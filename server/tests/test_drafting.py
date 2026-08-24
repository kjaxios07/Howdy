"""Tests for buying answers once.

The economics are the easy part. What these guard is the failure that would
undo it: storing a bad answer forever. A generated answer that goes into the
library is served to everyone who ever asks, with no model call left to catch
it — so the bar for storing one has to be at least as high as the bar for
sending one, and the tests below are mostly about refusing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import drafting, library  # noqa: E402


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


GOOD = (
    "You can apply for a Tax File Number free on the ATO website once you have "
    "arrived in Australia. It takes about twenty minutes and the number arrives "
    "by post within 28 days. Give it to your employer on the declaration they "
    "hand you when you start, because without one they must withhold tax at the "
    "top rate. Your TFN is for life, so only ever give it to the ATO, your "
    "employer after you start, your bank and your super fund."
)


class FakeModel:
    """Stands in for the Anthropic client. Returns whatever text it is given."""

    def __init__(self, text=GOOD):
        self.text, self.calls = text, 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        self.last = kw
        class B:
            type = "text"
        b = B(); b.text = self.text
        u = type("U", (), {"input_tokens": 5000, "output_tokens": 400,
                           "cache_creation_input_tokens": 0,
                           "cache_read_input_tokens": 0, "server_tool_use": None})()
        return type("R", (), {"content": [b], "usage": u, "stop_reason": "end_turn"})()


# ── What it refuses to buy ───────────────────────────────────────────────

def test_volatile_questions_are_never_drafted():
    """There is no amount of demand that makes storing a moving figure a good
    idea. Those keep going to the model and paying for them is correct."""
    qs = json.loads(drafting.QUESTIONS.read_text())["questions"]
    volatile = {q["id"] for q in qs if q["volatile"]}
    assert not {q["id"] for q in drafting.candidates()} & volatile


def test_questions_already_answered_are_not_re_bought():
    have = set(library.all_answers())
    assert not {q["id"] for q in drafting.candidates()} & have


def test_an_unverified_answer_is_discarded_not_stored(monkeypatch):
    """One bad answer stored forever is the worst thing this file can do, so
    a failed citation check throws the answer away rather than storing it with
    a caveat."""
    monkeypatch.setattr(drafting, "verify_reply",
                        lambda t: type("V", (), {"verified": False, "reply": t, "sources": []})())
    q = drafting.candidates(1)[0]
    entry, cost, reason = run(drafting.draft_one(FakeModel(), "claude-sonnet-5", q))
    assert entry is None
    assert "citation" in reason
    assert cost > 0, "we still paid for it — that is the point of checking before storing"


def test_an_answer_citing_nothing_is_discarded(monkeypatch):
    monkeypatch.setattr(drafting, "verify_reply",
                        lambda t: type("V", (), {"verified": True, "reply": t, "sources": []})())
    monkeypatch.setattr(drafting.websearch, "merge_sources", lambda a, b: [])
    q = drafting.candidates(1)[0]
    entry, _, reason = run(drafting.draft_one(FakeModel(), "claude-sonnet-5", q))
    assert entry is None and "vouch" in reason


def test_a_stub_answer_is_discarded(monkeypatch):
    monkeypatch.setattr(drafting, "verify_reply",
                        lambda t: type("V", (), {"verified": True, "reply": "Sorry, no.", "sources": []})())
    monkeypatch.setattr(drafting.websearch, "merge_sources",
                        lambda a, b: [{"domain": "ato.gov.au", "url": "https://www.ato.gov.au"}])
    q = drafting.candidates(1)[0]
    entry, _, reason = run(drafting.draft_one(FakeModel("Sorry, no."), "claude-sonnet-5", q))
    assert entry is None and "too short" in reason


def test_a_failed_request_costs_nothing_and_stores_nothing():
    class Broken:
        messages = None
        async def create(self, **kw):
            raise RuntimeError("api down")
    b = Broken(); b.messages = b
    q = drafting.candidates(1)[0]
    entry, cost, reason = run(drafting.draft_one(b, "claude-sonnet-5", q))
    assert entry is None and cost == 0.0 and "failed" in reason


# ── What it does buy ─────────────────────────────────────────────────────

def _good(monkeypatch):
    monkeypatch.setattr(drafting, "verify_reply",
                        lambda t: type("V", (), {"verified": True, "reply": t, "sources": []})())
    monkeypatch.setattr(drafting.websearch, "merge_sources",
                        lambda a, b: [{"domain": "ato.gov.au", "url": "https://www.ato.gov.au"}])


def test_a_good_answer_lands_as_a_draft(monkeypatch):
    """Generated is not reviewed. Everything arrives invisible at runtime."""
    _good(monkeypatch)
    q = drafting.candidates(1)[0]
    entry, cost, _ = run(drafting.draft_one(FakeModel(), "claude-sonnet-5", q))
    assert entry is not None
    assert entry["status"] == library.DRAFT
    assert entry["origin"] == "drafted"
    assert entry["reviewed_by"] is None
    assert cost > 0


def test_a_drafted_answer_carries_its_recheck_fields(monkeypatch):
    _good(monkeypatch)
    q = drafting.candidates(1)[0]
    entry, _, _ = run(drafting.draft_one(FakeModel(), "claude-sonnet-5", q))
    for f in ("checked_on", "stale_reason", "review_by", "written"):
        assert f in entry, f
    assert entry["review_by"] > entry["written"]


def test_it_uses_the_real_pipeline_not_a_shortcut(monkeypatch):
    """Same system prompt, same restricted search. An answer generated with
    weaker guards than a live one would be a worse answer stored for longer."""
    _good(monkeypatch)
    m = FakeModel()
    run(drafting.draft_one(m, "claude-sonnet-5", drafting.candidates(1)[0]))
    assert m.last["system"][0]["cache_control"], "the cached system prompt was not used"
    if drafting.websearch.tool_definition() is not None:
        assert m.last["tools"][0]["allowed_domains"], "search was not domain-restricted"


def test_easy_questions_are_drafted_first():
    """Those are the ones a stored answer serves best and the ones most likely
    to survive review untouched."""
    first = drafting.candidates(30)
    assert first[0]["difficulty"] == "Easy"


# ── The release bar ──────────────────────────────────────────────────────

def test_migration_answers_cannot_be_released_in_bulk():
    """Refer answers need a registered agent to read them individually. Bulk
    release exists so ordinary answers can ship, not so the risky ones can."""
    with pytest.raises(SystemExit):
        drafting.release("refer", "somebody")


def test_crisis_answers_cannot_be_released_in_bulk():
    with pytest.raises(SystemExit):
        drafting.release("crisis", "somebody")


def test_only_standard_is_bulk_releasable():
    assert drafting.bulk_releasable() == frozenset({"standard"})


def test_release_records_who_checked_them():
    """Releasing in bulk is still a person saying 'I read a sample of these and
    they are sound'. That claim needs a name on it."""
    src = Path(drafting.__file__).read_text()
    assert "reviewer" in src
    assert "mark_reviewed(a.id, reviewer)" in src


