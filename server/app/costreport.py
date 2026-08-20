"""Recording and reporting what answers actually cost.

Split from `costs.py` on purpose: that module is pure arithmetic and stays
testable with no database. This one is the part that touches storage.

Nothing here is ever allowed to break an answer. Metering is a nice-to-have;
a student getting their question answered is not. Every write is wrapped so
a failure is logged and swallowed.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select

from .costs import PRICES_VERIFIED, Usage, price
from .models import AnswerCost

log = logging.getLogger(__name__)


def combine(usages: list[Usage]) -> Usage:
    """Add up the usages of a multi-request turn.

    A search turn can stop with `pause_turn` and be resumed, which means one
    answer can be several API calls. Charging for only the last one would
    under-report exactly the answers that cost the most.
    """
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        cache_creation_input_tokens=sum(u.cache_creation_input_tokens for u in usages),
        cache_read_input_tokens=sum(u.cache_read_input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        web_searches=sum(u.web_searches for u in usages),
    )


async def record(db, model: str, usage: Usage, module_id: str | None = None) -> None:
    """Meter one answer. Never raises."""
    if db is None:
        return
    try:
        cost = price(model, usage)
        micro = round(cost.total * 1_000_000)

        # Same number, two places: Redis for the fast ceiling check on the next
        # request, Postgres for the durable record. The counter is the one the
        # budget guard reads, so it is updated before the row is committed.
        from . import budget

        await budget.add(micro)

        db.add(
            AnswerCost(
                day=date.today(),
                model=model,
                module_id=module_id,
                input_tokens=usage.input_tokens,
                cache_write_tokens=usage.cache_creation_input_tokens,
                cache_read_tokens=usage.cache_read_input_tokens,
                output_tokens=usage.output_tokens,
                searches=usage.web_searches,
                micro_usd=micro,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — metering must never break an answer
        log.warning("cost_record_failed", exc_info=True)


# ── Reporting ────────────────────────────────────────────────────────────

async def summary(db, days: int = 30) -> dict:
    """Aggregate the meter. Percentiles are computed in Python because the
    row counts here are small and it keeps the query portable."""
    since = date.today() - timedelta(days=days)
    rows = (
        await db.execute(
            select(AnswerCost.micro_usd, AnswerCost.searches, AnswerCost.module_id)
            .where(AnswerCost.day >= since)
        )
    ).all()
    if not rows:
        return {"answers": 0, "days": days}

    micros = sorted(r[0] for r in rows)
    n = len(micros)

    def pct(p: float) -> float:
        return micros[min(n - 1, int(n * p))] / 1_000_000

    searched = [r for r in rows if r[1] > 0]
    total_usd = sum(micros) / 1_000_000

    by_module: dict[str, list[int]] = {}
    for micro, _, module in rows:
        by_module.setdefault(module or "—", []).append(micro)

    return {
        "answers": n,
        "days": days,
        "total_usd": total_usd,
        "mean_usd": total_usd / n,
        "p50_usd": pct(0.50),
        "p95_usd": pct(0.95),
        "max_usd": micros[-1] / 1_000_000,
        "searched_share": len(searched) / n,
        "searches": sum(r[1] for r in rows),
        "by_module": {
            k: {"answers": len(v), "mean_usd": sum(v) / len(v) / 1_000_000}
            for k, v in sorted(by_module.items(), key=lambda kv: -sum(kv[1]))
        },
    }


def print_report(days: int = 30) -> None:
    """CLI entry: `python -m app.costs report`."""
    import asyncio

    from .db import session_scope

    async def run() -> None:
        async with session_scope() as db:
            s = await summary(db, days)
            if not s["answers"]:
                print(
                    f"\n  No answers metered in the last {days} days.\n"
                    "  Once the app has served traffic this shows measured cost.\n"
                    "  Until then: python -m app.costs estimate\n"
                )
                return
            print(f"\n  MEASURED — last {s['days']} days, {s['answers']:,} answers\n")
            print(f"  spend                 ${s['total_usd']:>9.2f}")
            print(f"  mean per answer        {s['mean_usd'] * 100:>9.3f}c")
            print(f"  median (p50)           {s['p50_usd'] * 100:>9.3f}c")
            print(f"  p95                    {s['p95_usd'] * 100:>9.3f}c   <- size the plan on this")
            print(f"  worst                  {s['max_usd'] * 100:>9.3f}c")
            print(f"  answers that searched  {s['searched_share'] * 100:>9.1f}%  ({s['searches']:,} searches)")
            print("\n  BY TOPIC")
            for mod, m in list(s["by_module"].items())[:10]:
                print(f"  {mod:<16} {m['answers']:>6,} answers   {m['mean_usd'] * 100:>7.3f}c avg")
            print(f"\n  A $5/month plan covers {5.0 / s['mean_usd']:,.0f} answers at today's mean.")
            print(f"  Prices verified {PRICES_VERIFIED}.\n")

    asyncio.run(run())
