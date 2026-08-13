"""Chat history: list, read, rename, delete.

Every query carries `user_id` in the WHERE clause. That is not stylistic —
broken object-level access control is the single most common serious flaw in
apps shaped like this one, and the repository signature is what prevents it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import Sealed, open_sealed, seal
from ..db import audit, get_db
from ..deps import CurrentUser, required_user
from ..models import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    module_id: str | None
    updated_at: datetime
    expires_at: datetime | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    sources: list
    verified: bool
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _title_of(current: CurrentUser, conv: Conversation) -> str:
    if not conv.title_ct:
        return "Untitled chat"
    try:
        return open_sealed(
            current.dek,
            Sealed(ct=conv.title_ct, nonce=conv.title_nonce),
            aad=f"title:{current.id}|{conv.id}",
        )
    except Exception:
        return "Untitled chat"


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db), current: CurrentUser = Depends(required_user)
):
    rows = (await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == current.id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )).all()
    return [
        ConversationOut(
            id=c.id, title=_title_of(current, c), module_id=c.module_id,
            updated_at=c.updated_at, expires_at=c.expires_at,
        )
        for c in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(required_user),
):
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current.id,   # ← ownership in the predicate
        )
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    rows = (await db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )).all()

    aad = f"{current.id}|{conv.id}"
    messages = []
    for m in rows:
        try:
            content = open_sealed(current.dek, Sealed(ct=m.content_ct, nonce=m.content_nonce), aad)
        except Exception:
            continue
        messages.append(MessageOut(
            id=m.id, role=m.role, content=content,
            sources=m.sources, verified=m.verified, created_at=m.created_at,
        ))

    return ConversationDetail(
        id=conv.id, title=_title_of(current, conv), module_id=conv.module_id,
        updated_at=conv.updated_at, expires_at=conv.expires_at, messages=messages,
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: RenameRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(required_user),
):
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == current.id
        )
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    sealed = seal(current.dek, body.title, aad=f"title:{current.id}|{conv.id}")
    conv.title_ct, conv.title_nonce = sealed.ct, sealed.nonce
    await db.commit()

    return ConversationOut(
        id=conv.id, title=body.title, module_id=conv.module_id,
        updated_at=conv.updated_at, expires_at=conv.expires_at,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(required_user),
):
    """Hard delete. Not a soft-delete flag.

    If a student asks us to erase a conversation about a workplace complaint,
    "we set deleted_at" is not erasure. Messages go via ON DELETE CASCADE.
    """
    result = await db.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == current.id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await audit(db, action="conversation.delete", user_id=current.id)
    await db.commit()
