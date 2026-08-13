"""ORM models.

Note what is *not* stored in plaintext: message content, conversation titles,
and email addresses. `module_id` and source domains are deliberately plaintext —
they carry no personal information and we want them for product analytics.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Email: HMAC for lookup, AES-GCM for the value itself.
    email_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    email_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(255))

    # Per-user data key, wrapped by the KEK.
    dek_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    consent_version: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    title_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)

    module_id: Mapped[str | None] = mapped_column(String(32))  # non-sensitive

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conv_user_updated", "user_id", "updated_at"),
        Index("ix_conv_expires", "expires_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        CheckConstraint("role in ('user','assistant')", name="ck_message_role"),
        Index("ix_msg_conv_created", "conversation_id", "created_at"),
    )


class AuditLog(Base):
    """Append-only. NEVER contains message content."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # null after deletion
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary)  # HMAC, never a raw IP
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
