"""Free-tier allowances.

Three counters per person, all sliding 24-hour windows:

    per_topic   stops one topic being farmed (someone scraping every discount)
                without punishing a student who genuinely has a housing problem
                AND a visa problem in the same week
    per_day     the overall ceiling
    searches    the one that actually controls spend — a live search costs
                2.04c against 0.43c for a library answer, so capping searches
                is worth roughly five times capping questions

Two design decisions worth defending:

**Safety is never rationed.** Modules listed in `exempt_modules` are not
counted and cannot be blocked, at any tier, including signed out. A student
asking about family violence, an underpaying employer or a mental health
crisis must never meet a counter. If that means an abuser gets free answers
about tenancy law, that is a trade worth making every time.

**Counters live in Redis with a TTL, never in Postgres.** A per-topic table
keyed to a user would be a durable record of which topics that person asks
about — precisely the profile the rest of this system refuses to build. In
Redis it evaporates with the window, and guests are counted by hashed IP so
signing out still writes nothing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .appconfig import raw


def redis_client():
    """Resolved lazily, on purpose.

    Importing `ratelimit` at module load pulls in the redis package, which
    would make this module untestable without a Redis install — the same trap
    that already caught security.py and two helpers in chat.py. The quota
    arithmetic is ours and should be checkable on its own.
    """
    from .ratelimit import redis_client as _client

    return _client()



def _cfg() -> dict:
    return raw().get("quotas", {})


def window_seconds() -> int:
    return int(_cfg().get("window_hours", 24)) * 3600


def exempt_modules() -> frozenset[str]:
    return frozenset(_cfg().get("exempt_modules", ()))


def tiers() -> dict:
    return _cfg().get("tiers", {})


def tier_for(*, signed_in: bool, subscribed: bool) -> str:
    if subscribed:
        return "deals"
    return "free" if signed_in else "guest"


def allowance(tier: str) -> dict:
    t = tiers()
    return t.get(tier) or t.get("guest", {})


@dataclass(frozen=True)
class Decision:
    """The outcome of a quota check."""

    allowed: bool
    counter: str = ""          # which of the three ran out
    remaining: int = 0         # of the tightest relevant counter
    retry_after: int = 0       # seconds
    exempt: bool = False       # safety topic — never counted

    @property
    def retry_hours(self) -> float:
        return round(self.retry_after / 3600, 1)


def _human_wait(seconds: int) -> str:
    if seconds < 3600:
        return f"{max(1, seconds // 60)} minutes"
    hours = round(seconds / 3600)
    return "an hour" if hours <= 1 else f"{hours} hours"


def message(decision: Decision, tier: str) -> str:
    """What the student reads. Warm, specific, and never a dead end.

    A quota wall is the worst moment in a free product, so it says what
    happened, when it lifts, and what they can do right now.
    """
    wait = _human_wait(decision.retry_after)
    if tier == "guest":
        return (
            f"You've used your questions for now — they come back in {wait}. "
            "Signing in with Google gives you a lot more, keeps your answers, "
            "and costs nothing.\n\n"
            "If this is urgent or about your safety, ask anyway — those are never limited."
        )
    if decision.counter == "per_topic":
        return (
            f"You've asked a lot about this topic today, which is completely fine — "
            f"more on it opens up in {wait}. Other topics still work right now.\n\n"
            "If it's urgent or about your safety, ask anyway — those are never limited."
        )
    if decision.counter == "searches":
        return (
            f"I've done a lot of live checking for you today. That resets in {wait}.\n\n"
            "I can still answer from what I already have — ask away, and anything "
            "about your safety is never limited."
        )
    return (
        f"You've reached today's questions — they come back in {wait}.\n\n"
        "Anything about your safety is never limited, so ask if you need to."
    )


async def _hit(key: str, limit: int, window: int, *, consume: bool) -> tuple[bool, int, int]:
    """One sliding-window counter. Returns (allowed, remaining, retry_after).

    Same shape as the per-minute limiter: a sorted set of timestamps, so a
    burst straddling a boundary cannot double the effective allowance.
    """
    if limit <= 0:
        return True, 0, 0                      # unset means unlimited, not zero

    r = redis_client()
    now = time.time()
    member = f"{now:.6f}:{os.urandom(6).hex()}"

    async with r.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, now - window)
        if consume:
            pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window + 60)
        results = await pipe.execute()

    count = results[-2]
    # Consuming, `count` already includes this request, so > limit is over.
    # Peeking, it does not — the question is whether adding one WOULD exceed,
    # so the comparison must be >=. Getting this wrong let one extra request
    # through every time, because peek said yes at exactly the limit.
    if (count > limit) if consume else (count >= limit):
        if consume:
            await r.zrem(key, member)          # a blocked request must not hold a slot
        oldest = await r.zrange(key, 0, 0, withscores=True)
        retry = int(window - (now - oldest[0][1])) + 1 if oldest else window
        return False, 0, max(1, retry)

    return True, max(0, limit - count), 0


async def check(
    subject: str,
    module_id: str | None,
    tier: str,
    *,
    will_search: bool = False,
    consume: bool = True,
) -> Decision:
    """Can this person ask this question?

    `subject` is an opaque identity: a user id when signed in, a hashed IP
    when not. Nothing here needs to know which.
    """
    if module_id and module_id in exempt_modules():
        return Decision(allowed=True, exempt=True)

    window = window_seconds()
    limits = allowance(tier)

    checks: list[tuple[str, str, int]] = []
    if module_id:
        checks.append(("per_topic", f"q:{tier}:{subject}:m:{module_id}", int(limits.get("per_topic", 0))))
    checks.append(("per_day", f"q:{tier}:{subject}:all", int(limits.get("per_day", 0))))
    if will_search:
        checks.append(("searches", f"q:{tier}:{subject}:search", int(limits.get("searches", 0))))

    # Two phases, on purpose. Consuming as we go meant a question blocked on
    # the search counter had already spent a topic slot and a daily slot — you
    # were charged for a question you were not allowed to ask. Peek at all
    # three first; only spend when every one of them passes.
    for name, key, limit in checks:
        ok, _, retry = await _hit(key, limit, window, consume=False)
        if not ok:
            return Decision(allowed=False, counter=name, retry_after=retry)

    if not consume:
        remaining = []
        for _, key, limit in checks:
            _, left, _ = await _hit(key, limit, window, consume=False)
            if limit > 0:
                remaining.append(left)
        return Decision(allowed=True, remaining=min(remaining) if remaining else 0)

    remaining = []
    for _, key, limit in checks:
        _, left, _ = await _hit(key, limit, window, consume=True)
        if limit > 0:
            remaining.append(left)

    return Decision(allowed=True, remaining=min(remaining) if remaining else 0)


async def status(subject: str, tier: str) -> dict:
    """What is left, without spending anything. For the UI's quota chip."""
    window = window_seconds()
    limits = allowance(tier)
    out = {"tier": tier, "label": limits.get("label", tier), "window_hours": window // 3600}
    for name, suffix in (("per_day", "all"), ("searches", "search")):
        limit = int(limits.get(name, 0))
        _, left, _ = await _hit(f"q:{tier}:{subject}:{suffix}", limit, window, consume=False)
        out[name] = {"limit": limit, "remaining": left}
    out["never_limited"] = sorted(exempt_modules())
    return out
