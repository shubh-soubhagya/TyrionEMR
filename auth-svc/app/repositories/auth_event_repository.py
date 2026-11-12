"""All SQL for the audit trail. Writes join the caller's transaction so an event and the change it
records commit (or roll back) together."""
from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime

from sqlalchemy import text
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

    async def purge_older_than(self, s: AsyncSession, retention_days: int) -> int:
        """Retention. The runtime role has no DELETE on auth_events: the only way to remove audit rows is
        this function, which refuses anything newer than 30 days and uses the DATABASE clock."""
        return int((await s.execute(text("SELECT purge_auth_events(:days)"), {"days": retention_days})).scalar_one())
