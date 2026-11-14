"""Problem-list use cases (LLD §13.3, §13.5). Every write runs under the patient row lock (P-01)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.errors import ConditionNotActive, NotFound, ValidationFailed
from app.core.security import User
from app.domain.clock import Clock, today_in
from app.domain.problem_list import ConditionRef, infer_category, resolve_link
from app.models import PatientCondition
from app.repositories import conditions as repo
from app.repositories import patients as patients_repo
from app.schemas.chart import ConditionCreate, ConditionPatch


class ConditionService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self.session, self.settings, self.clock = session, settings, clock

    def today(self) -> date:
        return today_in(self.clock, self.settings.clinic_tz)

    async def list(self, pid: uuid.UUID, status: str | None) -> list[PatientCondition]:
        if not await patients_repo.exists(self.session, pid):
            raise NotFound()
        return await repo.list_for_patient(self.session, pid, status)

    async def create(self, pid: uuid.UUID, body: ConditionCreate, user: User) -> PatientCondition:
        self._check_onset(body.onset_date)
        async with self.session.begin():
            await self._lock(pid)
            if body.is_primary:
                await repo.clear_primary(self.session, pid)
            cond = await repo.insert(self.session, {
                **body.model_dump(), "patient_id": pid, "created_by": user.id, "updated_by": user.id})
            await audit.record(self.session, actor_id=user.id, action="condition.add", resource="condition",
                               patient_id=pid, resource_id=cond.id,
                               details=audit.fields(k for k, v in body.model_dump().items() if v not in (None, False)))
            await patients_repo.refresh_primary_dx_sort(self.session, pid)      # derived sort key, same transaction
            return cond

    async def patch(self, pid: uuid.UUID, cid: uuid.UUID, body: ConditionPatch,
                    user: User) -> tuple[PatientCondition, bool]:
        changes: dict[str, Any] = body.model_dump(exclude_unset=True)
        make_primary = changes.pop("is_primary", False)
        new_status = changes.pop("status", None)
        if "onset_date" in changes:
            self._check_onset(changes["onset_date"])
        async with self.session.begin():
            await self._lock(pid)
            cond = await repo.get(self.session, pid, cid)
            if cond is None:
                raise NotFound()
            primary_cleared = False
            values: dict[str, Any] = {**changes, "updated_by": user.id}
            if new_status == "resolved" and cond.status != "resolved":
                values.update(status="resolved", resolved_date=self.today())
                if cond.is_primary:
                    values["is_primary"] = False
                    primary_cleared = True
            elif new_status == "active" and cond.status != "active":
                values.update(status="active", resolved_date=None)
            effective_status = values.get("status", cond.status)
            if make_primary:
                if effective_status != "active":
                    raise ConditionNotActive()
                await repo.clear_primary(self.session, pid, except_id=cid)
                values["is_primary"] = True
            cond = await repo.apply(self.session, cond, values)
            touched = {*changes, *(["status"] if new_status else []), *(["is_primary"] if make_primary else [])}
            await audit.record(self.session, actor_id=user.id, action="condition.update", resource="condition",
                               patient_id=pid, resource_id=cid, details=audit.fields(touched))
            await patients_repo.refresh_primary_dx_sort(self.session, pid)      # set primary, resolve, rename
            return cond, primary_cleared

    async def delete(self, pid: uuid.UUID, cid: uuid.UUID, user: User) -> None:
        from sqlalchemy import func
        async with self.session.begin():
            await self._lock(pid)
            cond = await repo.get(self.session, pid, cid)
            if cond is None:
                raise NotFound()
            # A deleted primary leaves the patient with none: the gap rule will show it (§13.3)
            await repo.apply(self.session, cond, {"deleted_at": func.now(), "is_primary": False, "updated_by": user.id})
            await audit.record(self.session, actor_id=user.id, action="condition.delete", resource="condition",
                               patient_id=pid, resource_id=cid)
            await patients_repo.refresh_primary_dx_sort(self.session, pid)

    # ---- used by the encounter finalize transaction (same transaction, lock already held) -------------
    async def link_or_create(self, *, patient_id: uuid.UUID, icd10: str | None, description: str,
                             category: str | None, onset: date, source_encounter_id: uuid.UUID,
                             user: User) -> tuple[uuid.UUID, str]:
        existing = await repo.active_and_resolved(self.session, patient_id)
        refs = {c.id: c for c in existing}
        decision = resolve_link(icd10, description,
                                [ConditionRef(c.id, c.icd10_code, c.description, c.status) for c in existing])
        if decision.kind == "linked":
            assert decision.condition is not None
            return decision.condition.id, "linked"
        if decision.kind == "reactivated":
            assert decision.condition is not None
            cond = refs[decision.condition.id]
            await repo.apply(self.session, cond, {"status": "active", "resolved_date": None, "updated_by": user.id})
            return cond.id, "reactivated"
        cond = await repo.insert(self.session, {
            "patient_id": patient_id, "icd10_code": icd10, "description": description,
            "category": category or infer_category(icd10), "is_primary": False, "status": "active",
            "onset_date": onset, "source_encounter_id": source_encounter_id,
            "created_by": user.id, "updated_by": user.id})
        return cond.id, "added"

    # ---- helpers -------------------------------------------------------------------------------
    async def _lock(self, pid: uuid.UUID) -> None:
        if await patients_repo.lock_active(self.session, pid) is None:
            raise NotFound()

    def _check_onset(self, onset: date | None) -> None:
        if onset is not None and onset > self.today():
            raise ValidationFailed([("onset_date", "Onset cannot be in the future.")])
