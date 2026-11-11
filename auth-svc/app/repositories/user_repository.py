"""All SQL for users lives here. No HTTP errors are raised in this layer."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, bindparam, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

# Atomic: no read-modify-write race between replicas (LLD §19.2). ``:now`` comes from the injected
# clock, never SQL now(), so lock expiry can be tested with a fake clock.
_REGISTER_FAILURE = text(
    """
    UPDATE users
    SET failed_login_count = CASE WHEN failed_login_count + 1 >= :max_attempts
                                  THEN 0 ELSE failed_login_count + 1 END,
        locked_until       = CASE WHEN failed_login_count + 1 >= :max_attempts
                                  THEN :now + make_interval(mins => :lock_minutes)
                                  ELSE locked_until END,
        updated_at         = :now
    WHERE id = :user_id
    RETURNING locked_until
    """
).bindparams(
    bindparam("now", type_=TIMESTAMP(timezone=True)),
    bindparam("max_attempts", type_=Integer),
    bindparam("lock_minutes", type_=Integer),
)


class UserRepository:
    async def get_by_email(self, s: AsyncSession, email: str) -> User | None:
        return (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def get(self, s: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await s.get(User, user_id)

    async def add(self, s: AsyncSession, user: User) -> None:
        s.add(user)
        await s.flush()  # surfaces the unique-email IntegrityError here

    async def register_failure(
        self, s: AsyncSession, user_id: uuid.UUID, max_attempts: int, lock_minutes: int, now: datetime
    ) -> datetime | None:
        row = await s.execute(
            _REGISTER_FAILURE,
            {"user_id": user_id, "max_attempts": max_attempts, "lock_minutes": lock_minutes, "now": now},
        )
        return row.scalar_one_or_none()

    async def register_success(self, s: AsyncSession, user: User, new_hash: str | None, now: datetime) -> None:
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user.updated_at = now
        if new_hash:
            user.password_hash = new_hash
        await s.flush()