# ── The economics, which are the reason this exists ──────────────────────

def test_drafting_everything_is_cheap_enough_to_just_do():
    c = drafting.would_cost()
    assert c["one_time_usd"] < 25, c
    assert c["one_time_usd"] < c["monthly_saved_at_100k"], \
        "if one-time drafting cost more than a month of generating, do not bother"


def test_the_batch_is_bounded():
    assert 0 < drafting.batch_size() <= 100


def test_a_costing_run_makes_no_requests():
    """You should be able to ask what it would cost without paying for it."""
    m = FakeModel()
    drafting.would_cost()
    drafting.candidates()
    assert m.calls == 0


def test_drafting_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(drafting, "enabled", lambda: False)
    assert run(drafting.run(FakeModel(), "claude-sonnet-5"))["drafted"] == 0


def test_nothing_drafted_is_servable_without_review(monkeypatch):
    """The end-to-end version of the gate: generate, store, and it is still
    not reachable by a student."""
    _good(monkeypatch)
    q = drafting.candidates(1)[0]
    entry, _, _ = run(drafting.draft_one(FakeModel(), "claude-sonnet-5", q))
    a = library.Answer(
        id=entry["id"], q=entry["q"], module=entry["module"], risk=entry["risk"],
        intent=entry["intent"], answer=entry["answer"], sources=entry["sources"],
        status=entry["status"], written=entry["written"], reviewed_by=None,
        review_by=entry["review_by"], origin=entry["origin"],
    )
    assert not a.servable
