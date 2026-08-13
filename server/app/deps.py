"""Request dependencies: the current user, and their unwrapped data key.

`current_user` is optional by design — the whole app works signed out (guest
mode), which is what keeps the "nothing is stored" promise available to the
students who need it most.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .crypto import Sealed, unwrap_dek
from .db import get_db
from .models import User
from .sessions import read_session

settings = get_settings()


@dataclass
class CurrentUser:
    user: User
    dek: bytes  # unwrapped in memory for the life of the request only

    @property
    def id(self) -> uuid.UUID:
        return self.user.id


async def optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> CurrentUser | None:
    session = await read_session(request)
    if not session:
        return None

    user = await db.scalar(select(User).where(User.id == uuid.UUID(session.user_id)))
    if not user:
        return None

    dek = unwrap_dek(
        settings.kek,
        Sealed(ct=user.dek_ct, nonce=user.dek_nonce),
        str(user.id),
    )
    return CurrentUser(user=user, dek=dek)


async def required_user(
    current: CurrentUser | None = Depends(optional_user),
) -> CurrentUser:
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required."
        )
    return current
