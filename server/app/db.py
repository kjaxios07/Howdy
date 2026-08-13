"""Async engine, session factory, and the audit helper."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,   # survives Postgres restarts without a stampede of errors
    echo=False,           # never log SQL in production — parameters may hold ciphertext
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def audit(
    session: AsyncSession,
    *,
    action: str,
    user_id=None,
    ip_hash: bytes | None = None,
    meta: dict | None = None,
) -> None:
    """Write an audit row. Callers must never pass message content in `meta`."""
    from .models import AuditLog

    session.add(
        AuditLog(user_id=user_id, action=action, ip_hash=ip_hash, meta=meta or {})
    )
