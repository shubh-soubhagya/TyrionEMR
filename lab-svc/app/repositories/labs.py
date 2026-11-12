"""Queries for reports, results and the read model. No business rules here."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.flagging import ABNORMAL_FLAGS
from app.domain.status import ResultPoint
from app.models import LabReport, LabResult, PatientLabStatus


def _effective():
    """Condition: the result has not been superseded by a correction."""
    newer = aliased(LabResult)
    return ~select(newer.id).where(newer.supersedes_id == LabResult.id).exists()


class LabRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def lock_patient(self, patient_id: uuid.UUID) -> None:
        """Serialises writers of one patient so the read model is recomputed from a consistent set."""
        await self._s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                              {"k": f"lab:{patient_id}"})

    def add(self, *rows: LabReport | LabResult) -> None:
        self._s.add_all(rows)

    async def flush(self) -> None:
        await self._s.flush()

    async def get_result(self, result_id: uuid.UUID) -> LabResult | None:
        return await self._s.get(LabResult, result_id)

    async def is_superseded(self, result_id: uuid.UUID) -> bool:
        q = select(func.count()).select_from(LabResult).where(LabResult.supersedes_id == result_id)
        return (await self._s.scalar(q) or 0) > 0

    async def effective_points(self, patient_id: uuid.UUID) -> list[ResultPoint]:
        q = select(LabResult).where(LabResult.patient_id == patient_id, _effective())
        rows = (await self._s.scalars(q)).all()
        return [ResultPoint(r.id, r.report_id, r.test_code, r.value, r.unit, r.flag, r.collected_at, r.created_at)
                for r in rows]

    async def patients_with_results(self) -> list[uuid.UUID]:
        return list((await self._s.scalars(select(LabResult.patient_id).distinct())).all())

    async def save_status(self, patient_id: uuid.UUID, status: dict[str, Any]) -> None:
        stmt = pg_insert(PatientLabStatus).values(patient_id=patient_id, **status)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PatientLabStatus.patient_id],
            set_={**status, "version": PatientLabStatus.version + 1, "updated_at": func.clock_timestamp()})
        await self._s.execute(stmt)

    # ---- reads ---------------------------------------------------------------------------------------
    async def list_results(self, patient_id: uuid.UUID, *, test: str | None, date_from: datetime | None,
                           date_to: datetime | None, flag: str | None, include_superseded: bool,
                           offset: int, limit: int) -> tuple[list[LabResult], int]:
        cond = [LabResult.patient_id == patient_id]
        if not include_superseded:
            cond.append(_effective())
        if test:
            cond.append(LabResult.test_code == test)
        if date_from:
            cond.append(LabResult.collected_at >= date_from)
        if date_to:
            cond.append(LabResult.collected_at <= date_to)
        if flag == "abnormal":
            cond.append(LabResult.flag.in_(sorted(ABNORMAL_FLAGS)))
        elif flag:
            cond.append(LabResult.flag == flag)
        total = await self._s.scalar(select(func.count()).select_from(LabResult).where(*cond)) or 0
        q = (select(LabResult).where(*cond)
             .order_by(LabResult.collected_at.desc(), LabResult.created_at.desc(), LabResult.id)
             .offset(offset).limit(limit))
        return list((await self._s.scalars(q)).all()), total

    async def series(self, patient_id: uuid.UUID, tests: Sequence[str], date_from: datetime | None,
                     date_to: datetime | None) -> list[LabResult]:
        cond = [LabResult.patient_id == patient_id, LabResult.test_code.in_(list(tests)), _effective()]
        if date_from:
            cond.append(LabResult.collected_at >= date_from)
        if date_to:
            cond.append(LabResult.collected_at <= date_to)
        q = select(LabResult).where(*cond).order_by(LabResult.collected_at, LabResult.created_at)
        return list((await self._s.scalars(q)).all())

    async def status(self, patient_id: uuid.UUID) -> PatientLabStatus | None:
        return await self._s.get(PatientLabStatus, patient_id)

    async def statuses(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, PatientLabStatus]:
        rows = (await self._s.scalars(select(PatientLabStatus).where(PatientLabStatus.patient_id.in_(list(ids))))).all()
        return {r.patient_id: r for r in rows}

    async def status_page(self, cursor: uuid.UUID | None, limit: int) -> list[PatientLabStatus]:
        q = select(PatientLabStatus).order_by(PatientLabStatus.patient_id).limit(limit)
        if cursor:
            q = q.where(PatientLabStatus.patient_id > cursor)
        return list((await self._s.scalars(q)).all())
