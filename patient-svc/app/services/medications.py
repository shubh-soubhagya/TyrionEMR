"""Medication use cases (LLD §11.6, §13.8). Repository calls are small, so they live here as ORM statements."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.errors import MedicationAlreadyDiscontinued, NotFound, ValidationFailed
from app.core.security import User
from app.domain.clock import Clock, today_in
from app.models import Medication
from app.repositories import patients as patients_repo
from app.schemas.chart import MedicationCreate, MedicationPatch


class MedicationService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self.session, self.settings, self.clock = session, settings, clock

    def today(self) -> date:
        return today_in(self.clock, self.settings.clinic_tz)

    async def list(self, pid: uuid.UUID, include_all: bool) -> list[Medication]:
        if not await patients_repo.exists(self.session, pid):
            raise NotFound()
        q = select(Medication).where(Medication.patient_id == pid, Medication.deleted_at.is_(None))
        if not include_all:
            q = q.where(Medication.status == "active")
        q = q.order_by(case((Medication.status == "active", 0), else_=1), Medication.start_date.desc().nulls_last(),
                       Medication.name)
        return list((await self.session.execute(q)).scalars())

    async def create(self, pid: uuid.UUID, body: MedicationCreate, user: User) -> Medication:
        start = body.start_date or self.today()                     # defaults to today (§11.6)
        self._check_dates(start, body.end_date)
        async with self.session.begin():
            await self._lock(pid)
            med = Medication(**{**body.model_dump(), "start_date": start}, patient_id=pid,
                             created_by=user.id, updated_by=user.id)
            self.session.add(med)
            await self.session.flush()
            await self.session.refresh(med)
            await audit.record(self.session, actor_id=user.id, action="medication.add", resource="medication",
                               patient_id=pid, resource_id=med.id,
                               details=audit.fields(k for k, v in body.model_dump().items() if v is not None))
            return med

    async def patch(self, pid: uuid.UUID, mid: uuid.UUID, body: MedicationPatch, user: User) -> Medication:
        changes: dict[str, Any] = body.model_dump(exclude_unset=True)
        action = changes.pop("action", None)
        async with self.session.begin():
            await self._lock(pid)
            res = await self.session.execute(select(Medication).where(
                Medication.id == mid, Medication.patient_id == pid, Medication.deleted_at.is_(None)).with_for_update())
            med = res.scalar_one_or_none()
            if med is None:
                raise NotFound()
            if med.status == "discontinued":                        # discontinued medications cannot be edited
                raise MedicationAlreadyDiscontinued()
            values: dict[str, Any] = dict(changes)
            if action == "discontinue":
                today = self.today()
                earliest = values.get("end_date") or med.end_date or today        # keep an earlier end date
                values.update(status="discontinued", end_date=min(earliest, today))
            self._check_dates(med.start_date, values.get("end_date", med.end_date))
            for k, v in {**values, "updated_by": user.id}.items():
                setattr(med, k, v)
            await self.session.flush()
            await self.session.refresh(med)
            await audit.record(self.session, actor_id=user.id,
                               action="medication.discontinue" if action else "medication.update",
                               resource="medication", patient_id=pid, resource_id=mid,
                               details=audit.fields(values))
            return med

    async def _lock(self, pid: uuid.UUID) -> None:
        if await patients_repo.lock_active(self.session, pid) is None:
            raise NotFound()

    @staticmethod
    def _check_dates(start: date | None, end: date | None) -> None:
        if start and end and end < start:
            raise ValidationFailed([("end_date", "End date cannot be before the start date.")])
