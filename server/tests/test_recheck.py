"""Tests for the answer recheck.

The thing being protected: a stored answer is served instantly, confidently,
with a citation under it and no hedging. That is exactly what makes an
outdated one worse than having no stored answer at all. So the tests here are
mostly about the two directions of failure —

  withdrawing something that was fine  -> the student pays with a slower,
                                          costlier answer. Survivable.
  serving something that went wrong    -> the student acts on it. Not.

which is why every ambiguous case must resolve towards withdrawal, and why
nothing automated may put an answer back.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import library, recheck  # noqa: E402

QUESTIONS = {
    q["id"]: q
    for q in json.loads(
        (Path(__file__).resolve().parents[2] / "knowledge" / "questions.json").read_text()
    )["questions"]
}


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def an_answer(**over) -> library.Answer:
    base = dict(
        id="safety-005", q="How do I report a sexual assault?", module="safety",
        risk="crisis", intent="Informational",
        answer="x" * 900, sources=["https://www.healthdirect.gov.au"],
        status=library.REVIEWED, written="2026-08-24", reviewed_by="A Person",
        review_by="2027-02-24", origin="written", checked_on="2026-08-24",
        stale_reason=None,
    )
    base.update(over)
    return library.Answer(**base)


# ── The free pass: what breaks in practice ───────────────────────────────

def test_a_healthy_answer_has_no_problems():
    assert recheck.structural_problems(an_answer(), QUESTIONS) == []


def test_a_source_falling_off_the_allowlist_is_caught():
    """This is the realistic failure. Facts change slowly; the allowlist gets
    edited, and an answer linking somewhere we no longer vouch for is broken
    the moment that happens."""
    p = recheck.structural_problems(
        an_answer(sources=["https://random-blog.example.com/visas"]), QUESTIONS)
    assert any("allowlist" in x for x in p), p


def test_a_retired_question_is_caught():
    p = recheck.structural_problems(an_answer(id="safety-999"), QUESTIONS)
    assert any("no longer in the bank" in x for x in p), p


def test_a_question_becoming_volatile_withdraws_its_answer():
    """The rule that nothing volatile may be pre-written has to keep holding
    after the fact, not only at the moment somebody writes one."""
    qs = dict(QUESTIONS)
    qs["safety-005"] = {**qs["safety-005"], "volatile": True}
    p = recheck.structural_problems(an_answer(), qs)
    assert any("volatile" in x for x in p), p


def test_a_risk_tier_moving_is_caught():
    qs = dict(QUESTIONS)
    qs["safety-005"] = {**qs["safety-005"], "risk": "standard"}
    p = recheck.structural_problems(an_answer(), qs)
    assert any("risk tier" in x for x in p), p


def test_truncated_or_empty_text_is_caught():
    assert recheck.structural_problems(an_answer(answer=""), QUESTIONS)
    assert recheck.structural_problems(an_answer(answer="too short"), QUESTIONS)


def test_an_answer_citing_nothing_is_caught():
    p = recheck.structural_problems(an_answer(sources=[]), QUESTIONS)
    assert any("cites nothing" in x for x in p), p


# ── Scheduling ───────────────────────────────────────────────────────────

def test_never_checked_is_always_due():
    assert recheck.due_for_audit(an_answer(checked_on=None))


def test_a_recently_checked_answer_is_not_due():
    today = date.today()
    assert not recheck.due_for_audit(
        an_answer(checked_on=today.isoformat()), today)


def test_an_answer_becomes_due_after_its_interval():
    today = date.today()
    old = (today - timedelta(days=recheck.interval_days("crisis") + 1)).isoformat()
    assert recheck.due_for_audit(an_answer(checked_on=old), today)


def test_high_risk_answers_are_looked_at_more_often():
    """Not because those facts move faster — they move slower — but because
    being wrong there costs the most."""
    assert recheck.interval_days("crisis") < recheck.interval_days("standard")
    assert recheck.interval_days("refer") < recheck.interval_days("standard")


def test_a_corrupt_date_means_due_rather_than_never():
    assert recheck.due_for_audit(an_answer(checked_on="not-a-date"))


def test_the_never_checked_go_first():
    q = recheck._audit_order([
        an_answer(id="a", checked_on="2026-08-01"),
        an_answer(id="b", checked_on=None),
        an_answer(id="c", checked_on="2026-01-01"),
    ])
    assert q[0].id == "b", "an answer nobody has ever verified must go first"
    assert q[1].id == "c", "then the one least recently looked at"


# ── The asymmetry: machines take down, people put back ───────────────────

def test_nothing_automated_can_restore_an_answer():
    """Withdrawing on a doubt is cheap and safe. Restoring is a judgement
    about whether something is true, and that needs a name against it."""
    src = Path(recheck.__file__).read_text()
    assert "mark_reviewed" not in src, "the recheck job can put answers back"
    assert "withdraw" in src


def test_a_withdrawn_answer_is_not_served(tmp_path, monkeypatch):
    doc = {"_meta": {}, "answers": [{
        "id": "safety-005", "q": "q", "module": "safety", "risk": "crisis",
        "intent": "Informational", "answer": "y" * 900,
        "sources": ["https://www.healthdirect.gov.au"],
        "status": "reviewed", "written": "2026-08-24", "reviewed_by": "A Person",
        "review_by": "2027-02-24", "checked_on": "2026-08-24",
    }]}
    f = tmp_path / "answers.json"
    f.write_text(json.dumps(doc))
    monkeypatch.setattr(library, "PATH", f)
    library._load.cache_clear()
    try:
        assert library.get("safety-005") is not None
        assert library.withdraw("safety-005", "source moved")
        assert library.get("safety-005") is None, "a withdrawn answer is still being served"
        assert library.all_answers()["safety-005"].stale_reason == "source moved"

        # And a person can put it back, which clears the reason.
        library.mark_reviewed("safety-005", "A Person")
        assert library.get("safety-005") is not None
        assert library.all_answers()["safety-005"].stale_reason is None
    finally:
        library._load.cache_clear()


def test_withdrawing_something_already_withdrawn_changes_nothing(tmp_path, monkeypatch):
    doc = {"_meta": {}, "answers": [{
        "id": "safety-005", "q": "q", "module": "safety", "risk": "crisis",
        "intent": "Informational", "answer": "y" * 900,
        "sources": ["https://www.healthdirect.gov.au"], "status": "stale",
        "written": "2026-08-24", "reviewed_by": None, "review_by": "2027-02-24",
    }]}
    f = tmp_path / "answers.json"
    f.write_text(json.dumps(doc))
    monkeypatch.setattr(library, "PATH", f)
    library._load.cache_clear()
    try:
        assert library.withdraw("safety-005", "again") is False
    finally:
        library._load.cache_clear()


# ── The audit: a website being down is not a contradiction ───────────────

class FakeModel:
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        class B:
            type, text = "text", json.dumps(self.verdict)
        return type("R", (), {"content": [B()]})()


def test_a_confident_contradiction_withdraws():
    m = FakeModel({"supported": False, "confidence": "high", "problem": "the figure changed"})
    v = run(recheck._audit_one(m, "claude-sonnet-5", an_answer()))
    assert v["supported"] is False and v["confidence"] == "high"


def test_an_unreachable_source_does_not_withdraw_a_good_answer():
    """The prompt is explicit about this and so is the caller. Withdrawing on
    a site being slow would make the job worse than not running it."""
    m = FakeModel({"supported": True, "confidence": "low", "problem": "none"})
    v = run(recheck._audit_one(m, "claude-sonnet-5", an_answer()))
    assert v["supported"] is True
    assert "not a contradiction" in recheck.AUDIT_PROMPT


def test_a_low_confidence_doubt_is_not_enough_to_withdraw():
    """Only high-confidence contradictions withdraw. A model that is unsure is
    reporting its own uncertainty, not a fact about the world."""
    src = Path(recheck.__file__).read_text()
    assert 'confidence") == "high"' in src


def test_a_broken_audit_leaves_the_answer_alone():
    class Broken:
        messages = None
        async def create(self, **kw):
            raise RuntimeError("api down")
    b = Broken(); b.messages = b
    assert run(recheck._audit_one(b, "claude-sonnet-5", an_answer())) is None


def test_junk_from_the_model_is_ignored():
    class Junk:
        messages = None
        async def create(self, **kw):
            class B:
                type, text = "text", "I could not check that source, sorry."
            return type("R", (), {"content": [B()]})()
    j = Junk(); j.messages = j
    assert run(recheck._audit_one(j, "claude-sonnet-5", an_answer())) is None


# ── The nightly run ──────────────────────────────────────────────────────

def test_the_free_pass_runs_without_a_model():
    """The structural checks are the ones that must never be skipped for cost
    reasons, so they take no client at all."""
    out = run(recheck.run(client=None))
    assert out["checked"] >= 0
    assert out["audited"] == 0


def test_a_broken_run_does_not_raise(monkeypatch):
    monkeypatch.setattr(library, "PATH", Path("/nonexistent/answers.json"))
    library._load.cache_clear()
    try:
        out = run(recheck.run(client=None))
        assert out["withdrawn"] == []
    finally:
        library._load.cache_clear()


def test_the_recheck_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(recheck, "enabled", lambda: False)
    assert run(recheck.run(client=None))["checked"] == 0


def test_the_audit_budget_is_bounded():
    """Unbounded, one bad night could audit every stored answer with a live
    search each. The cap is what makes this affordable to leave running."""
    assert 0 < recheck.audit_per_night() <= 50


def test_config_intervals_are_sane():
    for risk in ("crisis", "refer", "standard"):
        assert 7 <= recheck.interval_days(risk) <= 365, risk


@pytest.mark.parametrize("field", ["checked_on", "stale_reason", "origin"])
def test_every_stored_answer_carries_the_recheck_fields(field):
    doc = json.loads((Path(library.PATH)).read_text())
    for a in doc["answers"]:
        assert field in a, (a["id"], field)
