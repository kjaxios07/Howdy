"""Tests for the hand-written answers.

These twenty-one are the highest-stakes text in the product: nine crisis and
twelve refer. Most of what follows is not about the code — it is about the
content, because the content is the risk. A crisis answer that buries the
phone number, or a migration answer that drifts into telling somebody what
they qualify for, is a defect whatever the code around it does.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import library  # noqa: E402
from app.sources import _host_of, is_trusted  # noqa: E402

ANSWERS = library.all_answers()
CRISIS = [a for a in ANSWERS.values() if a.risk == "crisis"]
REFER = [a for a in ANSWERS.values() if a.risk == "refer"]


# ── The review gate ──────────────────────────────────────────────────────

def test_a_draft_is_never_served():
    """The whole point of pre-writing these is that a person signed them off.
    Serving one before that happens would defeat the exercise, so the gate is
    in get() rather than in the caller's memory."""
    drafts = [a for a in ANSWERS.values() if a.status != library.REVIEWED]
    for a in drafts:
        assert library.get(a.id) is None, a.id
        assert not library.covers(a.id)


# Modules that run on a timer with nobody watching. If any of these could
# sign an answer off, the signature would mean nothing — the whole value of a
# reviewed answer is that a person looked at it and can be asked why.
UNATTENDED = ("recheck.py", "evolve.py", "retention.py", "chat.py")


def test_nothing_that_runs_unattended_can_sign_an_answer_off():
    """mark_reviewed is reachable from human-invoked commands — that is how a
    reviewer records their sign-off, and drafting.release is one of them. What
    must never reach it is anything on a schedule."""
    app = Path(library.__file__).parent
    for name in UNATTENDED:
        for f in app.rglob(name):
            assert "mark_reviewed" not in f.read_text(), f"{name} can sign answers off"


def test_signing_off_always_records_a_name():
    """Every path to reviewed carries a reviewer through to the file. An
    anonymous sign-off is not a sign-off."""
    from app import drafting

    assert "reviewer" in Path(library.__file__).read_text()
    assert "mark_reviewed(a.id, reviewer)" in Path(drafting.__file__).read_text()
    with pytest.raises(TypeError):
        library.mark_reviewed("safety-005")  # no reviewer named


def test_every_answer_carries_its_review_dates():
    for a in ANSWERS.values():
        assert a.written, a.id
        assert a.review_by, a.id


def test_a_missing_file_is_not_fatal(monkeypatch):
    """No pre-written answers means every question goes to the model, exactly
    as it did before this module existed."""
    monkeypatch.setattr(library, "PATH", Path("/nonexistent/answers.json"))
    library._load.cache_clear()
    try:
        assert library.all_answers() == {}
        assert library.get("safety-005") is None
    finally:
        library._load.cache_clear()


# ── What may and may not be pre-written ──────────────────────────────────

def test_nothing_volatile_is_pre_written():
    """A figure that can move, served instantly with a citation under it, is
    worse than a slow correct answer. Same reasoning as the concession rule."""
    qs = json.loads((Path(__file__).parents[2] / "knowledge" / "questions.json").read_text())
    volatile = {q["id"] for q in qs["questions"] if q["volatile"]}
    assert not (set(ANSWERS) & volatile), set(ANSWERS) & volatile


def test_the_set_is_exactly_the_risk_tiered_questions():
    """Not a subset chosen by taste. Every crisis and refer question, and
    nothing else — so the coverage argument is checkable."""
    qs = json.loads((Path(__file__).parents[2] / "knowledge" / "questions.json").read_text())
    expected = {q["id"] for q in qs["questions"] if q["risk"] in ("crisis", "refer")}
    assert set(ANSWERS) == expected


def test_every_id_and_risk_agrees_with_the_question_bank():
    qs = {q["id"]: q for q in json.loads(
        (Path(__file__).parents[2] / "knowledge" / "questions.json").read_text())["questions"]}
    for a in ANSWERS.values():
        assert a.risk == qs[a.id]["risk"], a.id
        assert a.module == qs[a.id]["module"], a.id


# ── Sources ──────────────────────────────────────────────────────────────

def test_every_source_survives_the_real_verifier():
    """These skip the model. They must not skip the citation check with it."""
    for a in ANSWERS.values():
        assert a.sources, f"{a.id} cites nothing"
        for u in a.sources:
            assert is_trusted(_host_of(u)), f"{a.id}: {u} would be stripped"


def test_no_bare_urls_that_disagree_with_their_link_text():
    """The label/destination mismatch that got past me in the travel answers."""
    for a in ANSWERS.values():
        for host, url in re.findall(r"\*\*([a-z0-9.-]+\.(?:gov\.)?au)\*\*[^\n]{0,40}?(https?://\S+)?",
                                    a.answer):
            if url:
                assert host in url, f"{a.id}: text says {host}, link goes to {url}"


# ── Crisis answers: the number comes first ───────────────────────────────

EMERGENCY = ("000", "13 11 14", "1800 737 732", "1300 22 4636", "1800 022 222",
             "131 444", "1800 825 955", "1300 766 491")


