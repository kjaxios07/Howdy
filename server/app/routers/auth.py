"""Google sign-in — Authorization Code flow with PKCE.

Four details that are commonly botched, and are handled here:
  1. Users are keyed on Google's `sub`, never on email. Emails change hands
     (especially in Workspace domains); `sub` is stable and immutable.
  2. The ID token is fully verified — signature against Google's JWKS, plus
     iss / aud / exp / nonce. Authlib does all five; we never decode by hand.
  3. The session id is regenerated on login (session fixation).
  4. Google's access and refresh tokens are discarded. We only need identity at
     the moment of login, so storing them would add blast radius for no benefit.
"""

from __future__ import annotations

import secrets
import uuid

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import lookup_hash, new_dek, seal, wrap_dek
from ..db import audit, get_db
from ..deps import CurrentUser, optional_user
from ..models import User
from ..ratelimit import client_ip, hash_ip
from ..sessions import (
    create_session,
    destroy_session,
    pop_oauth_state,
    stash_oauth_state,
)

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url=settings.google_discovery_url,
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


@router.get("/google")
async def google_login(request: Request):
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)

    await stash_oauth_state(state, {"nonce": nonce, "verifier": verifier}, ttl=300)

    redirect_uri = f"{settings.base_url}/api/auth/callback"
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        state=state,
        nonce=nonce,
        code_verifier=verifier,
    )


@router.get("/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    state = request.query_params.get("state", "")
    stashed = await pop_oauth_state(state)
    if not stashed:
        # Unknown, expired or already-used state — treat as hostile.
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in attempt.")

    try:
        token = await oauth.google.authorize_access_token(
            request, code_verifier=stashed["verifier"]
        )
        claims = await oauth.google.parse_id_token(token, nonce=stashed["nonce"])
    except OAuthError:
        raise HTTPException(status_code=400, detail="Sign-in failed. Please try again.")

    google_sub: str = claims["sub"]
    email: str = (claims.get("email") or "").strip().lower()
    if not claims.get("email_verified", False):
        raise HTTPException(
            status_code=400,
            detail="Your Google email isn't verified. Verify it with Google and try again.",
        )

    user = await db.scalar(select(User).where(User.google_sub == google_sub))
    is_new = user is None

    if is_new:
        user_id = uuid.uuid4()
        dek = new_dek()
        wrapped = wrap_dek(settings.kek, dek, str(user_id))
        email_sealed = seal(dek, email, aad=f"email:{user_id}")

        user = User(
            id=user_id,
            google_sub=google_sub,
            email_hash=lookup_hash(settings.pepper, email),
            email_ct=email_sealed.ct,
            email_nonce=email_sealed.nonce,
            display_name=(claims.get("name") or "")[:255] or None,
            dek_ct=wrapped.ct,
            dek_nonce=wrapped.nonce,
            kek_version=1,
            retention_days=settings.default_retention_days,
            consent_version="2026-08-01",
        )
        db.add(user)
        await db.flush()

    await audit(
        db,
        action="auth.login" + (".new" if is_new else ""),
        user_id=user.id,
        ip_hash=hash_ip(client_ip(request)),
    )
    await db.commit()

    response = RedirectResponse(url="/chat", status_code=302)
    # New session id on every login — never reuse a pre-login id.
    await create_session(response, user_id=str(user.id), google_sub=google_sub)
    return response


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db),
                 current: CurrentUser | None = Depends(optional_user)):
    response = RedirectResponse(url="/", status_code=302)
    if current:
        await audit(db, action="auth.logout", user_id=current.id)
        await db.commit()
    await destroy_session(request, response)
    return response
