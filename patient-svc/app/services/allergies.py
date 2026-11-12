"""Allergy use cases (LLD §11.7, §13.7). ``allergy_status = has_allergies`` is derived from the rows (P-08)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateAllergy, NotFound
from app.core.security import User
from app.domain.patient_rules import allergy_status_after_removal
from app.models import Allergy
from app.repositories import patients as patients_repo
from app.schemas.chart import AllergyCreate


class AllergyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, pid: uuid.UUID) -> dict[str, Any]:
        patient = await patients_repo.get_active(self.session, pid)
        if patient is None:
            raise NotFound()
        res = await self.session.execute(select(Allergy).where(
            Allergy.patient_id == pid, Allergy.deleted_at.is_(None)).order_by(func.lower(Allergy.allergen)))
        return {"allergy_status": patient.allergy_status, "items": list(res.scalars())}

    async def create(self, pid: uuid.UUID, body: AllergyCreate, user: User) -> dict[str, Any]:
        async with self.session.begin():
            patient = await patients_repo.lock_active(self.session, pid)
            if patient is None:
                raise NotFound()
            dup = await self.session.execute(select(Allergy.id).where(
                Allergy.patient_id == pid, Allergy.deleted_at.is_(None),
                func.lower(func.btrim(Allergy.allergen)) == body.allergen.strip().lower()))
            if dup.first() is not None:
                raise DuplicateAllergy()
            allergy = Allergy(**body.model_dump(), patient_id=pid, created_by=user.id)
            self.session.add(allergy)
            await self.session.flush()
            await self.session.refresh(allergy)
            version = patient.version
            if patient.allergy_status != "has_allergies":
                version = await patients_repo.bump_version(self.session, pid, user.id, allergy_status="has_allergies")
            return {"allergy": allergy, "allergy_status": "has_allergies", "patient_version": version}

    async def remove(self, pid: uuid.UUID, aid: uuid.UUID, user: User) -> dict[str, Any]:
        async with self.session.begin():
            patient = await patients_repo.lock_active(self.session, pid)
            if patient is None:
                raise NotFound()
            res = await self.session.execute(select(Allergy).where(
                Allergy.id == aid, Allergy.patient_id == pid, Allergy.deleted_at.is_(None)))
            allergy = res.scalar_one_or_none()
            if allergy is None:
                raise NotFound()
            allergy.deleted_at, allergy.deleted_by = func.now(), user.id
            await self.session.flush()
            remaining = (await self.session.execute(select(func.count()).select_from(Allergy).where(
                Allergy.patient_id == pid, Allergy.deleted_at.is_(None)))).scalar_one()
            status = allergy_status_after_removal(int(remaining), patient.allergy_status)
            version = patient.version
            if status != patient.allergy_status:
                version = await patients_repo.bump_version(self.session, pid, user.id, allergy_status=status)
            return {"allergy_status": status, "patient_version": version}
