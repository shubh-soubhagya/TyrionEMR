"""Encounter persistence (LLD §13.4, §13.5). Never commits."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Encounter, EncounterDiagnosis, EncounterVitals


async def lock_for_update(session: AsyncSession, pid: uuid.UUID, eid: uuid.UUID) -> Encounter | None:
    """Second lock in the global order (patients -> encounters, §16.1). Waiters see the committed state."""
    res = await session.execute(
        select(Encounter).where(Encounter.id == eid, Encounter.patient_id == pid, Encounter.deleted_at.is_(None))
        .with_for_update().execution_options(populate_existing=True))
    return res.scalar_one_or_none()


async def get_detail(session: AsyncSession, pid: uuid.UUID, eid: uuid.UUID) -> Encounter | None:
    res = await session.execute(
        select(Encounter).where(Encounter.id == eid, Encounter.patient_id == pid, Encounter.deleted_at.is_(None))
        .options(selectinload(Encounter.vitals), selectinload(Encounter.diagnoses))
        .execution_options(populate_existing=True))
    return res.scalar_one_or_none()


async def insert(session: AsyncSession, values: dict[str, Any]) -> Encounter:
    enc = Encounter(**values)
    session.add(enc)
    await session.flush()
    return enc


async def replace_vitals(session: AsyncSession, eid: uuid.UUID, vitals: dict[str, Any] | None) -> None:
    """No row when every value is empty: 'no vitals' is the absence of the row (§9.3)."""
    await session.execute(delete(EncounterVitals).where(EncounterVitals.encounter_id == eid))
    if vitals and any(v is not None for v in vitals.values()):
        session.add(EncounterVitals(encounter_id=eid, **vitals))
        await session.flush()


async def replace_diagnoses(session: AsyncSession, eid: uuid.UUID, diagnoses: list[dict[str, Any]]) -> None:
    await session.execute(delete(EncounterDiagnosis).where(EncounterDiagnosis.encounter_id == eid))
    for seq, dx in enumerate(diagnoses, start=1):
        session.add(EncounterDiagnosis(encounter_id=eid, seq=seq, **dx))
    await session.flush()


async def diagnoses_of(session: AsyncSession, eid: uuid.UUID) -> list[EncounterDiagnosis]:
    res = await session.execute(select(EncounterDiagnosis).where(EncounterDiagnosis.encounter_id == eid)
                                .order_by(EncounterDiagnosis.seq).execution_options(populate_existing=True))
    return list(res.scalars())


async def set_diagnosis_condition(session: AsyncSession, dx_id: uuid.UUID, condition_id: uuid.UUID) -> None:
    await session.execute(update(EncounterDiagnosis).where(EncounterDiagnosis.id == dx_id)
                          .values(condition_id=condition_id).execution_options(synchronize_session=False))


async def update_fields(session: AsyncSession, eid: uuid.UUID, values: dict[str, Any]) -> None:
    await session.execute(update(Encounter).where(Encounter.id == eid)
                          .values(**values, version=Encounter.version + 1).execution_options(synchronize_session=False))


async def mark_final(session: AsyncSession, eid: uuid.UUID, user_id: uuid.UUID) -> None:
    """The trigger allows this because OLD.status = 'draft'; children must already be written (§9.3)."""
    await session.execute(update(Encounter).where(Encounter.id == eid)
                          .values(status="final", finalized_at=func.now(), finalized_by=user_id, updated_by=user_id,
                                  version=Encounter.version + 1).execution_options(synchronize_session=False))


async def soft_delete(session: AsyncSession, eid: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(update(Encounter).where(Encounter.id == eid)
                          .values(deleted_at=func.now(), updated_by=user_id).execution_options(
                              synchronize_session=False))


async def history(session: AsyncSession, pid: uuid.UUID, status: str | None, page: int,
                  size: int) -> tuple[list[dict[str, Any]], int]:
    where = "e.patient_id = :p AND e.deleted_at IS NULL" + (" AND e.status = :status" if status else "")
    params: dict[str, Any] = {"p": pid, "size": size, "offset": (page - 1) * size}
    if status:
        params["status"] = status
    rows = (await session.execute(text(f"""
        SELECT e.id, e.encounter_date, e.encounter_type, e.clinician_name, e.chief_complaint, e.assessment,
               e.follow_up_date, e.status, v.systolic_bp, v.diastolic_bp, v.heart_rate,
               (v.encounter_id IS NOT NULL) AS has_vitals
        FROM encounters e LEFT JOIN encounter_vitals v ON v.encounter_id = e.id
        WHERE {where}
        ORDER BY e.encounter_date DESC, e.created_at DESC, e.id
        LIMIT :size OFFSET :offset"""), params)).mappings().all()
    total = (await session.execute(text(f"SELECT count(*) FROM encounters e WHERE {where}"), params)).scalar_one()
    items = [{**{k: r[k] for k in ("id", "encounter_date", "encounter_type", "clinician_name", "chief_complaint",
                                   "assessment", "follow_up_date", "status")},
              "vitals_brief": ({"systolic_bp": r["systolic_bp"], "diastolic_bp": r["diastolic_bp"],
                                "heart_rate": r["heart_rate"]} if r["has_vitals"] else None)} for r in rows]
    return items, int(total)
