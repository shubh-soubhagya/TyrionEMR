"""Encounter use cases (LLD §13.4, §13.5, §14).

Every write: one transaction, patient row locked first, then the encounter row (global lock order, §16.1).
Finalize writes ``encounter_diagnoses.condition_id`` BEFORE flipping the status, because the children of a
final encounter are frozen by trigger (§9.3).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import EncounterFinal, NotFound, ValidationFailed, VersionConflict
from app.core.security import User
from app.domain import encounter_rules as rules
from app.domain.clock import Clock
from app.models import Encounter, Patient
from app.repositories import encounters as repo
from app.repositories import patients as patients_repo
from app.schemas.encounter import EncounterCreate, EncounterPatch
from app.services.conditions import ConditionService

DIAGNOSIS_FIELDS = ("icd10_code", "description", "category", "add_to_problem_list")


@dataclass
class ProblemListChanges:
    added: int = 0
    reactivated: int = 0
    linked: int = 0

    def count(self, kind: str) -> None:
        setattr(self, kind, getattr(self, kind) + 1)


@dataclass
class EncounterResult:
    encounter: Encounter
    problem_list_changes: ProblemListChanges = field(default_factory=ProblemListChanges)


def _fields(enc: Encounter | dict[str, Any]) -> rules.EncounterFields:
    get: Any = enc.get if isinstance(enc, dict) else lambda k: getattr(enc, k)
    return rules.EncounterFields(
        encounter_date=get("encounter_date"), chief_complaint=get("chief_complaint"),
        assessment=get("assessment"), plan=get("plan"), follow_up_date=get("follow_up_date"),
        symptoms=tuple(get("symptoms") or ()))


class EncounterService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self.session, self.settings, self.clock = session, settings, clock
        self.conditions = ConditionService(session, settings, clock)

    # ---- reads -------------------------------------------------------------------------------
    async def history(self, pid: uuid.UUID, status: str | None, page: int, size: int) -> dict[str, Any]:
        if not await patients_repo.exists(self.session, pid):
            raise NotFound()
        items, total = await repo.history(self.session, pid, status, page, size)
        return {"items": items, "page": page, "size": size, "total": total}

    async def get(self, pid: uuid.UUID, eid: uuid.UUID) -> Encounter:
        if not await patients_repo.exists(self.session, pid):
            raise NotFound()
        enc = await repo.get_detail(self.session, pid, eid)
        if enc is None:
            raise NotFound()
        return enc

    # ---- create ------------------------------------------------------------------------------
    async def create(self, pid: uuid.UUID, body: EncounterCreate, user: User) -> EncounterResult:
        async with self.session.begin():
            patient = await self._lock_patient(pid)
            values = {
                "encounter_date": body.encounter_date, "encounter_type": body.encounter_type,
                "chief_complaint": body.chief_complaint, "symptoms": list(body.symptoms),
                "examination_notes": body.examination_notes, "assessment": body.assessment, "plan": body.plan,
                "follow_up_date": body.follow_up_date}
            self._validate(values, patient, finalize=body.status == "final")
            enc = await repo.insert(self.session, {
                **values, "patient_id": pid, "status": "draft", "clinician_id": user.id,
                "clinician_name": user.name, "created_by": user.id, "updated_by": user.id})
            await repo.replace_vitals(self.session, enc.id, body.vitals.model_dump() if body.vitals else None)
            await repo.replace_diagnoses(self.session, enc.id, [d.model_dump() for d in body.diagnoses])
            changes = ProblemListChanges()
            if body.status == "final":
                changes = await self._finalize_in_tx(patient, enc.id, user)
            return await self._result(pid, enc.id, changes)

    # ---- edit a draft ------------------------------------------------------------------------
    async def patch(self, pid: uuid.UUID, eid: uuid.UUID, body: EncounterPatch, user: User) -> EncounterResult:
        sent = body.model_dump(exclude_unset=True, exclude={"version"})
        async with self.session.begin():
            patient = await self._lock_patient(pid)
            enc = await self._lock_draft(pid, eid, body.version)
            vitals_sent, dx_sent = "vitals" in sent, "diagnoses" in sent
            status = sent.pop("status", None)
            vitals = sent.pop("vitals", None)
            diagnoses = sent.pop("diagnoses", None)
            merged = {k: getattr(enc, k) for k in ("encounter_date", "chief_complaint", "assessment", "plan",
                                                   "follow_up_date", "symptoms")}
            merged.update(sent)                                   # merge the patch over the stored row
            self._validate(merged, patient, finalize=status == "final")
            await repo.update_fields(self.session, eid, {**sent, "updated_by": user.id})
            if vitals_sent:
                await repo.replace_vitals(self.session, eid, vitals)
            if dx_sent:
                await repo.replace_diagnoses(self.session, eid, diagnoses or [])
            changes = ProblemListChanges()
            if status == "final":
                changes = await self._finalize_in_tx(patient, eid, user)
            return await self._result(pid, eid, changes)

    async def finalize(self, pid: uuid.UUID, eid: uuid.UUID, version: int, user: User) -> EncounterResult:
        async with self.session.begin():
            patient = await self._lock_patient(pid)
            enc = await self._lock_draft(pid, eid, version)
            self._validate(_fields_dict(enc), patient, finalize=True)
            changes = await self._finalize_in_tx(patient, eid, user)
            return await self._result(pid, eid, changes)

    async def delete(self, pid: uuid.UUID, eid: uuid.UUID, user: User) -> None:
        async with self.session.begin():
            await self._lock_patient(pid)
            enc = await repo.lock_for_update(self.session, pid, eid)
            if enc is None:
                raise NotFound()
            if enc.status == "final":
                raise EncounterFinal("Final encounters cannot be deleted.")
            await repo.soft_delete(self.session, eid, user.id)

    # ---- internals ---------------------------------------------------------------------------
    async def _finalize_in_tx(self, patient: Patient, eid: uuid.UUID, user: User) -> ProblemListChanges:
        enc = await repo.lock_for_update(self.session, patient.id, eid)
        assert enc is not None                                   # caller holds the lock on this row
        issues = rules.validate_finalizable(_fields(enc))        # re-check on the stored state
        if issues:
            raise ValidationFailed(issues)
        changes = ProblemListChanges()
        visit_day = rules.to_clinic_date(enc.encounter_date, self.settings.clinic_tz)
        # 1. link diagnoses to the problem list FIRST (children are frozen once status = final)
        for dx in await repo.diagnoses_of(self.session, eid):
            if not dx.add_to_problem_list:
                continue
            cond_id, kind = await self.conditions.link_or_create(
                patient_id=patient.id, icd10=dx.icd10_code, description=dx.description, category=dx.category,
                onset=visit_day, source_encounter_id=eid, user=user)
            await repo.set_diagnosis_condition(self.session, dx.id, cond_id)
            changes.count(kind)
        # 2. then flip the status (an encounter never sets or changes the primary diagnosis)
        await repo.mark_final(self.session, eid, user.id)
        return changes

    async def _lock_patient(self, pid: uuid.UUID) -> Patient:
        patient = await patients_repo.lock_active(self.session, pid)
        if patient is None:
            raise NotFound()
        return patient

    async def _lock_draft(self, pid: uuid.UUID, eid: uuid.UUID, version: int) -> Encounter:
        enc = await repo.lock_for_update(self.session, pid, eid)
        if enc is None:
            raise NotFound()
        if enc.status == "final":                                # checked after the lock, so a racing finalize wins
            raise EncounterFinal()
        if enc.version != version:
            raise VersionConflict()
        return enc

    def _validate(self, values: dict[str, Any], patient: Patient, *, finalize: bool) -> None:
        fields = _fields(values)
        issues = rules.validate_common(fields, dob=patient.date_of_birth, now=self.clock(),
                                       tz_name=self.settings.clinic_tz)
        if finalize:
            issues += rules.validate_finalizable(fields)
        if issues:
            raise ValidationFailed(issues)

    async def _result(self, pid: uuid.UUID, eid: uuid.UUID, changes: ProblemListChanges) -> EncounterResult:
        enc = await repo.get_detail(self.session, pid, eid)
        assert enc is not None
        return EncounterResult(enc, changes)


def _fields_dict(enc: Encounter) -> dict[str, Any]:
    return {k: getattr(enc, k) for k in ("encounter_date", "chief_complaint", "assessment", "plan",
                                         "follow_up_date", "symptoms")}

