"""Hand-written answers for the questions where the wording carries weight.

Twenty-one of the 483 seeded questions are risk-tiered: nine `crisis` and
twelve `refer`. Those are the ones where what Kip says matters most and where
a generated answer is hardest to defend — a lawyer or a MARA-registered agent
can read fixed text and sign it off, and cannot do that for something composed
fresh each time. That, not cost, is the reason these exist. The answer cache
already removes about 98% of the spend on repeated questions; pre-writing adds
roughly a further 1.5%.

Three rules hold here, and each is enforced by a test rather than a comment:

**Nothing is served until a person has reviewed it.** Every answer starts at
`status: draft` and is invisible at runtime. Only a human moves that field,
and `python -m app.library review` is how. Shipping unreviewed text on exactly
the questions that need review would defeat the point of writing them.

**Nothing volatile is ever pre-written.** A figure that can move, served
instantly and confidently with a citation under it, is worse than a slow
correct answer — it is the concession-fine problem again, in a different
place.

**Every source must pass the same verifier the model's answers pass.** These
skip the model, so they must not skip the citation check with it.

Matching is deliberately by question id, not by text. A student who taps a
suggested question is an exact, unambiguous match with no model call at all.
Matching what somebody *typed* to one of these is a separate problem — the
current fingerprint is exact-match-only, so "how do i get a tfn" and "How do
I apply for a TFN?" are different keys — and guessing wrong here means
answering a question nobody asked, on the topics where that is least
forgivable. Until there is a matcher good enough to trust, this serves taps.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

REVIEWED, DRAFT = "reviewed", "draft"

# resolve() matters: imported through a relative sys.path entry — which is
# how the tests import it — an unresolved __file__ makes parents[2] point at
# the wrong directory, and _load swallows the miss as "no answers". A quiet
# fallback to no library is exactly the failure nobody notices.
PATH = Path(__file__).resolve().parents[2] / "knowledge" / "answers.json"


@dataclass(frozen=True)
class Answer:
    id: str
    q: str
    module: str
    risk: str
    intent: str
    answer: str
    sources: list
    status: str
    written: str
    reviewed_by: str | None
    review_by: str | None

    @property
    def servable(self) -> bool:
        return self.status == REVIEWED

    @property
    def overdue(self) -> bool:
        """Past its review date. Still served — pulling a reviewed crisis
        answer because a date passed would leave someone with nothing, which
        is worse. It shows up in `status` for a human to deal with."""
        if not self.review_by:
            return False
        try:
            return date.fromisoformat(self.review_by) < date.today()
        except ValueError:
            return False


@lru_cache(maxsize=1)
def _load() -> dict[str, Answer]:
    """Read the file once. A missing or broken file is not fatal — it means
    no pre-written answers, and every question goes to the model as before."""
    try:
        doc = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        log.warning("library_load_failed", exc_info=True)
        return {}
    out = {}
    for a in doc.get("answers", []):
        try:
            out[a["id"]] = Answer(
                id=a["id"], q=a["q"], module=a["module"], risk=a["risk"],
                intent=a.get("intent", ""), answer=a["answer"],
                sources=list(a.get("sources", [])), status=a.get("status", DRAFT),
                written=a.get("written", ""), reviewed_by=a.get("reviewed_by"),
                review_by=a.get("review_by"),
            )
        except KeyError:
            log.warning("library_entry_malformed id=%s", a.get("id"))
    return out


def all_answers() -> dict[str, Answer]:
    return dict(_load())


def get(question_id: str) -> Answer | None:
    """The reviewed answer for this question id, or None.

    A draft returns None. That is the gate: unreviewed text cannot reach a
    student even by accident, and the caller does not have to remember to
    check.
    """
    a = _load().get(question_id)
    return a if a and a.servable else None


def covers(question_id: str) -> bool:
    return get(question_id) is not None


def status() -> dict:
    """What is written, what is signed off, what is due for another look."""
    answers = list(_load().values())
    reviewed = [a for a in answers if a.servable]
    return {
        "written": len(answers),
        "reviewed": len(reviewed),
        "draft": len(answers) - len(reviewed),
        "overdue": sorted(a.id for a in reviewed if a.overdue),
        "by_risk": {
            r: {
                "written": sum(1 for a in answers if a.risk == r),
                "reviewed": sum(1 for a in reviewed if a.risk == r),
            }
            for r in sorted({a.risk for a in answers})
        },
    }


def print_status() -> None:
    """`python -m app.library`"""
    s = status()
    print(f"\n  PRE-WRITTEN ANSWERS — {s['written']} written, "
          f"{s['reviewed']} reviewed, {s['draft']} awaiting sign-off\n")
    for risk, n in s["by_risk"].items():
        state = "all signed off" if n["reviewed"] == n["written"] else \
                f"{n['written'] - n['reviewed']} still draft — NOT being served"
        print(f"  {risk:<8} {n['written']:>3} written   {state}")
    if s["overdue"]:
        print(f"\n  ⚠ past their review date: {', '.join(s['overdue'])}")
    if s["draft"]:
        print("\n  Drafts are invisible at runtime — those questions still go")
        print("  to the model. Sign one off with:")
        print("    python -m app.library review <id> \"<who reviewed it>\"\n")
    else:
        print()


def mark_reviewed(question_id: str, reviewer: str) -> None:
    """Record that a person has read and approved this answer.

    Deliberately a human action with a named reviewer, and deliberately not
    something any automated job can do. The value of these answers is that
    somebody qualified put their name to them.
    """
    doc = json.loads(PATH.read_text(encoding="utf-8"))
    for a in doc["answers"]:
        if a["id"] == question_id:
            a["status"] = REVIEWED
            a["reviewed_by"] = reviewer
            a["reviewed_on"] = date.today().isoformat()
            PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
            _load.cache_clear()
            print(f"  {question_id} signed off by {reviewer} — now served.")
            return
    raise SystemExit(f"no answer with id {question_id}")


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "review":
        mark_reviewed(sys.argv[2], " ".join(sys.argv[3:]))
    else:
        print_status()
