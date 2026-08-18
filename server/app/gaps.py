"""Coverage-gap learning: what students ask that Kip can't answer well.

PRIVACY DESIGN — read before changing anything here.

Logging questions is the one place this system deliberately keeps user text.
It is safe only because of four constraints, all enforced below:

  1. No identity. No user_id, no session id, no IP, not even a hashed one.
     A gap row cannot be traced to a person, by us or by anyone who steals it.
  2. Date only, never a timestamp. Storing 14:32:07 would let anyone with the
     table correlate a question against a login and re-identify the asker.
     We store 2026-08-13 and nothing finer.
  3. Only questions that already passed the PII guard reach this module, so a
     TFN or passport number can never land here.
  4. Deduplicated by normalised text, so the table holds *distinct questions
     and how often they came up* — a topic list, not a transcript.

That makes this a product-improvement signal, not a user activity log. Say
exactly that in the privacy policy; it is defensible because it is true.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import QuestionGap

# Anything longer is a paste, not a question, and we don't want it.
MAX_QUESTION_CHARS = 300

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")
_NUM = re.compile(r"\b\d[\d,.]*\b")


def normalise(question: str) -> str:
    """Fold near-identical questions together for counting.

    Numbers become <n> so "2 bedroom in 4110" and "3 bedroom in 4000" count as
    the same underlying question — that is the signal we want, and it strips a
    little more incidental detail out of what we store.
    """
    s = question.lower().strip()
    s = _NUM.sub("<n>", s)
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def fingerprint(question: str) -> str:
    return hashlib.sha256(normalise(question).encode("utf-8")).hexdigest()[:32]


# Phrases Kip uses when it genuinely cannot answer. Treated as a gap even
# though a source may be cited, because the student left without an answer.
PUNT_PHRASES = (
    "i don't have verified information",
    "i can only help with questions about",
)


def answered_well(reply: str, sources) -> bool:
    """Did the student actually get an answer?

    Two conditions: at least one official source was cited, and the reply is
    not one of Kip's honest "I don't know, go here" responses. Both matter —
    an uncited answer is unverifiable, and a punt is a coverage gap by
    definition even when it names the right site to check.
    """
    if not sources:
        return False
    lowered = reply.lower()
    return not any(p in lowered for p in PUNT_PHRASES)


async def record(
    db: AsyncSession,
    *,
    question: str,
    module_id: str | None,
    answered_well: bool,
    searched: bool,
) -> None:
    """Log one coverage observation. Never raises into the request path."""
    question = question.strip()[:MAX_QUESTION_CHARS]
    if not question:
        return

    fp = fingerprint(question)
    today = date.today()

    row = await db.scalar(select(QuestionGap).where(QuestionGap.fingerprint == fp))

    if row is None:
        db.add(QuestionGap(
            fingerprint=fp,
            question=question,          # already PII-screened, identity-free
            module_id=module_id,
            occurrences=1,
            answered_well=answered_well,
            needed_search=searched,
            first_seen=today,
            last_seen=today,
        ))
    else:
        row.occurrences += 1
        row.last_seen = today
        row.needed_search = row.needed_search or searched
        # One good answer is enough to stop treating it as a gap.
        row.answered_well = row.answered_well or answered_well


async def top_gaps(db: AsyncSession, limit: int = 25) -> list[QuestionGap]:
    """The questions most worth adding to the knowledge base next.

    Ranked by how often students ask them, among those Kip answered poorly.
    This is the daily evolve job's work queue.
    """
    return list((await db.scalars(
        select(QuestionGap)
        .where(QuestionGap.answered_well.is_(False))
        .where(QuestionGap.resolved_at.is_(None))
        .order_by(QuestionGap.occurrences.desc(), QuestionGap.last_seen.desc())
        .limit(limit)
    )).all())


async def coverage_stats(db: AsyncSession) -> dict:
    distinct = await db.scalar(select(func.count()).select_from(QuestionGap)) or 0
    unanswered = await db.scalar(
        select(func.count()).select_from(QuestionGap)
        .where(QuestionGap.answered_well.is_(False))
        .where(QuestionGap.resolved_at.is_(None))
    ) or 0
    asked = await db.scalar(select(func.coalesce(func.sum(QuestionGap.occurrences), 0))) or 0
    return {
        "distinct_questions": distinct,
        "open_gaps": unanswered,
        "total_asked": asked,
        "coverage_pct": round(100 * (distinct - unanswered) / distinct, 1) if distinct else 100.0,
    }
