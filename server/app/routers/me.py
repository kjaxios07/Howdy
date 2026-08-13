"""Account, retention settings, data export and account deletion.

These are legal obligations, not nice-to-haves — Australian Privacy Principles
11.2 (destruction), 12 (access) and GDPR Articles 17 and 20 for EU students.
Build them in the same sprint as accounts, never "later".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import Sealed, open_sealed
from ..db import audit, get_db
from ..deps import CurrentUser, required_user
from ..models import Conversation, Message, User
from ..sessions import destroy_all_for_user

settings = get_settings()
router = APIRouter(prefix="/api/me", tags=["account"])


class MeOut(BaseModel):
    id: str
    display_name: str | None
    email: str
    retention_days: int
    created_at: datetime


class RetentionRequest(BaseModel):
    retention_days: int

    @field_validator("retention_days")
    @classmethod
    def allowed(cls, v: int) -> int:
        if v not in settings.allowed_retention_days:
            raise ValueError(
                f"retention_days must be one of {settings.allowed_retention_days} "
                "(0 means keep until I delete it)"
            )
        return v


def _email_of(current: CurrentUser) -> str:
    return open_sealed(
        current.dek,
        Sealed(ct=current.user.email_ct, nonce=current.user.email_nonce),
        aad=f"email:{current.id}",
    )


@router.get("", response_model=MeOut)
async def me(current: CurrentUser = Depends(required_user)):
    return MeOut(
        id=str(current.id),
        display_name=current.user.display_name,
        email=_email_of(current),
        retention_days=current.user.retention_days,
        created_at=current.user.created_at,
    )


@router.patch("/retention", response_model=MeOut)
async def set_retention(
    body: RetentionRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(required_user),
):
    current.user.retention_days = body.retention_days

    # Recompute expiry across existing conversations so the new setting is real,
    # not just a preference that applies to future chats.
    convs = (await db.scalars(
        select(Conversation).where(Conversation.user_id == current.id)
    )).all()
    for c in convs:
        c.expires_at = (
            c.updated_at + timedelta(days=body.retention_days)
            if body.retention_days
            else None
        )

    await audit(db, action="account.retention_changed", user_id=current.id,
                meta={"retention_days": body.retention_days})
    await db.commit()
    return await me(current)


@router.get("/export")
async def export_data(
    db: AsyncSession = Depends(get_db), current: CurrentUser = Depends(required_user)
):
    """APP 12 / GDPR Art 15 & 20 — everything we hold, decrypted, as JSON."""
    convs = (await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == current.id)
        .order_by(Conversation.created_at)
    )).all()

    out_convs = []
    for c in convs:
        rows = (await db.scalars(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
        )).all()
        aad = f"{current.id}|{c.id}"
        msgs = []
        for m in rows:
            try:
                content = open_sealed(current.dek, Sealed(ct=m.content_ct, nonce=m.content_nonce), aad)
            except Exception:
                content = "[unreadable]"
            msgs.append({
                "role": m.role, "content": content, "sources": m.sources,
                "created_at": m.created_at.isoformat(),
            })
        title = "Untitled chat"
        if c.title_ct:
            try:
                title = open_sealed(current.dek, Sealed(ct=c.title_ct, nonce=c.title_nonce),
                                    aad=f"title:{current.id}|{c.id}")
            except Exception:
                pass
        out_convs.append({
            "id": str(c.id), "title": title, "module": c.module_id,
            "created_at": c.created_at.isoformat(), "messages": msgs,
        })

    await audit(db, action="account.export", user_id=current.id)
    await db.commit()

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "id": str(current.id),
            "email": _email_of(current),
            "display_name": current.user.display_name,
            "created_at": current.user.created_at.isoformat(),
            "retention_days": current.user.retention_days,
        },
        "conversations": out_convs,
    }


@router.delete("", status_code=204)
async def delete_account(
    db: AsyncSession = Depends(get_db), current: CurrentUser = Depends(required_user)
):
    """APP 11.2 / GDPR Art 17 — real deletion, and every session killed.

    The audit row deliberately carries no user_id: we record that a deletion
    happened without retaining a pointer to the person who asked for it.
    """
    user_id = str(current.id)

    await db.execute(delete(User).where(User.id == current.id))  # cascades to conversations & messages
    await audit(db, action="account.delete", user_id=None,
                meta={"note": "user-initiated erasure"})
    await db.commit()

    await destroy_all_for_user(user_id)
