"""The chat endpoints — the only routes that call the model.

Pipeline (everything except the model call is deterministic):
    validate -> rate limit -> PII guard -> injection guard
             -> Claude (prompt-cached, + domain-restricted web search)
             -> source verification -> persist -> respond

Two endpoints:
    POST /api/chat          buffered — simple, used as the fallback
    POST /api/chat/stream   Server-Sent Events — live progress + token stream

Storage modes:
    guest      — not signed in.        Nothing is written. Ever.
    incognito  — signed in, opted out. Nothing is written.
    saved      — signed in, default.   Encrypted with the user's own data key.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import gaps, websearch
from ..config import get_settings
from ..crypto import Sealed, open_sealed, seal
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
from ..costreport import combine, record
from ..costs import Usage
from ..ratelimit import hash_ip
from .. import quota
from ..sources import verify_reply

log = logging.getLogger("kip.chat")
settings = get_settings()
router = APIRouter(prefix="/api", tags=["chat"])

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_key)

UNAVAILABLE = "Kip is momentarily unavailable. Try again shortly."


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
    searched: bool = False
    search_queries: list[str] = []
    conversation_id: uuid.UUID | None = None
    stored: bool


# ── Shared request preparation ───────────────────────────────────────────


class Refusal(Exception):
    """A guard stopped the request before the model was called."""

    def __init__(self, reply: str):
        self.reply = reply


async def _prepare(
    body: ChatRequest, request: Request, db: AsyncSession, current: CurrentUser | None
) -> tuple[str, Conversation | None, list[dict], bool]:
    """Rate limit, sanitise, run the guards, load history. Raises Refusal/HTTPException."""
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

    # Daily allowance. Deliberately AFTER sanitising (an empty message should
    # not spend a slot) and BEFORE the guards, so a refused question does not
    # burn one either — being told off for pasting your TFN should not also
    # cost you a question.
    #
    # Guests are counted by hashed IP, so signing out still writes nothing
    # durable. Safety topics are exempt inside check() and never reach a
    # counter at all.
    subject = str(current.id) if current else hash_ip(client_ip(request)).hex()[:32]
    tier = quota.tier_for(
        signed_in=current is not None,
        subscribed=bool(getattr(current, "subscribed", False)),
    )
    verdict = await quota.check(subject, body.module_id, tier)
    if not verdict.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=quota.message(verdict, tier),
            headers={"Retry-After": str(verdict.retry_after)},
        )

    # PII guard runs BEFORE the model call, so the value never leaves us.
    if detect_pii(message):
        raise Refusal(PII_RESPONSE)
    if detect_injection(message):
        raise Refusal(INJECTION_RESPONSE)

    persist = current is not None and not body.incognito

    conversation: Conversation | None = None
    if persist and body.conversation_id:
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == current.id,   # ← ownership in the predicate
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    history = await _load_history(db, conversation, current) if conversation else []
    return message, conversation, history, persist


def _request_kwargs(history: list[dict], message: str) -> dict:
    tools = []
    if (tool := websearch.tool_definition()) is not None:
        tools.append(tool)

    kwargs = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "system": [{
            "type": "text",
            "text": system_prompt(),
            "cache_control": {"type": "ephemeral"},  # ~90% off the bulk of every request
        }],
        "messages": [*history, {"role": "user", "content": message}],
    }
    if tools:
        kwargs["tools"] = tools
    return kwargs


# ── Buffered endpoint ────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser | None = Depends(optional_user),
) -> ChatResponse:
    try:
        message, conversation, history, persist = await _prepare(body, request, db, current)
    except Refusal as refusal:
        return ChatResponse(
            reply=refusal.reply, sources=[], verified=True,
            conversation_id=body.conversation_id, stored=False,
        )

    kwargs = _request_kwargs(history, message)
    blocks: list = []
    usages: list[Usage] = []

    try:
        # A server-tool turn can stop with pause_turn when the search loop hits
        # its internal limit. Resend to resume; cap the resumes so a pathological
        # case cannot loop forever.
        for _ in range(3):
            response = await client.messages.create(**kwargs)
            blocks.extend(response.content)
            # Every leg is billed, so every leg is metered. Charging only the
            # last one would under-report exactly the answers that cost most.
            usages.append(Usage.from_api(response.usage))
            if response.stop_reason != "pause_turn":
                break
            kwargs["messages"] = [
                *kwargs["messages"],
                {"role": "assistant", "content": response.content},
            ]
    except anthropic.APIStatusError as exc:
        log.warning("anthropic_error status=%s", exc.status_code)  # never log content
        raise HTTPException(status_code=502, detail=UNAVAILABLE)
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail=UNAVAILABLE)

    raw_text = "\n".join(b.text for b in blocks if getattr(b, "type", None) == "text")
    trace = websearch.trace_from_response(blocks)
    checked = verify_reply(raw_text)
    merged = websearch.merge_sources(checked.sources, trace)

    if persist:
        conversation = await _persist(
            db, current, conversation, body.module_id, message, checked, merged
        )

    await _record_gap(db, message, body.module_id, checked.reply, merged, trace.used)
    await record(db, settings.model, combine(usages), body.module_id)

    return ChatResponse(
        reply=checked.reply,
        sources=[SourceOut(**s) for s in merged],
        verified=checked.verified,
        searched=trace.used,
        search_queries=trace.queries,
        conversation_id=conversation.id if conversation else None,
        stored=persist,
    )


# ── Streaming endpoint ───────────────────────────────────────────────────


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser | None = Depends(optional_user),
):
    """SSE stream so a search-backed answer doesn't look like a frozen page.

    Events:
        status   {phase: thinking|searching|reading|writing, detail}
        delta    {text}                     incremental answer text
        done     {reply, sources, verified, searched, conversation_id, stored}
        error    {detail}
    """
    try:
        message, conversation, history, persist = await _prepare(body, request, db, current)
    except Refusal as refusal:
        async def refused() -> AsyncIterator[str]:
            yield _sse("done", {
                "reply": refusal.reply, "sources": [], "verified": True,
                "searched": False, "stored": False,
                "conversation_id": str(body.conversation_id) if body.conversation_id else None,
            })
        return StreamingResponse(refused(), media_type="text/event-stream")

    async def generate() -> AsyncIterator[str]:
        nonlocal conversation
        kwargs = _request_kwargs(history, message)
        blocks: list = []
        usages: list[Usage] = []
        text_parts: list[str] = []

        try:
            yield _sse("status", {"phase": "thinking", "detail": "Reading your question"})

            for _ in range(3):
                async with client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        etype = getattr(event, "type", "")

                        if etype == "content_block_start":
                            block = getattr(event, "content_block", None)
                            btype = getattr(block, "type", "")
                            if btype == "server_tool_use":
                                yield _sse("status", {
                                    "phase": "searching",
                                    "detail": "Checking official Australian sources",
                                })
                            elif btype == "web_search_tool_result":
                                yield _sse("status", {
                                    "phase": "reading",
                                    "detail": "Reading what the source says",
                                })
                            elif btype == "text":
                                yield _sse("status", {"phase": "writing", "detail": "Writing your answer"})

                        elif etype == "text":
                            chunk = getattr(event, "text", "")
                            if chunk:
                                text_parts.append(chunk)
                                yield _sse("delta", {"text": chunk})

                    final = await stream.get_final_message()

                blocks.extend(final.content)
                usages.append(Usage.from_api(final.usage))
                if final.stop_reason != "pause_turn":
                    break
                kwargs["messages"] = [
                    *kwargs["messages"],
                    {"role": "assistant", "content": final.content},
                ]

        except anthropic.APIStatusError as exc:
            log.warning("anthropic_error status=%s", exc.status_code)
            yield _sse("error", {"detail": UNAVAILABLE})
            return
        except anthropic.APIConnectionError:
            yield _sse("error", {"detail": UNAVAILABLE})
            return
        except Exception:
            log.exception("stream_failed")
            yield _sse("error", {"detail": UNAVAILABLE})
            return

        # Verification happens on the complete text. The client swaps in this
        # verified copy — streamed text is never the final record.
        raw_text = "".join(text_parts) or "\n".join(
            b.text for b in blocks if getattr(b, "type", None) == "text"
        )
        trace = websearch.trace_from_response(blocks)
        checked = verify_reply(raw_text)
        merged = websearch.merge_sources(checked.sources, trace)

        if persist:
            try:
                conversation = await _persist(
                    db, current, conversation, body.module_id, message, checked, merged
                )
            except Exception:
                log.exception("persist_failed")  # a save failure must not lose the answer

        await _record_gap(db, message, body.module_id, checked.reply, merged, trace.used)
        await record(db, settings.model, combine(usages), body.module_id)

        yield _sse("done", {
            "reply": checked.reply,
            "sources": merged,
            "verified": checked.verified,
            "searched": trace.used,
            "search_queries": trace.queries,
            "conversation_id": str(conversation.id) if conversation else None,
            "stored": persist,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )



async def _record_gap(db, message: str, module_id, reply: str, sources, searched: bool) -> None:
    """Log coverage, never the user. Failures here must never break a reply."""
    try:
        await gaps.record(
            db,
            question=message,
            module_id=module_id,
            answered_well=gaps.answered_well(reply, sources),
            searched=searched,
        )
        await db.commit()
    except Exception:
        log.exception("gap_record_failed")


# ── helpers ──────────────────────────────────────────────────────────────


async def _persist(
    db: AsyncSession,
    current: CurrentUser,
    conversation: Conversation | None,
    module_id: str | None,
    message: str,
    checked,
    merged: list[dict],
) -> Conversation:
    conversation = conversation or await _new_conversation(db, current, message, module_id)
    await _append(db, current, conversation, "user", message, [], True)
    await _append(db, current, conversation, "assistant", checked.reply, merged, checked.verified)
    conversation.updated_at = datetime.now(timezone.utc)
    if current.user.retention_days:
        conversation.expires_at = conversation.updated_at + timedelta(
            days=current.user.retention_days
        )
    await db.commit()
    return conversation


async def _load_history(
    db: AsyncSession, conversation: Conversation, current: CurrentUser
) -> list[dict]:
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
            continue  # an unreadable row is skipped, never fatal
        history.append({"role": row.role, "content": content[: settings.max_history_chars]})
    return history


async def _new_conversation(
    db: AsyncSession, current: CurrentUser, first_message: str, module_id: str | None
) -> Conversation:
    conv_id = uuid.uuid4()
    sealed = seal(current.dek, first_message[:60], aad=f"title:{current.id}|{conv_id}")
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
