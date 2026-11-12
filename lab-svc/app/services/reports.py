"""Writes: create a report (one blood draw, one or more analytes) and append a correction (LLD B6.1, B6.2).

Rules (ADR-009): values are stored canonical AND as entered; the reference range and flag are snapshotted at
write time; results are never updated; the read model is recomputed in the SAME transaction.
The patient-svc call happens BEFORE the transaction opens (LAB-ADR-5), so a slow upstream never holds a database
lock. A correction does not call patient-svc at all: it reuses the snapshot of the result it corrects.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.context import get_request_id
from app.core.errors import (
    CollectedBeforeBirth,
    NoChange,
    Rejected,
    ResultAlreadySuperseded,
    ResultNotFound,
    problem,
)
from app.core.metrics import CORRECTIONS, RESULTS_CREATED, STATUS_RECOMPUTE
from app.core.security import User
from app.domain.clock import Clock
from app.domain.flagging import ABNORMAL_FLAGS, RangeDef, age_on, flag_for, select_range
from app.domain.status import build_status
from app.domain.trends import TrendConfig
from app.domain.units import TestDef, UnknownUnit, resolve_unit, to_canonical
from app.models import LabReport, LabResult
from app.repositories.labs import LabRepository
from app.schemas.reports import (
    CorrectedOut,
    Correction,
    CorrectionIn,
    CreatedReport,
    CreatedResult,
    CurrentResult,
    ReportIn,
    ReportOut,
    ReportSummary,
    ResultIn,
    ResultOut,
)
from app.services.catalog import CatalogCache
from app.services.patient_client import PatientBasic, PatientDirectory

log = logging.getLogger("lab.reports")
DEFAULT_LAB_NAME = "Unspecified laboratory"


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _snapshot(rng: RangeDef | None) -> dict:
    """The interpretation context frozen into a result: which range applied and its limits."""
    if rng is None:
        return {"range_id": None, "ref_low": None, "ref_high": None, "crit_low": None, "crit_high": None}
    return {"range_id": rng.range_id, "ref_low": rng.low, "ref_high": rng.high, "crit_low": rng.critical_low,
            "crit_high": rng.critical_high}


def _range_from_snapshot(r: LabResult) -> RangeDef | None:
    """The range a stored result was judged against, rebuilt from its own snapshot."""
    if r.range_id is None:
        return None
    return RangeDef(r.test_code, None, None, None, r.ref_low, r.ref_high, r.crit_low, r.crit_high,
                    r.collected_at.date(), r.range_id)


def result_out(r: LabResult) -> ResultOut:
    return ResultOut(
        id=r.id, report_id=r.report_id, patient_id=r.patient_id, test_code=r.test_code, collected_at=r.collected_at,
        value=float(r.value), unit=r.unit, value_original=float(r.value_original), unit_original=r.unit_original,
        ref_low=_f(r.ref_low), ref_high=_f(r.ref_high), crit_low=_f(r.crit_low), crit_high=_f(r.crit_high),
        flag=r.flag, supersedes_id=r.supersedes_id, correction_reason=r.correction_reason)


def created_result(r: LabResult) -> CreatedResult:
    return CreatedResult(
        id=r.id, test_code=r.test_code, value=float(r.value), unit=r.unit, value_original=float(r.value_original),
        unit_original=r.unit_original, ref_low=_f(r.ref_low), ref_high=_f(r.ref_high), crit_low=_f(r.crit_low),
        crit_high=_f(r.crit_high), flag=r.flag)


async def refresh_status(repo: LabRepository, patient_id: uuid.UUID, cfg: TrendConfig, spark_points: int) -> int:
    """Recomputes patient_lab_status from the current results and returns its new version. Also used by the
    rebuild script, so the incremental path and a full rebuild cannot disagree."""
    start = time.perf_counter()
    await repo.flush()
    version = await repo.save_status(patient_id, build_status(await repo.effective_points(patient_id), cfg,
                                                              spark_points))
    STATUS_RECOMPUTE.observe(time.perf_counter() - start)
    return version


Prepared = tuple[ResultIn, TestDef, str, Decimal]       # item, test, unit in the catalog spelling, canonical value


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock, patients: PatientDirectory,
                 catalog: CatalogCache) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock
        self._patients = patients
        self._repo = LabRepository(session)
        self._catalog = catalog

    def _refresh(self, patient_id: uuid.UUID):
        return refresh_status(self._repo, patient_id, self._settings.trend_config(), self._settings.spark_points)

    def _validate(self, body: ReportIn, tests: dict[str, TestDef]) -> list[Prepared]:
        """Steps 2-6 of B6.1: no I/O. Collects every problem so the form can mark each row."""
        problems: list[dict] = []
        if body.collected_at > self._clock() + timedelta(seconds=self._settings.clock_skew_s):
            problems.append(problem("COLLECTED_AT_IN_FUTURE", "collected_at",
                                    "Collection date cannot be in the future."))
        seen: set[str] = set()
        prepared: list[Prepared] = []
        for i, item in enumerate(body.results):
            field = f"results[{i}]"
            if item.test_code in seen:
                problems.append(problem("DUPLICATE_TEST_IN_REPORT", f"{field}.test_code",
                                        f"{item.test_code} appears more than once in this report."))
                continue
            seen.add(item.test_code)
            test = tests.get(item.test_code)
            if test is None:
                problems.append(problem("UNKNOWN_TEST", f"{field}.test_code", f"Unknown test {item.test_code}.",
                                        allowed=sorted(tests)))
                continue
            try:
                shown = resolve_unit(test, item.unit)
            except UnknownUnit as exc:
                problems.append(problem("UNKNOWN_UNIT", f"{field}.unit",
                                        f"Unit {item.unit!r} is not accepted for {test.name}.", allowed=exc.allowed))
                continue
            canon = to_canonical(test, item.value, shown)
            if canon > test.plausible_max:
                problems.append(problem("VALUE_IMPLAUSIBLE", f"{field}.value",
                                        "Check the value and unit: it is above the plausible limit.",
                                        max=float(test.plausible_max), unit=test.canonical_unit))
                continue
            prepared.append((item, test, shown, canon))
        if problems:
            raise Rejected(problems)
        return prepared

    async def create(self, patient_id: uuid.UUID, body: ReportIn, user: User, authorization: str) -> CreatedReport:
        cat = await self._catalog.get()                                  # in-process, no database round trip
        prepared = self._validate(body, dict(cat.by_code))               # steps 2-6
        patient = await self._patients.basic(patient_id, authorization, get_request_id())     # step 7, no transaction
        return await self._persist(patient_id, body, user, patient, prepared, cat)

    async def create_with_basic(self, patient_id: uuid.UUID, body: ReportIn, user: User,
                                patient: PatientBasic) -> CreatedReport:
        """The same code path as ``create`` minus the HTTP call: the seed already knows the patient's sex and date
        of birth, so flags, snapshots and the read model come from production code, not from seed SQL."""
        cat = await self._catalog.get()
        return await self._persist(patient_id, body, user, patient, self._validate(body, dict(cat.by_code)), cat)

    async def _persist(self, patient_id: uuid.UUID, body: ReportIn, user: User, patient: PatientBasic,
                       prepared: list[Prepared], cat) -> CreatedReport:
        collected_on = body.collected_at.date()
        if collected_on < patient.date_of_birth:                         # step 8
            raise CollectedBeforeBirth()
        age = age_on(patient.date_of_birth, collected_on)
        now = self._clock()
        rid = get_request_id()
        report = LabReport(id=uuid.uuid4(), patient_id=patient_id, collected_at=body.collected_at,
                           lab_name=body.lab_name or DEFAULT_LAB_NAME, notes=body.notes, entered_by=user.id,
                           request_id=None if rid == "-" else rid, created_at=now)
        rows: list[LabResult] = []
        for item, test, shown, canon in prepared:                        # step 9
            rng = select_range(cat.ranges, test.code, patient.sex, age, collected_on)
            rows.append(LabResult(
                id=uuid.uuid4(), report_id=report.id, patient_id=patient_id, collected_at=body.collected_at,
                test_code=test.code, value=canon, unit=test.canonical_unit, value_original=item.value,
                unit_original=shown, **_snapshot(rng), flag=flag_for(canon, rng), entered_by=user.id, created_at=now))
        async with self._session.begin():                                # step 10
            await self._repo.lock_patient(patient_id)
            self._repo.add(report)
            await self._repo.flush()                                     # the report row first: results reference it
            self._repo.add(*rows)
            await self._refresh(patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.report.create", resource="lab_report",
                               patient_id=patient_id, resource_id=report.id,
                               details={"results": len(rows), "tests": sorted(r.test_code for r in rows)})
        for r in rows:
            RESULTS_CREATED.labels(r.test_code, r.flag).inc()
        flags = [r.flag for r in rows]
        abnormal = sum(f in ABNORMAL_FLAGS for f in flags)
        critical = sum(f.startswith("critical") for f in flags)
        log.info("lab_report_created", extra={            # ids, counts and flags only: no values, names or notes
            "report_id": str(report.id), "patient_id": str(patient_id), "n": len(rows), "abnormal": abnormal,
            "critical": critical, "units_converted": sum(r.unit_original != r.unit for r in rows)})
        return CreatedReport(
            report=ReportOut(id=report.id, patient_id=patient_id, collected_at=report.collected_at.astimezone(UTC),
                             lab_name=report.lab_name, notes=report.notes, entered_by=user.id,
                             created_at=report.created_at),
            results=[created_result(r) for r in rows],
            summary=ReportSummary(n=len(rows), abnormal=abnormal, critical=critical))

    async def correct(self, result_id: uuid.UUID, body: CorrectionIn, user: User) -> Correction:
        cat = await self._catalog.get()
        now: datetime = self._clock()
        async with self._session.begin():
            target = await self._repo.get_result(result_id)              # 1: the base table
            if target is None:
                raise ResultNotFound(result_id)
            patient_id = target.patient_id
            await self._repo.lock_patient(patient_id)                    # serialises corrections of one patient
            if await self._repo.is_superseded(result_id):                # 2: must be current
                raise ResultAlreadySuperseded(await self._repo.chain_head(result_id))
            test = cat.by_code[target.test_code]
            try:                                                         # 3: unit, conversion, plausibility
                shown = resolve_unit(test, body.unit)
            except UnknownUnit as exc:
                raise Rejected([problem("UNKNOWN_UNIT", "unit", f"Unit {body.unit!r} is not accepted for {test.name}.",
                                        allowed=exc.allowed)]) from None
            canon = to_canonical(test, body.value, shown)
            if canon > test.plausible_max:
                raise Rejected([problem("VALUE_IMPLAUSIBLE", "value",
                                        "Check the value and unit: it is above the plausible limit.",
                                        max=float(test.plausible_max), unit=test.canonical_unit)])
            if canon == target.value:                                    # 4
                raise NoChange()
            # 5: judged against the target's own snapshot. The sample is the same, so the same range applies and
            # no patient-svc call is needed.
            rng = _range_from_snapshot(target)
            corrected = LabResult(
                id=uuid.uuid4(), report_id=target.report_id, patient_id=patient_id,
                collected_at=target.collected_at, test_code=target.test_code, value=canon,
                unit=test.canonical_unit, value_original=body.value, unit_original=shown,
                range_id=target.range_id, ref_low=target.ref_low, ref_high=target.ref_high,
                crit_low=target.crit_low, crit_high=target.crit_high, flag=flag_for(canon, rng),
                supersedes_id=target.id, correction_reason=body.reason.strip(), entered_by=user.id, created_at=now)
            self._repo.add(corrected)                                    # 6
            version = await self._refresh(patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.result.correct", resource="lab_result",
                               patient_id=patient_id, resource_id=corrected.id,
                               details={"supersedes": str(target.id), "test": target.test_code})
        CORRECTIONS.labels(corrected.test_code).inc()
        RESULTS_CREATED.labels(corrected.test_code, corrected.flag).inc()
        log.info("lab_result_corrected", extra={"result_id": str(corrected.id), "patient_id": str(patient_id),
                                                "test_code": corrected.test_code})
        return Correction(
            corrected=CorrectedOut(id=target.id, value=float(target.value), flag=target.flag),
            current=CurrentResult(
                id=corrected.id, supersedes_id=target.id, test_code=corrected.test_code, value=float(canon),
                unit=corrected.unit, value_original=float(body.value), unit_original=shown,
                ref_low=_f(corrected.ref_low), ref_high=_f(corrected.ref_high), crit_low=_f(corrected.crit_low),
                crit_high=_f(corrected.crit_high), flag=corrected.flag,
                correction_reason=corrected.correction_reason or ""),
            status_version=version)
