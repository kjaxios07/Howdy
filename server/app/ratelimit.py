"""Rate limiting and IP hashing — the parts of request defence that need Redis."""

from __future__ import annotations

import hashlib
import hmac
import os
import time

import redis.asyncio as aioredis

from .config import get_settings

settings = get_settings()

_redis: aioredis.Redis | None = None


def redis_client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def check_rate_limit(key: str, limit: int) -> tuple[bool, int]:
    """Sliding-window limiter. Returns (allowed, retry_after_seconds).

    A sorted set of request timestamps, so a burst straddling a window boundary
    cannot double the effective limit the way a fixed-window counter does.
    """
    r = redis_client()
    now = time.time()
    window = settings.rate_limit_window_s
    redis_key = f"rl:{key}"
    member = f"{now:.6f}:{os.urandom(6).hex()}"  # unique even for simultaneous requests

    async with r.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(redis_key, 0, now - window)
        pipe.zadd(redis_key, {member: now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window + 1)
        _, _, count, _ = await pipe.execute()

    if count > limit:
        await r.zrem(redis_key, member)  # a blocked request must not hold a slot
        oldest = await r.zrange(redis_key, 0, 0, withscores=True)
        retry_after = int(window - (now - oldest[0][1])) + 1 if oldest else window
        return False, max(1, retry_after)
    return True, 0


def hash_ip(ip: str) -> bytes:
    """Never store a raw IP address — an HMAC is enough to spot abuse patterns."""
    return hmac.new(settings.pepper, ip.encode("utf-8"), hashlib.sha256).digest()


def client_ip(request) -> str:
    """Trust X-Forwarded-For only because Caddy is the sole ingress and sets it."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
