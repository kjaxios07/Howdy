"""The chat endpoint — the only route that calls the model.

Pipeline (everything except the model call is deterministic):
    validate -> rate limit -> PII guard -> injection guard
             -> Claude (prompt-cached) -> source verification -> persist -> respond

Storage modes:
    guest      — not signed in.        Nothing is written. Ever.
    incognito  — signed in, opted out. Nothing is written.
    saved      — signed in, default.   Encrypted with the user's own data key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import seal
from ..db import get_db
from ..deps import CurrentUser, optional_user
from ..models import Conversation, Message
from ..modules import MODULE_IDS
from ..prompt import system_prompt
from ..ratelimit import check_rate_limit, client_ip
from ..security import (
    INJECTION_RESPONSE,
    PII_RESPONSE,
    detect_injection,
    detect_pii,
    sanitize_message,
)
from ..sources import verify_reply

settings = get_settings()
router = APIRouter(prefix="/api", tags=["chat"])

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_key)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    module_id: str | None = Field(default=None, max_length=32)
    incognito: bool = False


class SourceOut(BaseModel):
    domain: str
    url: str


class ChatResponse(BaseModel):
    reply: str
    sources: list[SourceOut]
    verified: bool
    conversation_id: uuid.UUID | None = None
    stored: bool


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser | None = Depends(optional_user),
) -> ChatResponse:
    # ── Rate limit: signed-in users get a higher ceiling ─────────────────
    if current:
        rl_key, rl_limit = f"user:{current.id}", settings.rate_limit_user
    else:
        rl_key, rl_limit = f"ip:{client_ip(request)}", settings.rate_limit_anon

    allowed, retry_after = await check_rate_limit(rl_key, rl_limit)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many questions at once — give me a minute to catch up.",
            headers={"Retry-After": str(retry_after)},
        )

    message = sanitize_message(body.message, settings.max_message_chars)
    if not message:
        raise HTTPException(status_code=400, detail="Please type a question.")

    # ── PII guard: refuse BEFORE the model call, so the value never leaves us
    if detect_pii(message):
        return ChatResponse(
            reply=PII_RESPONSE, sources=[], verified=True,
            conversation_id=body.conversation_id, stored=False,
        )

    if detect_injection(message):
        return ChatResponse(
            reply=INJECTION_RESPONSE, sources=[], verified=True,
            conversation_id=body.conversation_id, stored=False,
        )

    persist = current is not None and not body.incognito

    # ── Resolve the conversation, enforcing ownership in the query ───────
    conversation: Conversation | None = None
    if persist and body.conversation_id:
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == current.id,   # ← ownership is part of the predicate
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    history = await _load_history(db, conversation, current) if conversation else []

    # ── Model call ───────────────────────────────────────────────────────
    try:
        response = await client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=[{
                "type": "text",
                "text": system_prompt(),
                "cache_control": {"type": "ephemeral"},  # ~90% off the bulk of every request
            }],
            messages=[*history, {"role": "user", "content": message}],
        )
    except anthropic.APIStatusError as exc:
        # Log the class only — never the user's content.
        import logging
        logging.getLogger("kip").warning("anthropic_error status=%s", exc.status_code)
        raise HTTPException(status_code=502, detail="Kip is momentarily unavailable. Try again shortly.")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Kip is momentarily unavailable. Try again shortly.")

    raw = "\n".join(b.text for b in response.content if b.type == "text")

    # ── Deterministic source verification ────────────────────────────────
    checked = verify_reply(raw)

    # ── Persist (encrypted) only when the user is signed in and not incognito
    if persist:
        conversation = conversation or await _new_conversation(db, current, message, body.module_id)
        await _append(db, current, conversation, "user", message, [], True)
        await _append(db, current, conversation, "assistant", checked.reply,
                      [s.as_dict() for s in checked.sources], checked.verified)
        conversation.updated_at = datetime.now(timezone.utc)
        if current.user.retention_days:
            conversation.expires_at = conversation.updated_at + timedelta(
                days=current.user.retention_days
            )
        await db.commit()

    return ChatResponse(
        reply=checked.reply,
        sources=[SourceOut(**s.as_dict()) for s in checked.sources],
        verified=checked.verified,
        conversation_id=conversation.id if conversation else None,
        stored=persist,
    )


# ── helpers ──────────────────────────────────────────────────────────────

async def _load_history(db: AsyncSession, conversation: Conversation, current: CurrentUser) -> list[dict]:
    from ..crypto import Sealed, open_sealed

    rows = (await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(settings.max_history_turns)
    )).all()

    aad = f"{current.id}|{conversation.id}"
    history = []
    for row in reversed(rows):
        try:
            content = open_sealed(current.dek, Sealed(ct=row.content_ct, nonce=row.content_nonce), aad)
        except Exception:
            continue  # a tampered or unreadable row is skipped, never fatal
        history.append({"role": row.role, "content": content[: settings.max_history_chars]})
    return history


async def _new_conversation(
    db: AsyncSession, current: CurrentUser, first_message: str, module_id: str | None
) -> Conversation:
    conv_id = uuid.uuid4()
    title = first_message[:60]
    sealed = seal(current.dek, title, aad=f"title:{current.id}|{conv_id}")
    conversation = Conversation(
        id=conv_id,
        user_id=current.id,
        title_ct=sealed.ct,
        title_nonce=sealed.nonce,
        module_id=module_id if module_id in MODULE_IDS else None,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _append(
    db: AsyncSession, current: CurrentUser, conversation: Conversation,
    role: str, content: str, sources: list, verified: bool,
) -> None:
    # AAD binds this ciphertext to this user and this conversation, so it cannot
    # be moved to another row even by someone with write access to the database.
    aad = f"{current.id}|{conversation.id}"
    sealed = seal(current.dek, content, aad)
    db.add(Message(
        conversation_id=conversation.id,
        role=role,
        content_ct=sealed.ct,
        content_nonce=sealed.nonce,
        sources=sources,
        verified=verified,
    ))
