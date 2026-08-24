"""Keeping stored answers honest, or taking them down.

A pre-written answer is only worth having while it is still true. Served
instantly, with a citation under it and no hedging, an outdated one is more
damaging than having no stored answer at all — the student has nothing to
doubt. Speed and confidence are exactly what make staleness expensive here.

So every stored answer is re-examined on a cycle, and **an answer that cannot
be stood up stops being served.** It drops to `stale` and that question falls
back to the model: slower, and it costs us money, but it is current. Paying a
fraction of a cent is the correct outcome when the alternative is telling
someone something that stopped being true in April.

Two passes, because they cost very different amounts:

**The free pass runs over everything, every night.** No model, no network —
just checks that hold regardless: do the cited sources still pass the
allowlist, does the question still exist in the bank at the same risk tier,
is the answer still non-empty. These catch the failure that actually happens
in practice, which is not a fact changing but somebody editing a file.

**The paid pass audits a handful a night.** It re-reads the answer's own cited
source and asks whether the source still supports it. At a dozen a night the
whole set comes round about monthly for roughly the price of a coffee a year.
Overdue and risk-tiered answers go first.

The asymmetry is the point: **a machine may take an answer down, only a
person may put one back up.** Withdrawing on a doubt is cheap and safe.
Restoring is a judgement about whether something is true, and that needs a
name against it — `python -m app.library review <id> "<who>"`.

One deliberate exception. A crisis answer that is merely *overdue* keeps
serving. Leaving someone in distress with nothing because a date passed is
worse than showing them a two-month-old phone number, and those numbers do
not change. Only a substantive failure withdraws a crisis answer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import library
from .appconfig import raw
from .sources import _host_of, is_trusted

log = logging.getLogger(__name__)

AUDIT_PROMPT = """You are auditing a stored answer in an Australian student help service.

The answer below is served to students without a model call, so it must still
be accurate. Search the cited source and check whether it still supports what
the answer says.

STORED ANSWER:
{answer}

CITED SOURCE: {source}

Reply ONLY with JSON, no prose:
{{"supported": true|false,
  "confidence": "high"|"low",
  "problem": "<one sentence naming what no longer matches, or 'none'>"}}

Rules:
- supported=false ONLY if you can see on the source that something in the
  answer is now wrong. A source you could not reach is not a contradiction.
- If you cannot reach or read the source, return supported=true with
  confidence="low". Withdrawing a good answer because a site was down would
  make this job worse than useless.
