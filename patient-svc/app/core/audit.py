"""Audit writer (LLD §19). Rows are inserted in the SAME transaction as the change they describe (P-07), so
there is never a change without its audit row, nor an audit row for a rolled-back change.

``details`` holds field NAMES, never values (§19.2): no PHI ends up in the audit table or the logs.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_request_id
from app.models import AuditEvent


async def record(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    action: str,
    resource: str,
    patient_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Must be called inside an open ``session.begin()`` block; it only flushes, never commits."""
    rid = get_request_id()
    session.add(AuditEvent(
        actor_id=actor_id, patient_id=patient_id, action=action, resource=resource, resource_id=resource_id,
        request_id=None if rid == "-" else rid, details=details or {}))
    await session.flush()


def fields(names: Iterable[str]) -> dict[str, Any]:
    """The standard ``details`` shape for writes: which fields were touched."""
    return {"fields": sorted(names)}
