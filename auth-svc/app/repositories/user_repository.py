"""All SQL for users lives here. No HTTP errors are raised in this layer."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, bindparam, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

_TS = TIMESTAMP(timezone=True)

# Attempt reservation (LLD §19.2). One atomic statement both checks and consumes an attempt, so N
# parallel guesses can only ever obtain `max_attempts` reservations and the rest never reach argon2.
# Failures older than the decay window no longer count (the CASE resets the counter first).
# ``:now`` comes from the injected clock, never SQL now().
_RESERVE = text(
    """
    UPDATE users
    SET failed_login_count = (CASE WHEN last_failed_at IS NOT NULL
                                    AND last_failed_at < :now - make_interval(mins => :window)
                                   THEN 0 ELSE failed_login_count END) + 1,
        last_failed_at = :now,
        updated_at = :now
    WHERE id = :user_id
      AND (locked_until IS NULL OR locked_until <= :now)
      AND (CASE WHEN last_failed_at IS NOT NULL
                 AND last_failed_at < :now - make_interval(mins => :window)
                THEN 0 ELSE failed_login_count END) < :max_attempts
    RETURNING failed_login_count
    """
).bindparams(
    bindparam("now", type_=_TS), bindparam("window", type_=Integer), bindparam("max_attempts", type_=Integer),
)

# Idempotent lock: only the request that actually flips the account to locked gets a row back.
_LOCK_OUT = text(
    """
    UPDATE users
    SET locked_until = :now + make_interval(mins => :lock_minutes),
        failed_login_count = 0,
        updated_at = :now
    WHERE id = :user_id AND (locked_until IS NULL OR locked_until <= :now)
    RETURNING locked_until
    """
).bindparams(bindparam("now", type_=_TS), bindparam("lock_minutes", type_=Integer))

# Give back an attempt that was reserved but never judged (service busy, or correct password on a
# disabled account), so load or a disabled account cannot push a user toward lockout.
_RELEASE = text(
    "UPDATE users SET failed_login_count = GREATEST(failed_login_count - 1, 0) "
    "WHERE id = :user_id AND failed_login_count > 0"
)


class UserRepository:
    async def get_by_email(self, s: AsyncSession, email: str) -> User | None:
        return (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def get(self, s: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await s.get(User, user_id)

    async def get_for_update(self, s: AsyncSession, user_id: uuid.UUID) -> User | None:
        """Row lock: serializes the success path against a concurrent lock-out."""
        stmt = select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
        return (await s.execute(stmt)).scalar_one_or_none()

    async def add(self, s: AsyncSession, user: User) -> None:
        s.add(user)
        await s.flush()  # surfaces the unique-email IntegrityError here

    async def reserve_attempt(
        self, s: AsyncSession, user_id: uuid.UUID, max_attempts: int, window_minutes: int, now: datetime
    ) -> int | None:
        """Returns the new failed count, or None if the account is locked or out of attempts."""
        row = await s.execute(_RESERVE, {"user_id": user_id, "max_attempts": max_attempts,
                                         "window": window_minutes, "now": now})
        return row.scalar_one_or_none()

    async def lock_out(self, s: AsyncSession, user_id: uuid.UUID, lock_minutes: int, now: datetime) -> datetime | None:
        """Locks the account if it is not already locked; returns the effective ``locked_until``."""
        row = await s.execute(_LOCK_OUT, {"user_id": user_id, "lock_minutes": lock_minutes, "now": now})
        locked_until = row.scalar_one_or_none()
        if locked_until is not None:
            return locked_until
        # someone else locked it first: report their deadline
        return (await s.execute(select(User.locked_until).where(User.id == user_id))).scalar_one_or_none()

    async def release_attempt(self, s: AsyncSession, user_id: uuid.UUID) -> None:
        await s.execute(_RELEASE, {"user_id": user_id})

    async def register_success(self, s: AsyncSession, user: User, new_hash: str | None, now: datetime) -> None:
        user.failed_login_count = 0
        user.locked_until = None
        user.last_failed_at = None
        user.last_login_at = now
        user.updated_at = now
        if new_hash:
            user.password_hash = new_hash
        await s.flush()
