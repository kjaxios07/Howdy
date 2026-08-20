"""Tests for the answer cache.

The cache is the biggest cost lever at scale, which makes it the most
dangerous thing to get slightly wrong: a stale or misrouted answer is worse
than an expensive one. Most of these are about what it must REFUSE to serve.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import answercache as ac  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, k):
        return self.kv.get(k)

    async def setex(self, k, ttl, v):
        self.kv[k], self.ttl[k] = v, ttl

    async def incr(self, k):
        self.kv[k] = str(int(self.kv.get(k, 0)) + 1)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(ac, "redis_client", lambda: r)
    return r


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


GOOD = "You can apply for a Tax File Number free on the ATO website. It takes about 20 minutes and arrives within 28 days. **Sources:** https://www.ato.gov.au"


# ── What it must refuse to store ─────────────────────────────────────────

def test_crisis_topics_are_never_cached():
    """A student in trouble gets an answer written for them, now — not one
    written for somebody else last Tuesday. Same reasoning as exempting these
    topics from quotas."""
    for module in ("safety", "rights"):
        stored = run(ac.put("i am being underpaid", module, reply=GOOD,
                            sources=[], verified=True, searched=False))
        assert stored is False, module
        assert run(ac.get("i am being underpaid", module)) is None


def test_unverified_answers_are_never_cached():
    """The citation check stripped something. Re-serving that would multiply
    one bad answer across everyone who asks."""
    assert run(ac.put("q", "tax", reply=GOOD, sources=[], verified=False, searched=False)) is False


def test_a_stub_answer_is_not_worth_caching():
    assert run(ac.put("q", "tax", reply="Sorry, no.", sources=[],
                      verified=True, searched=False)) is False


def test_cache_can_be_turned_off_entirely(monkeypatch):
    monkeypatch.setattr(ac, "enabled", lambda: False)
    assert run(ac.put("q", "tax", reply=GOOD, sources=[], verified=True, searched=False)) is False
    assert run(ac.get("q", "tax")) is None


# ── What it stores, and for how long ─────────────────────────────────────

def test_a_good_library_answer_round_trips():
    assert run(ac.put("How do I apply for a TFN?", "tax", reply=GOOD,
                      sources=[{"domain": "ato.gov.au", "url": "https://www.ato.gov.au"}],
                      verified=True, searched=False))
    hit = run(ac.get("How do I apply for a TFN?", "tax"))
    assert hit is not None
    assert hit.reply == GOOD
    assert hit.sources[0]["domain"] == "ato.gov.au"
    assert hit.verified is True


def test_searched_answers_expire_far_sooner_than_library_ones():
    """Whether it searched IS the volatility signal — the same idea the
    nightly verify job runs on. A figure that can move must not be served
    from memory for days."""
    stable = ac.ttl_for(searched=False)
    volatile = ac.ttl_for(searched=True)
    assert volatile < stable
    assert volatile <= 3600, "a live figure should not survive an hour"
    assert stable >= 3600, "a stable explanation should outlive a single session"


def test_a_degraded_answer_does_not_outlive_the_lean_period():
    """An answer written with live checking switched off by the budget guard is
    still a good answer, but it must not become the canonical one for two days
    — it would outlast the reason it was written that way."""
    assert ac.ttl_for(searched=False, degraded=True) == ac.ttl_for(searched=True)
    assert ac.ttl_for(searched=False, degraded=True) < ac.ttl_for(searched=False)


def test_ttl_actually_applied(fake):
    run(ac.put("what is a tfn", "tax", reply=GOOD, sources=[], verified=True, searched=False))
    run(ac.put("minimum wage now", "work", reply=GOOD, sources=[], verified=True, searched=True))
    ttls = sorted(fake.ttl.values())
    assert ttls[0] == ac.ttl_for(searched=True)
    assert ttls[1] == ac.ttl_for(searched=False)


# ── Keying: the ways a cache serves the wrong person the wrong answer ────

def test_the_same_question_in_different_topics_does_not_collide():
    run(ac.put("what are my rights", "housing", reply=GOOD + " housing",
               sources=[], verified=True, searched=False))
    assert run(ac.get("what are my rights", "work")) is None


def test_state_is_part_of_the_key():
    """A concession answer for Queensland served to someone in Victoria would
    be worse than no cache at all — it is how a student gets fined."""
    run(ac.put("do I get a concession", "discounts", reply=GOOD + " QLD",
               sources=[], verified=True, searched=False, state="QLD"))
    assert run(ac.get("do I get a concession", "discounts", "VIC")) is None
    assert run(ac.get("do I get a concession", "discounts", "QLD")) is not None


def test_wording_differences_still_hit():
    """Case and punctuation should not buy the same answer twice."""
    run(ac.put("How do I apply for a TFN?", "tax", reply=GOOD,
               sources=[], verified=True, searched=False))
    assert run(ac.get("how do i apply for a tfn", "tax")) is not None


def test_different_questions_do_not_share_an_answer():
    run(ac.put("How do I apply for a TFN?", "tax", reply=GOOD,
               sources=[], verified=True, searched=False))
    assert run(ac.get("What is the minimum wage?", "tax")) is None


def test_numbers_folded_out_of_the_key_do_not_leak_across_suburbs():
    """gaps.fingerprint folds numbers, which is right for counting topics but
    would be wrong here if a postcode changed the answer. Postcode-sensitive
    topics carry the state in the key instead — this documents that the two
    mechanisms have to be used together."""
    run(ac.put("rooms near 4110", "housing", reply=GOOD,
               sources=[], verified=True, searched=False, state="QLD"))
    assert run(ac.get("rooms near 3000", "housing", "VIC")) is None


# ── Failure behaviour ────────────────────────────────────────────────────

def test_a_broken_cache_is_a_miss_not_an_error(monkeypatch):
    """A cache fault must degrade to asking the model, never to a 500."""
    class Broken:
        async def get(self, k):
            raise RuntimeError("redis down")

        async def setex(self, *a):
            raise RuntimeError("redis down")

    monkeypatch.setattr(ac, "redis_client", lambda: Broken())
    assert run(ac.get("q", "tax")) is None
    assert run(ac.put("q", "tax", reply=GOOD, sources=[],
                      verified=True, searched=False)) is False


def test_corrupt_entry_is_a_miss(fake):
    fake.kv[ac.key("q", "tax")] = "{not json"
    assert run(ac.get("q", "tax")) is None


# ── Privacy ──────────────────────────────────────────────────────────────

def test_entries_hold_no_identity(fake):
    run(ac.put("How do I apply for a TFN?", "tax", reply=GOOD,
               sources=[], verified=True, searched=False))
    blob = next(v for k, v in fake.kv.items() if k.startswith("ac:"))
    stored = json.loads(blob)
    assert set(stored) == {"reply", "sources", "verified", "searched"}
    for forbidden in ("user", "user_id", "session", "ip", "email"):
        assert forbidden not in stored


def test_the_key_carries_no_identity():
    k = ac.key("How do I apply for a TFN?", "tax", "QLD")
    assert k.startswith("ac:")
    assert "user" not in k and "@" not in k


def test_cache_is_not_a_database_table():
    """Same stance as the quota counters: this is ephemeral state with a TTL,
    not a durable record of what people asked."""
    from app import models

    tables = {v.__tablename__ for v in vars(models).values() if hasattr(v, "__tablename__")}
    assert not any("cache" in t or "answer_cache" in t for t in tables), tables


# ── Hit-rate accounting ──────────────────────────────────────────────────

def test_hit_rate_is_counted():
    for _ in range(3):
        run(ac.note(True))
    run(ac.note(False))
    s = run(ac.stats())
    assert s["hits"] == 3 and s["misses"] == 1
    assert s["hit_rate"] == pytest.approx(0.75)


def test_hit_rate_with_no_traffic_is_zero_not_a_crash():
    assert run(ac.stats())["hit_rate"] == 0.0