def test_a_crisis_answer_leads_with_a_number_to_call():
    """Someone in trouble should not read a paragraph to find the number.
    Checked against the opening, not the whole answer."""
    for a in CRISIS:
        head = a.answer[:400]
        assert any(n in head for n in EMERGENCY), f"{a.id} buries the number:\n{head[:120]}"


# safety-037 (domestic violence) is deliberately not on the blanket
# reassurance. For someone on a partner visa the position genuinely is more
# complicated, and "your visa is not affected" would be a comforting sentence
# that is also wrong. It gets its own check below instead.
NUANCED = {"safety-037"}

REASSURANCE = (
    "not affect", "does not affect", "is not affected", "not at risk",
    "no bearing", "will not put your status", "not a visa problem",
    "does not touch your visa", "none of this touches your visa",
)


def test_every_crisis_answer_addresses_the_visa_fear():
    """The belief that asking for help endangers a visa is the single biggest
    reason international students do not call. Every crisis answer has to meet
    that fear head on — the wording varies, the obligation does not."""
    for a in CRISIS:
        low = a.answer.lower()
        assert "visa" in low, f"{a.id} never mentions the visa question at all"
        if a.id in NUANCED:
            continue
        assert any(p in low for p in REASSURANCE), a.id


def test_the_domestic_violence_answer_is_honest_rather_than_reassuring():
    """It must still tell someone their visa is not a trap — but by naming the
    family violence provisions and sending them to someone who can apply them,
    not by a blanket promise it cannot keep."""
    a = ANSWERS["safety-037"]
    low = a.answer.lower()
    assert "family violence provision" in low
    assert "mara.gov.au" in low
    assert "deported" in low or "deportation" in low, "the threat itself is unnamed"


def test_no_crisis_answer_gates_help_behind_anything():
    for a in CRISIS:
        low = a.answer.lower()
        for gate in ("kip plus", "subscribe", "upgrade", "$5", "$10", "paid plan"):
            assert gate not in low, (a.id, gate)


def test_crisis_answers_are_not_walls_of_text():
    """A person in distress reads the first screen and nothing else."""
    for a in CRISIS:
        assert len(a.answer) < 2200, (a.id, len(a.answer))


# ── Refer answers: where the Migration Act line sits ─────────────────────

def test_every_refer_answer_names_the_referral_and_how_to_verify_it():
    for a in REFER:
        assert "mara.gov.au" in a.answer.lower(), a.id


def test_no_refer_answer_tells_someone_what_they_qualify_for():
    """Giving immigration assistance unregistered is a criminal offence under
    the Migration Act 1958. The general information is lawful; the sentence
    about THIS person's prospects is not. These phrasings are the ones that
    cross it."""
    banned = (
        "you qualify", "you would qualify", "you are eligible",
        "you will be eligible", "you should apply for", "you can apply for the",
        "your best option", "i recommend you apply", "you will get pr",
        "you are likely to be invited",
    )
    for a in REFER:
        low = a.answer.lower()
        for phrase in banned:
            assert phrase not in low, f"{a.id} says '{phrase}'"


def test_refer_answers_do_not_quote_points_values():
    """Points values and thresholds move, and a stale one in an answer
    somebody plans a year around is the expensive kind of wrong."""
    for a in REFER:
        assert not re.search(r"\b\d{2,3}\s*points\b", a.answer.lower()), a.id
        assert not re.search(r"\+\s*\d+\s*points", a.answer.lower()), a.id


def test_refer_answers_say_plainly_that_this_is_not_advice():
    for a in REFER:
        low = a.answer.lower()
        assert any(p in low for p in (
            "cannot say", "not able to give", "cannot make", "is migration advice",
            "migration advice", "i cannot advise",
        )), a.id


# ── Shape, across both tiers ─────────────────────────────────────────────

def test_answers_are_substantial_enough_to_be_worth_serving():
    for a in ANSWERS.values():
        assert len(a.answer) > 400, (a.id, len(a.answer))


def test_no_answer_promises_an_outcome():
    for a in ANSWERS.values():
        low = a.answer.lower()
        for phrase in ("guaranteed", "we guarantee", "always approved", "100%"):
            assert phrase not in low or "nobody can guarantee" in low or "guaranteed visa" in low, (a.id, phrase)


def test_the_nightly_job_does_not_rewrite_this_file():
    """base.json is machine-written every night. Reviewed legal text in a
    regenerated file would be silently clobbered, so it lives apart and the
    job must not know about it."""
    job = (Path(__file__).parents[2] / "scripts" / "update-knowledge.js").read_text()
    assert "answers.json" not in job


def test_status_reports_what_is_actually_being_served():
    s = library.status()
    assert s["written"] == len(ANSWERS)
    assert s["reviewed"] + s["draft"] == s["written"]
    assert set(s["by_risk"]) == {"crisis", "refer"}


@pytest.mark.parametrize("tier,count", [("crisis", 9), ("refer", 12)])
def test_the_expected_number_of_each(tier, count):
    assert sum(1 for a in ANSWERS.values() if a.risk == tier) == count
