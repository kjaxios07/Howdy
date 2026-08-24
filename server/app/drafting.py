"""Buying each answer once instead of every time it is asked.

The whole seeded bank costs about **$8 to answer once**, with a live search
and the full citation check on each. Stored, they then serve free forever,
against roughly $430 a month to keep generating them at a hundred thousand
questions. Keeping them honest costs about $90 a year in rechecks. That is
the entire economics of this file.

It runs the real pipeline, not a shortcut: the same system prompt, the same
domain-restricted search, the same source verification that rejects anything
citing somewhere we do not vouch for. An answer that fails verification is
never stored — the point is to buy a *good* answer once, and a bad one stored
forever is the worst outcome available here.

Two rules it will not bend:

**Volatile questions are skipped, always.** Ninety-five of the bank contain a
figure that moves. Those keep going to the model every time, and paying for
them is the correct call.

**Nothing drafted here is served on the strength of having been generated.**
Everything lands as `draft`. Where it goes next depends on the stakes:

  standard  citation-verified and spot-checked — may be released in bulk
  refer     a registered migration agent reads it, individually
  crisis    a person who knows the services reads it, individually

That split is the practical compromise. Requiring a MARA agent to sign off
"do I have to tip in Australia?" would mean nothing ever ships; requiring
nobody to read the migration answers would be indefensible. The line sits
where the cost of being wrong changes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import library, websearch
from .appconfig import raw
from .costs import Usage, price
from .prompt import system_prompt
from .sources import verify_reply

log = logging.getLogger(__name__)

QUESTIONS = Path(library.PATH).parent / "questions.json"


def _cfg() -> dict:
    return raw().get("drafting", {})


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def batch_size() -> int:
    return int(_cfg().get("batch_size", 25))


def bulk_releasable() -> frozenset[str]:
    """Risk tiers where a spot-check is a proportionate level of review."""
    return frozenset(_cfg().get("bulk_releasable_risk", ["standard"]))


@dataclass
class Run:
    drafted: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        return {
            "drafted": len(self.drafted),
            "rejected": len(self.rejected),
            "skipped": len(self.skipped),
            "cost_usd": round(self.cost_usd, 4),
            "ids": self.drafted,
        }


def candidates(limit: int | None = None) -> list[dict]:
    """Questions worth buying an answer for, best first.

    Volatile ones are excluded outright rather than ranked last — there is no
    quantity of demand that makes storing a moving figure a good idea.
    """
    try:
        qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    except Exception:  # noqa: BLE001
        log.warning("drafting_questions_unreadable", exc_info=True)
        return []

    have = set(library.all_answers())
    todo = [q for q in qs if not q["volatile"] and q["id"] not in have]

    # Easy and Informational first: those are the ones a stored answer serves
    # best, and the ones most likely to survive review untouched.
    rank = {"Easy": 0, "Medium": 1, "Hard": 2}
    todo.sort(key=lambda q: (rank.get(q["difficulty"], 3), q["id"]))
    return todo[:limit] if limit else todo


def would_cost(n: int | None = None) -> dict:
    """What drafting would cost before committing to it. Runs no requests."""
    n = n if n is not None else len(candidates())
    searched, stored = 0.0204, 0.0043
    return {
        "questions": n,
        "one_time_usd": round(n * searched, 2),
        "monthly_saved_at_100k": round(100_000 * stored, 2),
        "note": "one-time; stored answers then serve at no model cost",
    }


async def draft_one(client, model: str, q: dict) -> tuple[dict | None, float, str]:
    """Buy one answer. Returns (entry or None, cost, reason_if_rejected)."""
    kwargs = {
        "model": model,
        "max_tokens": 1200,
        "system": [{"type": "text", "text": system_prompt(),
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": q["q"]}],
    }
    if (tool := websearch.tool_definition()) is not None:
        kwargs["tools"] = [tool]

    try:
        response = await client.messages.create(**kwargs)
    except Exception:  # noqa: BLE001
        log.warning("draft_failed id=%s", q["id"], exc_info=True)
        return None, 0.0, "the request failed"

    cost = price(model, Usage.from_api(response.usage)).total
    text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")

    trace = websearch.trace_from_response(response.content)
    checked = verify_reply(text)
    merged = websearch.merge_sources(checked.sources, trace)

    # The same bar the live pipeline holds answers to. Storing something that
    # failed verification would multiply one bad answer across everyone who
    # ever asks — the exact reason the answer cache refuses unverified text.
    if not checked.verified:
        return None, cost, "citation check rejected part of it"
    if not merged:
        return None, cost, "cited nothing we vouch for"
    if len(checked.reply) < 400:
        return None, cost, "too short to be worth storing"

    interval = int(raw().get("answer_review", {})
                   .get("check_interval_days", {}).get(q["risk"], 120))
    return {
        "id": q["id"], "q": q["q"], "module": q["module"], "risk": q["risk"],
        "intent": q["intent"], "answer": checked.reply,
        "sources": [s["url"] for s in merged],
        "written": date.today().isoformat(),
        "status": library.DRAFT,
        "origin": "drafted",
        "reviewed_by": None, "reviewed_on": None,
        "review_by": (date.today() + timedelta(days=interval)).isoformat(),
        "checked_on": None, "stale_reason": None,
    }, cost, ""


async def run(client, model: str, limit: int | None = None) -> dict:
    """Draft a batch. Writes each one as it lands, so an interrupted run keeps
    what it already paid for."""
    result = Run()
    if not enabled():
        return result.as_dict()

    todo = candidates(limit or batch_size())
    for q in todo:
        entry, cost, reason = await draft_one(client, model, q)
        result.cost_usd += cost
        if entry is None:
            result.rejected.append({"id": q["id"], "reason": reason})
            log.info("draft_rejected id=%s reason=%s", q["id"], reason)
            continue
        _append(entry)
        result.drafted.append(q["id"])

    log.info("drafting_done drafted=%d rejected=%d cost=$%.2f",
             len(result.drafted), len(result.rejected), result.cost_usd)
    return result.as_dict()


def _append(entry: dict) -> None:
    doc = json.loads(library.PATH.read_text(encoding="utf-8"))
    doc["answers"] = [a for a in doc["answers"] if a["id"] != entry["id"]] + [entry]
    doc["answers"].sort(key=lambda a: (a["risk"], a["id"]))
    doc["_meta"]["count"] = len(doc["answers"])
    library.PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    library._load.cache_clear()


def release(risk: str, reviewer: str) -> int:
    """Release spot-checked drafts of one risk tier.

    Only tiers listed in `bulk_releasable_risk` may go this way, and the
    reviewer's name goes on every one of them — releasing in bulk is still
    somebody saying "I read a sample of these and they are sound", which is a
    real claim a real person is making.
    """
    if risk not in bulk_releasable():
        raise SystemExit(
            f"'{risk}' answers are reviewed individually, not in bulk.\n"
            f"Bulk release is only for: {', '.join(sorted(bulk_releasable()))}"
        )
    n = 0
    for a in library.all_answers().values():
        if a.risk == risk and a.status == library.DRAFT:
            library.mark_reviewed(a.id, reviewer)
            n += 1
    return n


def print_plan() -> None:
    """`python -m app.drafting` — what it would do and what it would cost."""
    todo = candidates()
    c = would_cost(len(todo))
    have = library.all_answers()
    print(f"\n  DRAFTING — {len(have)} answers stored, {len(todo)} questions still unanswered\n")
    if not todo:
        print("  Nothing left to draft.\n")
        return
    import collections
    by = collections.Counter(q["module"] for q in todo)
    for mod, n in by.most_common(8):
        print(f"    {mod:<11} {n:>3}")
    if len(by) > 8:
        print(f"    ... and {len(by) - 8} more topics")
    print(f"\n  One-time cost to answer all {c['questions']}: ${c['one_time_usd']}")
    print(f"  They then serve at no model cost. Generating the same volume on")
    print(f"  demand at 100k questions a month runs ${c['monthly_saved_at_100k']}/month.\n")
    print("  Volatile questions are excluded — those keep going to the model,")
    print("  and paying for them every time is the right call.\n")
    print(f"  Run a batch:  python -m app.drafting run [n]   (default {batch_size()})")
    print( "  Then release: python -m app.drafting release standard \"<who checked them>\"\n")


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        import anthropic

        from .config import get_settings

        s = get_settings()
        n = int(sys.argv[2]) if len(sys.argv) > 2 else batch_size()
        out = asyncio.run(run(anthropic.AsyncAnthropic(api_key=s.anthropic_key), s.model, n))
        print(json.dumps(out, indent=2))
    elif len(sys.argv) >= 4 and sys.argv[1] == "release":
        print(f"  released {release(sys.argv[2], ' '.join(sys.argv[3:]))} answers")
    else:
        print_plan()
