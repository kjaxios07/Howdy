"""Daily evolution — how Kip gets better while you sleep.

Two jobs, deliberately separated by risk, because "the knowledge base updates
itself" is a sentence that should make an engineer nervous when students are
making visa decisions on the output.

  VERIFY  (runs automatically, unsupervised)
      Re-checks facts we ALREADY hold against the source URL we already cite.
      This is checking, not inventing. If Fair Work raised the minimum wage,
      the number updates and the change is logged. Low risk, high value —
      stale figures are the most likely way Kip misleads someone.

  PROPOSE (runs automatically, but only STAGES — never publishes)
      Researches the top questions Kip answered badly and drafts knowledge-base
      entries for them. Drafts land in question_gaps.proposal for a human to
      approve with `python -m app.evolve approve <id>`.

Why the second one is gated: an auto-published wrong fact about work-hour
limits could cost a student their visa, and under Australian Consumer Law we
would own that. A human read of a few paragraphs a week is cheap insurance.
Run `python -m app.evolve report` to see what is waiting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import anthropic
from sqlalchemy import select

from . import websearch
from .config import get_settings
from .db import SessionLocal
from .gaps import coverage_stats, top_gaps
from .models import QuestionGap

log = logging.getLogger("kip.evolve")
settings = get_settings()

KB_PATH = Path(__file__).parent / "knowledge" / "base.json"
QUESTIONS_PATH = Path(__file__).parents[2] / "knowledge" / "questions.json"
CHANGELOG_PATH = Path(__file__).parent / "knowledge" / "changelog.jsonl"

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_key)


# ── 1. Verify: re-check the figures we already publish ───────────────────

VERIFY_PROMPT = """You are auditing a fact in an Australian government knowledge base.

Current stored value:
{stored}

Source of record: {source_url}

Search that official source and answer ONLY with JSON, no prose:
{{"changed": true|false,
  "current_value": "<the value as it appears on the source today>",
  "confidence": "high"|"low",
  "note": "<one sentence: what changed, or 'unchanged'>"}}

Rules:
- If you cannot reach or confirm the source, return changed=false, confidence="low".
- NEVER guess a figure. Low confidence is always better than a wrong number.
- Only report changed=true if you can see the new value on the official source."""


async def verify_facts(limit: int = 8) -> list[dict]:
    """Re-check volatile facts against their own cited source."""
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    checks: list[dict] = []

    # Walk the KB for sections carrying both a source_url and a figure.
    def walk(node, path):
        if isinstance(node, dict):
            url = node.get("source_url")
            if url and _has_figure(node):
                checks.append({"path": path, "url": url, "value": _figures(node)})
            for k, v in node.items():
                if k != "source_url":
                    walk(v, f"{path}.{k}" if path else k)

    walk(kb, "")
    checks = checks[:limit]
    findings = []

    for check in checks:
        try:
            response = await client.messages.create(
                model=settings.model,
                max_tokens=400,
                tools=[t] if (t := websearch.tool_definition()) else [],
                messages=[{
                    "role": "user",
                    "content": VERIFY_PROMPT.format(
                        stored=json.dumps(check["value"], ensure_ascii=False),
                        source_url=check["url"],
                    ),
                }],
            )
            text = "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            result = _extract_json(text)
            if not result:
                continue

            if result.get("changed") and result.get("confidence") == "high":
                findings.append({
                    "path": check["path"],
                    "source_url": check["url"],
                    "was": check["value"],
                    "now": result.get("current_value"),
                    "note": result.get("note", ""),
                })
                log.warning("kb_fact_changed path=%s note=%s", check["path"], result.get("note"))
        except Exception:
            log.exception("verify_failed path=%s", check["path"])

    return findings


def _has_figure(node: dict) -> bool:
    blob = json.dumps(node)
    return any(marker in blob for marker in ("$", "%", "per hour", "AUD", "hours per"))


def _figures(node: dict) -> dict:
    return {k: v for k, v in node.items() if isinstance(v, (str, int, float)) and k != "source_url"}


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


# ── 2. Propose: draft KB entries for the top gaps (staged, not published) ─

PROPOSE_PROMPT = """Students keep asking this and our knowledge base has no good answer:

    "{question}"

