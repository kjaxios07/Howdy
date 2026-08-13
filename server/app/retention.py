"""Nightly retention sweep.

Conversations past `expires_at` are hard-deleted; ON DELETE CASCADE takes their
messages. This is what makes the user's retention setting a real promise rather
than a preference we display back to them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete

from .db import SessionLocal
from .models import Conversation

log = logging.getLogger("kip.retention")

SWEEP_INTERVAL_S = 6 * 3600  # four times a day; cheap, and bounds worst-case overrun


async def retention_sweep_once() -> int:
    async with SessionLocal() as db:
        result = await db.execute(
            delete(Conversation).where(
                Conversation.expires_at.is_not(None),
                Conversation.expires_at < datetime.now(timezone.utc),
            )
        )
        await db.commit()
        deleted = result.rowcount or 0

    if deleted:
        log.info("retention_sweep deleted_conversations=%d", deleted)
    return deleted


async def retention_sweep_forever() -> None:
    while True:
        try:
            await retention_sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retention_sweep_failed")
        await asyncio.sleep(SWEEP_INTERVAL_S)
