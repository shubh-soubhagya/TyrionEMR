from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PatientCondition as C


async def list_for_patient(session: AsyncSession, pid: uuid.UUID, status: str | None) -> list[C]:
    q = select(C).where(C.patient_id == pid, C.deleted_at.is_(None))
    if status:
        q = q.where(C.status == status)
    # primary first, then nephrology before comorbidity, then newest onset
    q = q.order_by(C.is_primary.desc(), case((C.category == "nephrology", 0), else_=1),
                   C.onset_date.desc().nulls_last(), C.created_at)
    return list((await session.execute(q)).scalars())


async def get(session: AsyncSession, pid: uuid.UUID, cid: uuid.UUID) -> C | None:
    res = await session.execute(select(C).where(C.id == cid, C.patient_id == pid, C.deleted_at.is_(None)))
    return res.scalar_one_or_none()


async def active_and_resolved(session: AsyncSession, pid: uuid.UUID) -> list[C]:
    return await list_for_patient(session, pid, None)


async def clear_primary(session: AsyncSession, pid: uuid.UUID, except_id: uuid.UUID | None = None) -> bool:
    """Clear BEFORE setting: the partial unique index is checked per statement (§13.3). True if one was cleared."""
    q = update(C).where(C.patient_id == pid, C.is_primary.is_(True), C.deleted_at.is_(None))
    if except_id is not None:
        q = q.where(C.id != except_id)
    res = await session.execute(q.values(is_primary=False).execution_options(synchronize_session=False))
    return bool(res.rowcount)  # type: ignore[attr-defined]


async def insert(session: AsyncSession, values: dict[str, Any]) -> C:
    cond = C(**values)
    session.add(cond)
    await session.flush()
    await session.refresh(cond)
    return cond


async def apply(session: AsyncSession, cond: C, values: dict[str, Any]) -> C:
    for k, v in values.items():
        setattr(cond, k, v)
    await session.flush()
    await session.refresh(cond)
    return cond