Research it using ONLY official Australian government sources. Then answer with
JSON only, no prose:

{{"answerable": true|false,
  "module": "arrive|visa|tax|work|housing|health|money|transport|study|safety",
  "summary": "<2-4 sentences of general information a student can act on>",
  "source_url": "<the single best official URL>",
  "volatile": true|false,
  "refer_to_expert": "<empty, or which registered professional this really needs>"}}

Rules:
- If this needs a registered migration agent, lawyer or financial adviser to
  answer properly for an individual, set answerable=false and say so in
  refer_to_expert. We give general information only, never individual advice.
- Never invent a URL. If you cannot find an official source, answerable=false.
- volatile=true if the answer contains a figure or date that will change."""


async def propose_answers(limit: int = 5) -> int:
    """Research the worst gaps and stage drafts for human review."""
    staged = 0

    async with SessionLocal() as db:
        gaps = await top_gaps(db, limit=limit)

        for gap in gaps:
            if gap.proposal:
                continue  # already waiting on review
            try:
                response = await client.messages.create(
                    model=settings.model,
                    max_tokens=700,
                    tools=[t] if (t := websearch.tool_definition()) else [],
                    messages=[{"role": "user", "content": PROPOSE_PROMPT.format(question=gap.question)}],
                )
                text = "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")
                draft = _extract_json(text)
                if not draft:
                    continue

                # Never stage a source we would not cite.
                from .sources import is_trusted
                from urllib.parse import urlparse

                url = draft.get("source_url") or ""
                host = (urlparse(url).hostname or "") if url else ""
                if draft.get("answerable") and not is_trusted(host):
                    log.warning("proposal_rejected_untrusted_source host=%s", host)
                    continue

                draft["drafted_at"] = datetime.now(timezone.utc).isoformat()
                gap.proposal = draft
                staged += 1
            except Exception:
                log.exception("propose_failed gap=%s", gap.id)

        await db.commit()

    return staged


# ── Orchestration ────────────────────────────────────────────────────────


async def run_daily() -> dict:
    started = datetime.now(timezone.utc)
    findings = await verify_facts()
    staged = await propose_answers()

    async with SessionLocal() as db:
        stats = await coverage_stats(db)

    entry = {
        "ran_at": started.isoformat(),
        "facts_changed": findings,
        "proposals_staged": staged,
        "coverage": stats,
    }

    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHANGELOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log.info("evolve_done changed=%d staged=%d open_gaps=%d",
             len(findings), staged, stats["open_gaps"])
    return entry


async def _report() -> None:
    async with SessionLocal() as db:
        stats = await coverage_stats(db)
        print("\nCoverage")
        for k, v in stats.items():
            print(f"  {k:22s} {v}")

        pending = list((await db.scalars(
            select(QuestionGap)
            .where(QuestionGap.proposal.is_not(None))
            .where(QuestionGap.resolved_at.is_(None))
            .order_by(QuestionGap.occurrences.desc())
        )).all())

        if not pending:
            print("\nNothing waiting for review.\n")
            return

        print(f"\n{len(pending)} proposal(s) awaiting review:\n")
        for gap in pending:
            p = gap.proposal or {}
            print(f"  [{gap.id}] asked {gap.occurrences}x — {gap.question}")
            if p.get("answerable"):
                print(f"       module : {p.get('module')}")
                print(f"       summary: {(p.get('summary') or '')[:160]}")
                print(f"       source : {p.get('source_url')}")
            else:
                print(f"       NOT ANSWERABLE — refer to: {p.get('refer_to_expert')}")
            print(f"       approve: python -m app.evolve approve {gap.id}\n")


async def _approve(gap_id: int) -> None:
    """Merge one reviewed proposal into the knowledge base."""
    async with SessionLocal() as db:
        gap = await db.scalar(select(QuestionGap).where(QuestionGap.id == gap_id))
        if not gap or not gap.proposal:
            print(f"No staged proposal with id {gap_id}."); return

        p = gap.proposal
        if not p.get("answerable"):
            gap.resolved_at = date.today()
            await db.commit()
            print(f"Marked {gap_id} resolved (referral-only, nothing to add to the KB).")
            return

        kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
        module = p.get("module", "arrive")
        kb.setdefault(module, {})
        key = f"learned_{gap.fingerprint[:8]}"
        kb[module][key] = {
            "name": gap.question,
            "source_url": p["source_url"],
            "summary": p["summary"],
            "volatile": bool(p.get("volatile")),
            "added": date.today().isoformat(),
            "origin": "evolve (human-approved)",
        }
        kb["_meta"]["last_updated"] = date.today().isoformat()

        KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        gap.resolved_at = date.today()
        gap.answered_well = True
        await db.commit()
        print(f"Merged into knowledge base under '{module}.{key}'. Restart the app to load it.")


async def _seed(limit: int = 20) -> None:
    """Research answers for seeded questions the knowledge base doesn't cover yet.

    Works through knowledge/questions.json in priority order — most-volatile and
    highest-difficulty first, since those are the ones Kip is most likely to get
    wrong from memory. Every result is STAGED for review, never auto-published.

        python -m app.evolve seed 20      # research the next 20
    """
    bank = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    kb_blob = KB_PATH.read_text(encoding="utf-8").lower()

    def covered(item) -> bool:
        # Crude but honest: does the KB already mention the distinctive words?
        words = [w for w in item["q"].lower().split() if len(w) > 6]
        return sum(w in kb_blob for w in words) >= max(2, len(words) // 2)

    todo = [q for q in bank if q["risk"] != "crisis" and not covered(q)]
    todo.sort(key=lambda q: (not q["volatile"], q["difficulty"] != "Hard"))
    todo = todo[:limit]

    print(f"{len(todo)} question(s) to research (of {len(bank)} in the bank)\n")
    staged = 0

    async with SessionLocal() as db:
        for item in todo:
            note = ""
            if item["risk"] == "refer":
                note = ("\nIMPORTANT: this question can only be answered as GENERAL information. "
                        "Do not assess any individual's eligibility. Name the registered "
                        "professional they should see.")
            try:
                response = await client.messages.create(
                    model=settings.model,
                    max_tokens=700,
                    tools=[t] if (t := websearch.tool_definition()) else [],
                    messages=[{"role": "user",
                               "content": PROPOSE_PROMPT.format(question=item["q"]) + note}],
                )
                text = "\n".join(b.text for b in response.content
                                  if getattr(b, "type", "") == "text")
                draft = _extract_json(text)
                if not draft:
                    print(f"  ✗ {item['id']}  no usable draft"); continue

                from urllib.parse import urlparse
                from .sources import is_trusted

                host = (urlparse(draft.get("source_url") or "").hostname or "")
                if draft.get("answerable") and not is_trusted(host):
                    print(f"  ✗ {item['id']}  rejected: untrusted source {host}"); continue

                draft["drafted_at"] = datetime.now(timezone.utc).isoformat()
                draft["seeded_from"] = item["id"]
                fp = __import__("app.gaps", fromlist=["fingerprint"]).fingerprint(item["q"])

                row = await db.scalar(select(QuestionGap).where(QuestionGap.fingerprint == fp))
                if row is None:
                    row = QuestionGap(
                        fingerprint=fp, question=item["q"][:300], module_id=item["module"],
                        occurrences=0, answered_well=False, needed_search=bool(item["volatile"]),
                        first_seen=date.today(), last_seen=date.today(),
                    )
                    db.add(row)
                row.proposal = draft
                staged += 1
                mark = "→" if draft.get("answerable") else "⚑ referral only"
                print(f"  ✓ {item['id']}  {mark}  {item['q'][:64]}")
            except Exception as exc:
                print(f"  ✗ {item['id']}  {type(exc).__name__}")
                log.exception("seed_failed id=%s", item["id"])

        await db.commit()

    print(f"\n{staged} staged for review.  python -m app.evolve report")


def main() -> None:
    logging.basicConfig(level="INFO")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "run":
        print(json.dumps(asyncio.run(run_daily()), indent=2))
    elif cmd == "report":
        asyncio.run(_report())
    elif cmd == "seed":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        asyncio.run(_seed(n))
    elif cmd == "approve" and len(sys.argv) > 2:
        asyncio.run(_approve(int(sys.argv[2])))
    else:
        print("usage: python -m app.evolve [run|report|seed <n>|approve <id>]")


if __name__ == "__main__":
    main()
