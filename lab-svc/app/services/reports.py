"""Writes: create a report (one blood draw, one or more analytes) and append a correction.

Rules (HLD 4.3, ADR-009): values are stored canonical AND as entered; the reference range and flag are
snapshotted at write time; results are never updated; the read model is recomputed in the SAME transaction.
The patient-svc call happens BEFORE the transaction opens, so a slow upstream never holds a database lock.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.context import get_request_id
from app.core.errors import AlreadyCorrected, NotFound, ValidationFailed
from app.core.metrics import CORRECTIONS, REPORTS_CREATED, RESULTS_STORED, STATUS_REFRESH
from app.core.security import User
from app.domain.clock import Clock
from app.domain.flagging import age_on, flag_for, select_range
from app.domain.status import build_status
from app.domain.units import UnknownUnit, to_canonical
from app.models import LabReport, LabResult
from app.repositories.catalog import CatalogRepository
from app.repositories.labs import LabRepository
from app.schemas.reports import CorrectionIn, ReportIn, ReportOut, ResultOut
from app.services.patient_client import PatientBasic, PatientDirectory

FUTURE_TOLERANCE = timedelta(minutes=5)       # clock skew between the browser and the server; matches the DB CHECK


DEFAULT_LAB_NAME = "Unspecified laboratory"


def _snapshot(rng) -> dict:
    """The interpretation context frozen into a result: which range applied and its limits."""
    if rng is None:
        return {"range_id": None, "ref_low": None, "ref_high": None, "crit_low": None, "crit_high": None}
    return {"range_id": rng.range_id, "ref_low": rng.low, "ref_high": rng.high, "crit_low": rng.critical_low,
            "crit_high": rng.critical_high}


def result_out(r: LabResult) -> ResultOut:
    return ResultOut(
        id=r.id, report_id=r.report_id, patient_id=r.patient_id, test_code=r.test_code, collected_at=r.collected_at,
        value=float(r.value), unit=r.unit, value_original=float(r.value_original), unit_original=r.unit_original,
        ref_low=None if r.ref_low is None else float(r.ref_low),
        ref_high=None if r.ref_high is None else float(r.ref_high),
        crit_low=None if r.crit_low is None else float(r.crit_low),
        crit_high=None if r.crit_high is None else float(r.crit_high),
        flag=r.flag, supersedes_id=r.supersedes_id, correction_reason=r.correction_reason)


async def refresh_status(repo: LabRepository, patient_id: uuid.UUID) -> None:
    """Recomputes patient_lab_status from the effective results. Also used by the rebuild script."""
    start = time.perf_counter()
    await repo.flush()
    await repo.save_status(patient_id, build_status(await repo.effective_points(patient_id)))
    STATUS_REFRESH.observe(time.perf_counter() - start)


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock, patients: PatientDirectory) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock
        self._patients = patients
        self._repo = LabRepository(session)
        self._catalog = CatalogRepository(session)

    async def _interpret(self, patient: PatientBasic, collected_on, test_code: str, value: Decimal, unit: str,
                         field: str, tests: dict, ranges: list):
        """canonical value, snapshot (low, high) and flag for one analyte; raises ValidationFailed."""
        test = tests.get(test_code)
        if test is None:
            raise ValidationFailed([(f"{field}.test_code", f"Unknown test {test_code}.")])
        try:
            canon = to_canonical(value, unit, test.allowed_units, test.decimals)
        except UnknownUnit:
            allowed = ", ".join(test.allowed_units)
            raise ValidationFailed([(f"{field}.unit", f"Unit must be one of: {allowed}.")]) from None
        if canon > test.plausible_max:
            raise ValidationFailed([(f"{field}.value", f"Value is above the plausible limit for {test.name}.")])
        age = age_on(patient.date_of_birth, collected_on)
        rng = select_range(ranges, test_code, patient.sex, age, collected_on)
        return test, canon, rng, flag_for(canon, rng)

    def _check_date(self, collected_at, patient: PatientBasic) -> None:
        if collected_at > self._clock() + FUTURE_TOLERANCE:
            raise ValidationFailed([("collected_at", "Collection date cannot be in the future.")])
        if collected_at.date() < patient.date_of_birth:
            raise ValidationFailed([("collected_at", "Collection date is before the patient was born.")])

    async def create(self, patient_id: uuid.UUID, body: ReportIn, user: User, authorization: str) -> ReportOut:
        codes = [r.test_code for r in body.results]
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        if dupes:
            raise ValidationFailed([("results", f"Each test can appear once per report: {', '.join(dupes)}.")])
        patient = await self._patients.basic(patient_id, authorization, get_request_id())   # before the transaction
        self._check_date(body.collected_at, patient)
        now = self._clock()
        async with self._session.begin():
            await self._repo.lock_patient(patient_id)
            tests = {t.code: t for t in await self._catalog.tests()}
            ranges = await self._catalog.ranges()
            report = LabReport(id=uuid.uuid4(), patient_id=patient_id, collected_at=body.collected_at,
                               lab_name=body.lab_name or DEFAULT_LAB_NAME, notes=body.notes, entered_by=user.id,
                               request_id=None if get_request_id() == "-" else get_request_id(), created_at=now)
            rows: list[LabResult] = []
            issues: list[tuple[str, str]] = []
            for i, item in enumerate(body.results):
                try:
                    _, canon, rng, flag = await self._interpret(
                        patient, body.collected_at.date(), item.test_code, item.value, item.unit,
                        f"results[{i}]", tests, ranges)
                except ValidationFailed as exc:
                    issues += [(d["field"], d["issue"]) for d in exc.details]
                    continue
                rows.append(LabResult(
                    id=uuid.uuid4(), report_id=report.id, patient_id=patient_id, collected_at=body.collected_at,
                    test_code=item.test_code, value=canon, unit=tests[item.test_code].canonical_unit,
                    value_original=item.value, unit_original=item.unit,
                    **_snapshot(rng), flag=flag, entered_by=user.id, created_at=now))
            if issues:
                raise ValidationFailed(issues)          # nothing was written: the transaction rolls back
            self._repo.add(report)
            await self._repo.flush()                    # report row first: results reference it
            self._repo.add(*rows)
            await refresh_status(self._repo, patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.report.create", resource="lab_report",
                               patient_id=patient_id, resource_id=report.id,
                               details={"results": len(rows), "tests": sorted(codes)})
        REPORTS_CREATED.inc()
        for r in rows:
            RESULTS_STORED.labels(r.flag).inc()
        return ReportOut(id=report.id, patient_id=patient_id, collected_at=report.collected_at,
                         lab_name=report.lab_name, notes=report.notes, created_at=report.created_at,
                         results=[result_out(r) for r in rows])

    async def correct(self, result_id: uuid.UUID, body: CorrectionIn, user: User, authorization: str) -> ResultOut:
        async with self._session.begin():            # short read to learn the patient, then release
            original = await self._repo.get_result(result_id)
            if original is None:
                raise NotFound()
            patient_id = original.patient_id
        patient = await self._patients.basic(patient_id, authorization, get_request_id())
        now = self._clock()
        async with self._session.begin():
            await self._repo.lock_patient(patient_id)
            original = await self._repo.get_result(result_id)
            if original is None:
                raise NotFound()
            if await self._repo.is_superseded(result_id):
                raise AlreadyCorrected()
            tests = {t.code: t for t in await self._catalog.tests()}
            _, canon, rng, flag = await self._interpret(
                patient, original.collected_at.date(), original.test_code, body.value, body.unit, "value",
                tests, await self._catalog.ranges())
            corrected = LabResult(
                id=uuid.uuid4(), report_id=original.report_id, patient_id=patient_id,
                collected_at=original.collected_at, test_code=original.test_code, value=canon,
                unit=tests[original.test_code].canonical_unit, value_original=body.value, unit_original=body.unit,
                **_snapshot(rng), flag=flag, supersedes_id=original.id, correction_reason=body.reason.strip(),
                entered_by=user.id, created_at=now)
            self._repo.add(corrected)
            await refresh_status(self._repo, patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.result.correct", resource="lab_result",
                               patient_id=patient_id, resource_id=corrected.id,
                               details={"supersedes": str(original.id), "test": original.test_code})
        CORRECTIONS.inc()
        RESULTS_STORED.labels(flag).inc()
        return result_out(corrected)
