"""Tests for free-tier allowances.

The one that matters most is `test_safety_is_never_rationed`. Everything else
is tuning; that one is the product's ethics expressed as an assertion.

The counters need Redis, so the sliding-window behaviour is exercised against
a small fake rather than a live server — the logic under test is ours, not
Redis's.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import quota  # noqa: E402


# ── A minimal stand-in for the bits of Redis we use ──────────────────────

class FakeRedis:
    def __init__(self):
        self.sets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction=True):
        return FakePipe(self)

    async def zrem(self, key, member):
        self.sets.get(key, {}).pop(member, None)

    async def zrange(self, key, start, stop, withscores=False):
        items = sorted(self.sets.get(key, {}).items(), key=lambda kv: kv[1])
        sliced = items[start : (stop + 1 if stop >= 0 else None)]
        return sliced if withscores else [k for k, _ in sliced]


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def zremrangebyscore(self, key, lo, hi):
        self.ops.append(("trim", key, hi))

    def zadd(self, key, mapping):
        self.ops.append(("add", key, mapping))

    def zcard(self, key):
        self.ops.append(("card", key, None))

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))

    async def execute(self):
        out = []
        for op, key, arg in self.ops:
            s = self.r.sets.setdefault(key, {})
            if op == "trim":
                for m, score in list(s.items()):
                    if score <= arg:
                        del s[m]
                out.append(None)
            elif op == "add":
                s.update(arg)
                out.append(1)
            elif op == "card":
                out.append(len(s))
            else:
                out.append(True)
        return out


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(quota, "redis_client", lambda: r)
    return r


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── Safety ───────────────────────────────────────────────────────────────

def test_safety_is_never_rationed():
    """The whole point. A student in trouble must never meet a counter —
    not when signed out, not after burning every other allowance."""
    for tier in ("guest", "free", "deals"):
        for _ in range(200):
            d = run(quota.check("someone", "safety", tier))
            assert d.allowed, f"safety blocked on {tier}"
            assert d.exempt


def test_exempt_modules_include_safety_and_rights():
    ex = quota.exempt_modules()
    assert "safety" in ex, "family violence, scams, mental health live here"
    assert "rights" in ex, "underpayment and legal rights must not be rationed"


def test_exempt_questions_do_not_consume_the_daily_total():
    """Asking about safety must not quietly eat the allowance for everything
    else — otherwise the exemption is only half real."""
    for _ in range(50):
        run(quota.check("s1", "safety", "guest"))
    d = run(quota.check("s1", "housing", "guest"))
    assert d.allowed


# ── The three counters ───────────────────────────────────────────────────

def test_per_topic_cap_bites_before_the_daily_cap():
    limits = quota.allowance("free")
    for i in range(limits["per_topic"]):
        assert run(quota.check("s2", "housing", "free")).allowed, i
    blocked = run(quota.check("s2", "housing", "free"))
    assert not blocked.allowed
    assert blocked.counter == "per_topic"


def test_running_out_on_one_topic_leaves_the_others_working():
    """A student stuck on housing should not lose their visa questions."""
    for _ in range(quota.allowance("free")["per_topic"] + 3):
        run(quota.check("s3", "housing", "free"))
    assert run(quota.check("s3", "visa", "free")).allowed


def test_daily_total_stops_topic_hopping():
    """Otherwise per-topic caps are trivially beaten by rotating topics."""
    limits = quota.allowance("free")
    topics = ["housing", "visa", "work", "tax", "health", "money", "study", "transport"]
    allowed = 0
    for i in range(limits["per_day"] + 20):
        if run(quota.check("s4", topics[i % len(topics)], "free")).allowed:
            allowed += 1
    assert allowed == limits["per_day"]


def test_search_cap_is_separate_and_tighter():
    """Searches are the expensive part — 2.04c against 0.43c — so they get
    their own, lower ceiling."""
    limits = quota.allowance("free")
    assert limits["searches"] < limits["per_day"]
    for _ in range(limits["searches"]):
        assert run(quota.check("s5", "cost", "free", will_search=True)).allowed
    d = run(quota.check("s5", "cost", "free", will_search=True))
    assert not d.allowed and d.counter == "searches"


def test_running_out_of_searches_still_allows_library_answers():
    """Out of searches is not out of Kip. The library still answers.

    Spread across topics so the per-topic cap is not what blocks — this is
    testing the search counter specifically.
    """
    topics = ["cost", "visa", "work", "tax", "health", "money", "study", "transport",
              "housing", "travel", "arrive", "culture"]
    for i in range(quota.allowance("free")["searches"] + 2):
        run(quota.check("s6", topics[i % len(topics)], "free", will_search=True))
    assert run(quota.check("s6", "culture", "free", will_search=False)).allowed


def test_a_question_blocked_on_search_does_not_burn_a_topic_slot():
    """You should not be charged for a question you were not allowed to ask.

    Consuming counters as they were checked meant a search-blocked question
    had already spent a topic slot and a daily slot.
    """
    limits = quota.allowance("free")
    topics = ["visa", "work", "tax", "health", "money", "study", "transport", "cost"]
    for i in range(limits["searches"]):
        run(quota.check("s6b", topics[i % len(topics)], "free", will_search=True))

    before = run(quota.status("s6b", "free"))["per_day"]["remaining"]
    for _ in range(5):
        blocked = run(quota.check("s6b", "housing", "free", will_search=True))
        assert not blocked.allowed and blocked.counter == "searches"
    after = run(quota.status("s6b", "free"))["per_day"]["remaining"]
    assert after == before, "a refused question spent part of the daily allowance"
    assert run(quota.check("s6b", "housing", "free", will_search=False)).allowed


# ── Tiers ────────────────────────────────────────────────────────────────

def test_tiers_increase_monotonically():
    g, f, d = (quota.allowance(t) for t in ("guest", "free", "deals"))
    for k in ("per_topic", "per_day", "searches"):
        assert g[k] < f[k] < d[k], k


def test_tier_selection():
    assert quota.tier_for(signed_in=False, subscribed=False) == "guest"
    assert quota.tier_for(signed_in=True, subscribed=False) == "free"
    assert quota.tier_for(signed_in=True, subscribed=True) == "deals"
    # A subscription implies an account; never downgrade a paying user.
    assert quota.tier_for(signed_in=False, subscribed=True) == "deals"


def test_guest_allowance_is_a_taste_not_a_wall():
    """Signed out should still prove Kip works — the nudge to sign in comes
    after it has helped, not before the first question."""
    g = quota.allowance("guest")
    assert g["per_day"] >= 5
    assert g["per_topic"] >= 3


def test_deals_cap_bounds_worst_case_exposure():
    """The cap's job is to bound abuse, not to guarantee margin on every user.

    Realistic use is well under the $5 price. What must not happen is one
    person at the ceiling every day for a month costing a wild multiple of it,
    so the exposure is deliberately held near 2x and asserted here.
    """
    d = quota.allowance("deals")
    SEARCHED, LIBRARY, PRICE = 0.0204, 0.0043, 5.00   # measured, see app/costs.py

    worst = (d["searches"] * SEARCHED + (d["per_day"] - d["searches"]) * LIBRARY) * 30
    assert worst < PRICE * 3, f"${worst:.2f}/month at the ceiling is more than 3x the price"

    typical = (2 * SEARCHED + 3 * LIBRARY) * 30      # 5 questions/day, 2 searched
    assert typical < PRICE / 2, f"${typical:.2f}/month for normal use leaves too little margin"


def test_free_tier_worst_case_is_affordable_at_scale():
    """The free tier is the real bill — it scales with signups, not revenue."""
    f = quota.allowance("free")
    worst_user = (f["searches"] * 0.0204 + (f["per_day"] - f["searches"]) * 0.0043) * 30
    assert worst_user < 5.00, (
        f"${worst_user:.2f}/month for one free user at the ceiling — a free abuser "
        "must never cost more than a paying subscriber pays"
    )

    typical = (6 * 0.0204 + 24 * 0.0043)          # 30 questions a month, 20% searched
    assert typical < 0.35, f"${typical:.2f}/month for a real free user"


# ── Windows and recovery ─────────────────────────────────────────────────

def test_window_is_rolling_not_a_calendar_day():
    """A calendar reset invites asking the cap at 23:59 and again at 00:01."""
    assert quota.window_seconds() == 24 * 3600


def test_allowance_returns_after_the_window(fake_redis):
    limits = quota.allowance("guest")
    for _ in range(limits["per_day"] + 5):
        run(quota.check("s7", "housing", "guest"))
    assert not run(quota.check("s7", "housing", "guest")).allowed

    # Age every recorded hit past the window.
    shift = quota.window_seconds() + 10
    for key, members in fake_redis.sets.items():
        fake_redis.sets[key] = {m: t - shift for m, t in members.items()}

    assert run(quota.check("s7", "housing", "guest")).allowed


def test_blocked_requests_do_not_hold_a_slot(fake_redis):
    """A refused question must not make the wait longer than it already is."""
    limits = quota.allowance("guest")
    for _ in range(limits["per_day"]):
        run(quota.check("s8", "housing", "guest"))
    before = sum(len(v) for v in fake_redis.sets.values())
    for _ in range(10):
        run(quota.check("s8", "housing", "guest"))
    assert sum(len(v) for v in fake_redis.sets.values()) == before


def test_status_does_not_spend_a_question():
    """Checking what's left is not using it."""
    run(quota.check("s9", "housing", "free"))
    first = run(quota.status("s9", "free"))
    for _ in range(5):
        run(quota.status("s9", "free"))
    assert run(quota.status("s9", "free"))["per_day"] == first["per_day"]


