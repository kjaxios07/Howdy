"""Tests for the coverage-gap learning loop.

Most of these are privacy tests. Logging user questions is the one place this
system keeps user text, and it is only defensible while these hold.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import gaps  # noqa: E402
from app.models import QuestionGap  # noqa: E402

QUESTIONS = Path(__file__).parents[2] / "knowledge" / "questions.json"


# ── The seed bank ────────────────────────────────────────────────────────

def test_question_bank_has_200():
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    assert data["_meta"]["count"] == 200
    assert len(data["questions"]) == 200


def test_every_question_maps_to_a_real_module():
    from app.modules import MODULE_IDS

    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    for item in data["questions"]:
        assert item["module"] in MODULE_IDS, f"{item['id']} → unknown module {item['module']}"


def test_question_ids_are_unique():
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    ids = [i["id"] for i in data["questions"]]
    assert len(ids) == len(set(ids))


def test_volatile_questions_are_flagged():
    """Questions whose answers contain changing figures must be marked, or the
    daily verify job has nothing to re-check."""
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    volatile = [i for i in data["questions"] if i["volatile"]]
    assert len(volatile) >= 20, "too few volatile questions — the verify job would be idle"

    wage = next(i for i in data["questions"] if "minimum wage" in i["q"].lower())
    assert wage["volatile"] is True, "the minimum wage changes every July"


# ── Normalisation and fingerprinting ─────────────────────────────────────

def test_numbers_are_folded_out():
    """'2 bedroom in 4110' and '3 bedroom in 4000' are the same question."""
    a = gaps.normalise("Two bedroom house near 4110 Brisbane")
    b = gaps.normalise("Two bedroom house near 4000 Brisbane")
    assert a == b


def test_case_and_punctuation_do_not_split_a_question():
    assert gaps.fingerprint("How do I apply for a TFN?") == \
           gaps.fingerprint("how do i apply for a tfn")


def test_different_questions_get_different_fingerprints():
    assert gaps.fingerprint("How do I apply for a TFN?") != \
           gaps.fingerprint("What is the minimum wage?")


def test_fingerprint_is_short_and_stable():
    fp = gaps.fingerprint("test question")
    assert len(fp) == 32
    assert fp == gaps.fingerprint("test question")


# ── Privacy invariants ───────────────────────────────────────────────────

def test_gap_table_has_no_identity_columns():
    """A gap row must never be traceable to a person."""
    columns = {c.name for c in QuestionGap.__table__.columns}
    forbidden = {"user_id", "session_id", "ip", "ip_hash", "email", "google_sub"}
    assert not (columns & forbidden), f"identity column on question_gaps: {columns & forbidden}"


def test_seen_dates_are_date_not_datetime():
    """A timestamp would allow correlating a question against a login.

    This is a deliberate privacy control — if someone 'fixes' these to DateTime
    for convenience, re-identification becomes possible and this test fails.
    """
    from sqlalchemy import Date

    for column in ("first_seen", "last_seen", "resolved_at"):
        col_type = QuestionGap.__table__.columns[column].type
        assert isinstance(col_type, Date), f"{column} must be Date, not {col_type}"


def test_question_length_is_capped():
    assert gaps.MAX_QUESTION_CHARS <= 300, "long pastes should never be stored"


# ── Answer-quality heuristic ─────────────────────────────────────────────

def test_uncited_answer_counts_as_a_gap():
    assert gaps.answered_well("Here is an answer.", []) is False


def test_punt_counts_as_a_gap_even_with_a_source():
    reply = "I don't have verified information on that — check immi.homeaffairs.gov.au."
    assert gaps.answered_well(reply, [{"domain": "immi.homeaffairs.gov.au", "url": "x"}]) is False


def test_cited_substantive_answer_is_not_a_gap():
    reply = "You can work **48 hours per fortnight**. **Sources:** https://immi.homeaffairs.gov.au"
    assert gaps.answered_well(reply, [{"domain": "immi.homeaffairs.gov.au", "url": "x"}]) is True
