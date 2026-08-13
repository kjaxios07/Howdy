"""Opaque server-side sessions, backed by Redis.

Deliberately NOT a JWT in localStorage:
  * an opaque id is unreadable to XSS (the cookie is httpOnly)
  * revocation is a single DEL — "log out everywhere" and post-breach kill both work
  * lookup costs ~0.2 ms
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from fastapi import Request, Response

from .config import get_settings
from .ratelimit import redis_client

settings = get_settings()

_PREFIX = "sess:"
_TTL = settings.session_ttl_days * 24 * 3600


@dataclass(frozen=True)
class SessionData:
    user_id: str
    google_sub: str


def _key(sid: str) -> str:
    return f"{_PREFIX}{sid}"


async def create_session(response: Response, *, user_id: str, google_sub: str) -> str:
    """Always call this on login — a fresh id prevents session fixation."""
    sid = secrets.token_urlsafe(32)
    await redis_client().setex(
        _key(sid), _TTL, json.dumps({"user_id": user_id, "google_sub": google_sub})
    )
    response.set_cookie(
        key=settings.session_cookie,
        value=sid,
        max_age=_TTL,
        path="/",          # required by the __Host- prefix
        secure=True,       # required by the __Host- prefix
        httponly=True,
        samesite="lax",    # blocks cross-site CSRF on state-changing verbs
    )
    return sid


async def read_session(request: Request) -> SessionData | None:
    sid = request.cookies.get(settings.session_cookie)
    if not sid:
        return None
    raw = await redis_client().get(_key(sid))
    if not raw:
        return None
    # Sliding expiry: an active user is never logged out mid-conversation.
    await redis_client().expire(_key(sid), _TTL)
    data = json.loads(raw)
    return SessionData(user_id=data["user_id"], google_sub=data["google_sub"])


async def destroy_session(request: Request, response: Response) -> None:
    sid = request.cookies.get(settings.session_cookie)
    if sid:
        await redis_client().delete(_key(sid))
    response.delete_cookie(settings.session_cookie, path="/")


async def destroy_all_for_user(user_id: str) -> int:
    """Used by account deletion and 'sign out everywhere'."""
    r = redis_client()
    removed = 0
    async for key in r.scan_iter(match=f"{_PREFIX}*", count=500):
        raw = await r.get(key)
        if raw and json.loads(raw).get("user_id") == user_id:
            await r.delete(key)
            removed += 1
    return removed


# ── Short-lived OAuth state (PKCE verifier + nonce) ──────────────────────

async def stash_oauth_state(state: str, payload: dict, ttl: int = 300) -> None:
    await redis_client().setex(f"oauth:{state}", ttl, json.dumps(payload))


async def pop_oauth_state(state: str) -> dict | None:
    r = redis_client()
    key = f"oauth:{state}"
    raw = await r.get(key)
    if raw:
        await r.delete(key)  # single use — replaying a callback must fail
        return json.loads(raw)
    return None