def test_people_are_counted_separately():
    limits = quota.allowance("guest")
    for _ in range(limits["per_day"] + 3):
        run(quota.check("personA", "housing", "guest"))
    assert run(quota.check("personB", "housing", "guest")).allowed


def test_zero_or_missing_limit_means_unlimited_not_blocked():
    """A config typo that drops a limit should open the gate, not close it —
    failing shut on a missing number would lock everyone out silently."""
    d = run(quota._hit("q:test:nolimit", 0, 3600, consume=True))
    assert d[0] is True


# ── What the student reads ───────────────────────────────────────────────

def test_messages_never_dead_end():
    """Every wall says when it lifts and that safety still works."""
    for counter in ("per_topic", "per_day", "searches"):
        for tier in ("guest", "free", "deals"):
            msg = quota.message(
                quota.Decision(allowed=False, counter=counter, retry_after=7200), tier
            )
            assert "safety" in msg.lower(), (tier, counter)
            assert "hour" in msg.lower() or "minute" in msg.lower(), (tier, counter)


def test_guest_message_offers_the_next_step():
    msg = quota.message(quota.Decision(allowed=False, counter="per_day", retry_after=3600), "guest")
    assert "sign" in msg.lower()
    assert "costs nothing" in msg.lower()


def test_topic_message_says_other_topics_still_work():
    msg = quota.message(
        quota.Decision(allowed=False, counter="per_topic", retry_after=3600), "free"
    )
    assert "other topics" in msg.lower()


def test_wait_is_phrased_in_human_units():
    assert quota._human_wait(300) == "5 minutes"
    assert quota._human_wait(3600) == "an hour"
    assert quota._human_wait(7200) == "2 hours"


# ── Privacy ──────────────────────────────────────────────────────────────

def test_quota_counters_are_not_a_database_table():
    """A per-topic table keyed to a user would be a durable record of which
    topics that person asks about — the exact profile this system refuses to
    build. Counters live in Redis and expire with the window."""
    from app import models

    tables = {v.__tablename__ for v in vars(models).values() if hasattr(v, "__tablename__")}
    assert not any("quota" in t or "usage" in t for t in tables), (
        f"quota state must not be persisted: {tables}"
    )