- Ignore differences of wording, tone or emphasis. Only facts count."""


def _cfg() -> dict:
    return raw().get("answer_review", {})


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def interval_days(risk: str) -> int:
    return int(_cfg().get("check_interval_days", {}).get(risk, 120))


def audit_per_night() -> int:
    return int(_cfg().get("audit_per_night", 12))


def withdraw_on_failure() -> bool:
    return bool(_cfg().get("withdraw_on_failure", True))


@dataclass
class Result:
    checked: int = 0
    withdrawn: list = field(default_factory=list)
    audited: int = 0
    failures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "audited": self.audited,
            "withdrawn": self.withdrawn,
            "failures": self.failures,
        }


# ── The free pass ────────────────────────────────────────────────────────


def structural_problems(a: library.Answer, questions: dict) -> list[str]:
    """Everything checkable without a model or a network call.

    In practice this is the pass that earns its keep. Facts change slowly;
    files get edited every week, and an answer whose question was retired or
    whose source dropped off the allowlist is broken now, not in April.
    """
    problems = []

    if not a.answer or len(a.answer) < 200:
        problems.append("answer text is missing or truncated")

    if not a.sources:
        problems.append("cites nothing")
    for u in a.sources:
        if not is_trusted(_host_of(u)):
            problems.append(f"source {_host_of(u)} is no longer on the allowlist")

    q = questions.get(a.id)
    if q is None:
        problems.append("the question it answers is no longer in the bank")
    else:
        if q["risk"] != a.risk:
            problems.append(f"risk tier moved to {q['risk']}, answer written as {a.risk}")
        if q["volatile"]:
            problems.append("the question is now flagged volatile and must not be pre-written")

    return problems


def due_for_audit(a: library.Answer, today: date | None = None) -> bool:
    today = today or date.today()
    if not a.checked_on:
        return True
    try:
        last = date.fromisoformat(a.checked_on)
    except ValueError:
        return True
    return last + timedelta(days=interval_days(a.risk)) <= today


def _audit_order(answers: list) -> list:
    """Never checked first, then longest since a check, then risk tier."""
    rank = {"crisis": 0, "refer": 1}

    def key(a):
        return (a.checked_on or "", rank.get(a.risk, 2))

    return sorted(answers, key=key)


async def run(client=None, model: str | None = None) -> dict:
    """One night's work. Never raises — a broken recheck must not take the
    product down, and the worst case is that answers keep serving unchecked."""
    result = Result()
    if not enabled():
        return result.as_dict()

    try:
        from pathlib import Path

        qpath = Path(library.PATH).parent / "questions.json"
        questions = {q["id"]: q for q in json.loads(qpath.read_text(encoding="utf-8"))["questions"]}
    except Exception:  # noqa: BLE001
        log.warning("recheck_questions_unreadable", exc_info=True)
        return result.as_dict()

    served = [a for a in library.all_answers().values() if a.status == library.REVIEWED]

    # Pass one: free, over everything.
    for a in served:
        result.checked += 1
        problems = structural_problems(a, questions)
        if problems and withdraw_on_failure():
            reason = "; ".join(problems)
            if library.withdraw(a.id, reason):
                result.withdrawn.append({"id": a.id, "reason": reason, "pass": "structural"})

    # An overdue answer is not wrong, it is unexamined. It keeps serving and
    # goes to the front of the audit queue — except that we say so out loud,
    # because "nobody has looked at this in four months" is worth surfacing
    # even when nothing is broken.
    overdue = [a.id for a in served if a.overdue]
    if overdue:
        result.failures.append({"overdue_but_still_serving": overdue})

    # Pass two: costs a search each, so only a handful.
    if client is None:
        return result.as_dict()

    still_served = [a for a in library.all_answers().values() if a.status == library.REVIEWED]
    queue = [a for a in _audit_order(still_served) if due_for_audit(a)][: audit_per_night()]

    for a in queue:
        verdict = await _audit_one(client, model, a)
        result.audited += 1
        if verdict is None:
            continue
        if verdict.get("supported") is False and verdict.get("confidence") == "high":
            reason = f"source no longer supports it: {verdict.get('problem', 'unspecified')}"
            if withdraw_on_failure() and library.withdraw(a.id, reason):
                result.withdrawn.append({"id": a.id, "reason": reason, "pass": "audit"})
        else:
            library.mark_checked(a.id)

    log.info("recheck_done checked=%d audited=%d withdrawn=%d",
             result.checked, result.audited, len(result.withdrawn))
    return result.as_dict()


async def _audit_one(client, model, a: library.Answer) -> dict | None:
    """Ask the model whether the cited source still stands the answer up.

    A None return means we learned nothing — a failure here leaves the answer
    exactly as it was, which is the safe direction. The one thing this must
    never do is withdraw an answer because a website was slow.
    """
    from . import websearch

    try:
        kwargs = {
            "model": model or "claude-sonnet-5",
            "max_tokens": 400,
            "messages": [{
                "role": "user",
                "content": AUDIT_PROMPT.format(answer=a.answer[:2500], source=a.sources[0]),
            }],
        }
        if (tool := websearch.tool_definition()) is not None:
            kwargs["tools"] = [tool]
        response = await client.messages.create(**kwargs)
        text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        return json.loads(text[start : end + 1])
    except Exception:  # noqa: BLE001
        log.warning("recheck_audit_failed id=%s", a.id, exc_info=True)
        return None


def print_status() -> None:
    """`python -m app.recheck` — what is due, without checking anything."""
    answers = library.all_answers()
    served = [a for a in answers.values() if a.status == library.REVIEWED]
    stale = [a for a in answers.values() if a.status == library.STALE]
    due = [a for a in served if due_for_audit(a)]

    print(f"\n  ANSWER RECHECK — {len(served)} being served, {len(stale)} withdrawn\n")
    for risk in sorted({a.risk for a in answers.values()}):
        n = [a for a in served if a.risk == risk]
        d = [a for a in due if a.risk == risk]
        print(f"  {risk:<8} {len(n):>3} served   {len(d):>3} due a look   "
              f"(every {interval_days(risk)} days)")
    if stale:
        print("\n  WITHDRAWN — these questions are going to the model instead:")
        for a in stale:
            print(f"    {a.id:<14} {a.stale_reason}")
    if due:
        print(f"\n  {len(due)} due. At {audit_per_night()} a night that is "
              f"{-(-len(due) // max(1, audit_per_night()))} night(s) to clear.")
    print()


if __name__ == "__main__":  # pragma: no cover
    print_status()
