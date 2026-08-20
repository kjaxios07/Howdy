"""Serving a repeated question from the last good answer.

The scale model (`python -m app.scale 500000 --levers`) says this is the
single biggest lever we have: at 500,000 users it removes about two thirds
of the bill, more than model routing and search reduction combined. The
reason is simple — students overwhelmingly ask the same things. "How do I
apply for a TFN?" does not have 50,000 different answers, but today we buy
it 50,000 times.

What may be cached, and for how long, is decided by one signal we already
have: whether the answer needed a live search.

    answered from the library   stable  →  cached for days
    needed a live search        volatile →  cached for minutes, or not at all

That mapping is not a heuristic bolted on here. It is the same `volatile`
idea the nightly verify job already runs on: if a figure can move, we do not
serve it from memory.

Never cached, at any TTL:

  * anything in a risk-tiered topic (safety, rights) — a crisis answer must
    be generated fresh, in that student's words, every single time
  * anything the citation check rejected — never re-serve a bad answer
  * anything with a location in the key we did not capture — a concession
    answer for Queensland must never be served to someone in Victoria

Privacy: entries are keyed by a fingerprint of the question and hold no user,
session or IP. It is the same shape as the coverage-gap log — a list of
questions, never a record of who asked one. A test asserts it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .appconfig import raw
from .gaps import fingerprint

log = logging.getLogger(__name__)


def redis_client():
    """Lazy, so this module stays importable and testable without redis."""
    from .ratelimit import redis_client as _client

    return _client()


def _cfg() -> dict:
    return raw().get("answer_cache", {})


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def never_cache_modules() -> frozenset[str]:
    return frozenset(_cfg().get("never_cache_modules", ("safety", "rights")))


def ttl_for(*, searched: bool) -> int:
    """Seconds. A searched answer contains something that can move."""
    c = _cfg()
    return int(c.get("volatile_ttl_s", 900) if searched else c.get("stable_ttl_s", 172800))


@dataclass(frozen=True)
class Cached:
    reply: str
    sources: list
    verified: bool
    searched: bool


def key(question: str, module_id: str | None, state: str = "") -> str:
    """Cache key.

    The state is part of the key because a concession or a tenancy answer is
    only correct for one jurisdiction. Serving Queensland's answer to someone
    in Victoria would be worse than not caching at all.
    """
    return f"ac:{module_id or '-'}:{state or '-'}:{fingerprint(question)}"


def cacheable(
    *, module_id: str | None, verified: bool, searched: bool, reply: str
) -> tuple[bool, str]:
    """May this answer be stored? Returns (ok, reason_if_not)."""
    if not enabled():
        return False, "cache disabled"
    if module_id and module_id in never_cache_modules():
        return False, "risk-tiered topic — always answered fresh"
    if not verified:
        return False, "citation check rejected part of it"
    if not reply or len(reply) < 80:
        return False, "too short to be a real answer"
    if searched and ttl_for(searched=True) <= 0:
        return False, "volatile and volatile caching is off"
    return True, ""


async def get(question: str, module_id: str | None, state: str = "") -> Cached | None:
    """A previous answer to this question, or None. Never raises."""
    if not enabled():
        return None
    if module_id and module_id in never_cache_modules():
        return None
    try:
        blob = await redis_client().get(key(question, module_id, state))
        if not blob:
            return None
        d = json.loads(blob)
        return Cached(
            reply=d["reply"],
            sources=d.get("sources", []),
            verified=d.get("verified", True),
            searched=d.get("searched", False),
        )
    except Exception:  # noqa: BLE001 — a cache miss and a cache fault are the same thing
        log.warning("answer_cache_read_failed", exc_info=True)
        return None


async def put(
    question: str,
    module_id: str | None,
    *,
    reply: str,
    sources: list,
    verified: bool,
    searched: bool,
    state: str = "",
) -> bool:
    """Store an answer if it is allowed to be stored. Never raises."""
    ok, _ = cacheable(module_id=module_id, verified=verified, searched=searched, reply=reply)
    if not ok:
        return False
    try:
        await redis_client().setex(
            key(question, module_id, state),
            ttl_for(searched=searched),
            json.dumps(
                {"reply": reply, "sources": sources, "verified": verified, "searched": searched}
            ),
        )
        return True
    except Exception:  # noqa: BLE001 — never let caching break an answer
        log.warning("answer_cache_write_failed", exc_info=True)
        return False


async def stats() -> dict:
    """Hit rate, for the cost report. Counters are plain integers, no identity."""
    r = redis_client()
    try:
        hits = int(await r.get("ac:stat:hit") or 0)
        misses = int(await r.get("ac:stat:miss") or 0)
    except Exception:  # noqa: BLE001
        return {"hits": 0, "misses": 0, "hit_rate": 0.0}
    total = hits + misses
    return {"hits": hits, "misses": misses, "hit_rate": (hits / total) if total else 0.0}


async def note(hit: bool) -> None:
    """Count a hit or miss. Fire and forget."""
    try:
        await redis_client().incr("ac:stat:hit" if hit else "ac:stat:miss")
    except Exception:  # noqa: BLE001
        pass
