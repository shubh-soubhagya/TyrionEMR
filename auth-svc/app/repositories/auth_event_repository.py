"""All SQL for the audit trail. Writes join the caller's transaction so an event and the change it
records commit (or roll back) together."""
from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthEvent


def parse_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class AuthEventRepository:
    def add(
        self,
        s: AsyncSession,
        *,
        at: datetime,
        event: str,
        outcome: str,
        user_id: uuid.UUID | None = None,
        family_id: uuid.UUID | None = None,
        request_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        s.add(AuthEvent(
            id=uuid.uuid4(), at=at, event=event, outcome=outcome, user_id=user_id, family_id=family_id,
            request_id=request_id if request_id and request_id != "-" else None, ip=parse_ip(ip),
            user_agent=user_agent[:256] if user_agent else None))

    async def delete_older_than(self, s: AsyncSession, before: datetime) -> int:
        result = cast(CursorResult, await s.execute(delete(AuthEvent).where(AuthEvent.at < before)))
        return result.rowcount or 0
