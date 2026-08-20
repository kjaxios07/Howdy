"""A spend ceiling you cannot accidentally exceed.

Pre-revenue, the thing that actually matters is not cost per answer — it is
that a good week cannot produce a bill you did not agree to. Being written
about on a student forum should be good news, not an invoice.

So there is a hard monthly cap and a daily cap, and when spend approaches
them the product **degrades in stages rather than switching off**:

    normal      everything works
    no_search   live checking is off; the library still answers, at about a
                fifth of the cost. Most students never notice.
    cache_only  only answers we already have. New questions get an honest
                "back tomorrow" instead of a bill.
    paused      the cap is reached. Nothing is generated.

Two rules hold at every stage:

**Safety is never degraded.** The exempt topics — the ones a student in
trouble asks — always get a full, fresh, live answer, even past the cap.
The cap is protection against a surprise bill, not against helping someone
in danger. If that means overshooting the ceiling slightly, we overshoot.

**Paying users degrade after free ones.** They gave you money; they are the
last thing to be turned down, not the first.

Spend is tracked in Redis counters incremented as answers are metered, so
the check is one integer read rather than a database query per request. The
durable record stays in `answer_costs`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from .appconfig import raw

log = logging.getLogger(__name__)

NORMAL, NO_SEARCH, CACHE_ONLY, PAUSED = "normal", "no_search", "cache_only", "paused"


def redis_client():
    """Lazy, so this module stays importable and testable without redis."""
    from .ratelimit import redis_client as _client

    return _client()


def _cfg() -> dict:
    return raw().get("budget", {})


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def monthly_cap() -> float:
    return float(_cfg().get("monthly_cap_usd", 0) or 0)


def daily_cap() -> float:
    return float(_cfg().get("daily_cap_usd", 0) or 0)


def thresholds() -> dict:
    t = _cfg().get("thresholds", {})
    return {
        NO_SEARCH: float(t.get("no_search", 0.60)),
        CACHE_ONLY: float(t.get("cache_only", 0.85)),
        PAUSED: float(t.get("pause", 1.00)),
    }


def _keys() -> tuple[str, str]:
    today = date.today()
    return f"spend:d:{today.isoformat()}", f"spend:m:{today:%Y-%m}"


@dataclass(frozen=True)
class Budget:
    mode: str
    spent_today: float
    spent_month: float
    daily_cap: float
    monthly_cap: float

    @property
    def used(self) -> float:
        """Fraction of the tighter of the two caps."""
        parts = []
        if self.daily_cap:
            parts.append(self.spent_today / self.daily_cap)
        if self.monthly_cap:
            parts.append(self.spent_month / self.monthly_cap)
        return max(parts) if parts else 0.0

    @property
    def remaining_month(self) -> float:
        return max(0.0, self.monthly_cap - self.spent_month)


async def add(micro_usd: int) -> None:
    """Record spend. Called once per metered answer. Never raises."""
    if not enabled() or micro_usd <= 0:
        return
    try:
        day, month = _keys()
        r = redis_client()
        async with r.pipeline(transaction=True) as pipe:
            pipe.incrby(day, micro_usd)
            pipe.expire(day, 60 * 60 * 48)
            pipe.incrby(month, micro_usd)
            pipe.expire(month, 60 * 60 * 24 * 62)
            await pipe.execute()
    except Exception:  # noqa: BLE001 — metering must never break an answer
        log.warning("budget_add_failed", exc_info=True)


async def state() -> Budget:
    """Where we are against the caps. A read failure reports NORMAL.

    Failing open is deliberate: a Redis blip must not take the product down.
    The cap is a cost guard, not a safety control, and the durable
    `answer_costs` rows are still there to reconcile against.
    """
    m_cap, d_cap = monthly_cap(), daily_cap()
    if not enabled() or (not m_cap and not d_cap):
        return Budget(NORMAL, 0.0, 0.0, d_cap, m_cap)

    try:
        day, month = _keys()
        r = redis_client()
        d_raw, m_raw = await r.mget(day, month)
        spent_today = int(d_raw or 0) / 1_000_000
        spent_month = int(m_raw or 0) / 1_000_000
    except Exception:  # noqa: BLE001
        log.warning("budget_read_failed", exc_info=True)
        return Budget(NORMAL, 0.0, 0.0, d_cap, m_cap)

    b = Budget(NORMAL, spent_today, spent_month, d_cap, m_cap)
    t = thresholds()
    used = b.used
    if used >= t[PAUSED]:
        mode = PAUSED
    elif used >= t[CACHE_ONLY]:
        mode = CACHE_ONLY
    elif used >= t[NO_SEARCH]:
        mode = NO_SEARCH
    else:
        mode = NORMAL
    return Budget(mode, spent_today, spent_month, d_cap, m_cap)


def effective_mode(budget: Budget, *, tier: str, exempt: bool) -> str:
    """What this particular request gets.

    Safety questions are never degraded — full, fresh, live, past the cap if
    it comes to that. Paying users degrade one stage later than free ones,
    because they paid.
    """
    if exempt:
        return NORMAL
    if budget.mode == NORMAL:
        return NORMAL
    if tier == "deals":
        ladder = [NORMAL, NORMAL, NO_SEARCH, CACHE_ONLY]
        order = [NORMAL, NO_SEARCH, CACHE_ONLY, PAUSED]
        return ladder[order.index(budget.mode)]
    return budget.mode


def message(mode: str) -> str:
    """What a student reads when the product is running lean. Never mentions
    money — that is our problem, not theirs."""
    if mode == CACHE_ONLY:
        return (
            "I'm running light today, so I can only answer things I've already "
            "looked up. Try again tomorrow for anything new.\n\n"
            "Anything urgent or about your safety still works normally."
        )
    if mode == PAUSED:
        return (
            "I'm at capacity for today — back tomorrow.\n\n"
            "Anything urgent or about your safety still works normally. "
            "For emergencies call 000, and Lifeline is 13 11 14."
        )
    return ""


async def status() -> dict:
    """For the ops report and the health endpoint."""
    b = await state()
    return {
        "mode": b.mode,
        "spent_today_usd": round(b.spent_today, 4),
        "spent_month_usd": round(b.spent_month, 4),
        "daily_cap_usd": b.daily_cap,
        "monthly_cap_usd": b.monthly_cap,
        "used_fraction": round(b.used, 4),
        "remaining_month_usd": round(b.remaining_month, 2),
    }
