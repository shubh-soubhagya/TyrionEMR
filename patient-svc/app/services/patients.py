"""Patient use cases (LLD §13.1, §13.2, §15). Services own the transaction; repositories never commit."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.dberrors import _pg_exc
from app.core.errors import AllergiesPresent, NotFound, ValidationFailed, VersionConflict
from app.core.metrics import OPTIMISTIC_CONFLICTS
from app.core.security import User
from app.domain import patient_rules
from app.domain.clock import Clock, today_in
from app.domain.search import default_direction, parse_query
from app.repositories import patients as repo
from app.schemas.patient import ListQuery, PatientCreate, PatientPatch

MAX_IDS = 500
log = logging.getLogger("patient.patients")


def _brief_primary(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["primary_description"]:
        return None
    return {"icd10_code": row["primary_icd10"], "description": row["primary_description"]}


class PatientService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self.session, self.settings, self.clock = session, settings, clock

    def today(self):
        return today_in(self.clock, self.settings.clinic_tz)

    # ---- queries -----------------------------------------------------------------------------
    async def list(self, q: ListQuery) -> dict[str, Any]:
        if q.ids is not None and len(q.ids) > MAX_IDS:
            raise ValidationFailed([("ids", f"At most {MAX_IDS} ids are accepted.")])
        search = parse_query(q.q)
        sort = q.sort or "name"
        direction = q.dir or default_direction(sort)
        relevance = " ".join(q.q.lower().split()) if (search.kind == "name" and q.sort is None and q.q) else None
        today = self.today()
        rows, total = await repo.list_patients(
            self.session, sex=q.sex, stage=q.stage, ids=q.ids, search=search, sort=sort, direction=direction,
            page=q.page, size=q.size, today=today, relevance_q=relevance)
        items = [{**r, "primary_diagnosis": _brief_primary(r)} for r in rows]
        return {"items": items, "page": q.page, "size": q.size, "total": total}

    async def get(self, pid: uuid.UUID, user: User) -> dict[str, Any]:
        # A chart read is audited in the same short transaction: if the audit insert fails, the read fails (§19.3)
        async with self.session.begin():
            patient = await repo.get_active(self.session, pid)
            if patient is None:
                raise NotFound()
            await audit.record(self.session, actor_id=user.id, action="patient.view", resource="patient",
                               patient_id=pid, resource_id=pid)
            return await self._detail(patient)

    async def _detail(self, patient) -> dict[str, Any]:
        today = self.today()
        extra = await repo.detail_extras(self.session, patient.id, today)
        agg = extra["agg"]
        return {
            "id": patient.id, "mrn": patient.mrn, "first_name": patient.first_name, "last_name": patient.last_name,
            "date_of_birth": patient.date_of_birth, "age": patient_rules.age_on(patient.date_of_birth, today),
            "sex": patient.sex, "phone": patient.phone, "email": patient.email, "address": patient.address,
            "past_medical_history": patient.past_medical_history, "family_history": patient.family_history,
            "social_history": patient.social_history, "allergy_status": patient.allergy_status,
            "allergy_summary": extra["allergies"], "established_ckd_stage": patient.established_ckd_stage,
            "primary_diagnosis": extra["primary"],
            "counts": {k: agg[k] for k in ("conditions", "active_conditions", "active_medications", "encounters")},
            "last_visit": agg["last_visit"], "next_follow_up": agg["next_follow_up"],
            "version": patient.version, "created_at": patient.created_at, "updated_at": patient.updated_at,
        }

    # ---- commands ----------------------------------------------------------------------------
    async def create(self, body: PatientCreate, user: User) -> dict[str, Any]:
        problem = patient_rules.validate_dob(body.date_of_birth, self.today())
        if problem:
            raise ValidationFailed([("date_of_birth", problem)])
        values = {**body.model_dump(), "created_by": user.id, "updated_by": user.id}
        async with self.session.begin():
            patient = await self._insert_with_mrn_retry(values)
            await audit.record(self.session, actor_id=user.id, action="patient.create", resource="patient",
                               patient_id=patient.id, resource_id=patient.id,
                               details=audit.fields(k for k, v in body.model_dump().items() if v is not None))
            detail = await self._detail(patient)
        return detail

    async def _insert_with_mrn_retry(self, values: dict[str, Any]):
        """On a clash with an explicitly inserted MRN, advance the sequence past the max and retry once (§13.1)."""
        for attempt in (1, 2):
            try:
                async with self.session.begin_nested():            # savepoint: a failed insert must not poison the tx
                    return await repo.insert(self.session, values)
            except IntegrityError as exc:
                if attempt == 2 or getattr(_pg_exc(exc), "constraint_name", None) != "patients_mrn_uq":
                    raise
                await repo.reseed_mrn_sequence(self.session)
        raise AssertionError("unreachable")

    async def update(self, pid: uuid.UUID, body: PatientPatch, user: User) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True, exclude={"version"})
        today = self.today()
        async with self.session.begin():
            current = await repo.lock_active(self.session, pid)
            if current is None:
                raise NotFound()
            if "date_of_birth" in changes:
                problem = patient_rules.validate_dob(changes["date_of_birth"], today)
                if problem:
                    raise ValidationFailed([("date_of_birth", problem)])
            if "allergy_status" in changes:
                active = await self._active_allergy_count(pid)
                if not patient_rules.can_set_allergy_status(changes["allergy_status"], active):
                    raise AllergiesPresent()
            if current.version != body.version:
                OPTIMISTIC_CONFLICTS.labels(resource="patient").inc()
                log.info("version_conflict", extra={"resource": "patient"})
                raise VersionConflict()
            new_version = await repo.update_versioned(self.session, pid, body.version, changes, user.id)
            if new_version is None:                               # cannot happen under the row lock; stay safe
                raise VersionConflict()
            await audit.record(self.session, actor_id=user.id, action="patient.update", resource="patient",
                               patient_id=pid, resource_id=pid, details=audit.fields(changes))
            await self.session.refresh(current)
            return await self._detail(current)

    async def _active_allergy_count(self, pid: uuid.UUID) -> int:
        from sqlalchemy import func, select

        from app.models import Allergy
        res = await self.session.execute(
            select(func.count()).select_from(Allergy).where(Allergy.patient_id == pid, Allergy.deleted_at.is_(None)))
        return int(res.scalar_one())

    async def delete(self, pid: uuid.UUID, user: User) -> None:
        async with self.session.begin():
            if await repo.lock_active(self.session, pid) is None:
                raise NotFound()
            await repo.soft_delete(self.session, pid, user.id)
            await audit.record(self.session, actor_id=user.id, action="patient.delete", resource="patient",
                               patient_id=pid, resource_id=pid)
