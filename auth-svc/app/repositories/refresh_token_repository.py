"""All SQL for refresh tokens lives here. No HTTP errors are raised in this layer."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken


class RefreshTokenRepository:
    async def get_by_hash_for_update(self, s: AsyncSession, token_hash: str) -> RefreshToken | None:
        # FOR UPDATE serializes concurrent refreshes of the same token (LLD §19.3)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return (await s.execute(stmt)).scalar_one_or_none()

    async def add(self, s: AsyncSession, token: RefreshToken) -> None:
        s.add(token)
        await s.flush()  # so token.id exists for replaced_by_id

    async def revoke_family(self, s: AsyncSession, family_id: uuid.UUID, reason: str, now: datetime) -> int:
        result = cast(CursorResult, await s.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        ))
        return result.rowcount or 0

    async def revoke_user_sessions(
        self,
        s: AsyncSession,
        user_id: uuid.UUID,
        reason: str,
        now: datetime,
        except_family_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every active token of a user, optionally sparing one session family."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )
        if except_family_id is not None:
            stmt = stmt.where(RefreshToken.family_id != except_family_id)
        return cast(CursorResult, await s.execute(stmt)).rowcount or 0

    async def delete_expired(self, s: AsyncSession, before: datetime) -> int:
        result = cast(CursorResult, await s.execute(
            delete(RefreshToken).where(
                or_(RefreshToken.expires_at < before, RefreshToken.family_expires_at < before)
            )
        ))
        return result.rowcount or 0
