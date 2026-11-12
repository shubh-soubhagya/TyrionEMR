"""Reads: results history, trends, latest, batch summary and the internal bulk status.

Every patient-scoped read is audited in the same short transaction as the read itself, so an unaudited chart
read cannot happen. The batch summary and the bulk export write one audit row per request, not per patient.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.security import User
from app.domain.ckd import EGFR_LABELS, UACR_LABELS
from app.domain.trends import Point, trend_stats
from app.domain.units import TestDef
from app.models import PatientLabStatus
from app.repositories.labs import LabRepository
from app.schemas.reads import (
    CategoryOut,
    LatestOut,
    ResultsPage,
    StatusItem,
    StatusPage,
    SummaryItem,
    SummaryOut,
    TrendPoint,
    TrendSeries,
    TrendsOut,
)
from app.services.catalog import CatalogCache
from app.services.reports import result_out

ALLOWED_FLAGS = frozenset({"abnormal", "normal", "low", "high", "critical_low", "critical_high", "unknown"})


def _f(v) -> float | None:
    return None if v is None else float(v)


class ReadService:
    def __init__(self, session: AsyncSession, settings: Settings, catalog: CatalogCache) -> None:
        self._session = session
        self._settings = settings
        self._repo = LabRepository(session)
        self._catalog = catalog

    async def results(self, patient_id: uuid.UUID, user: User, *, test: str | None, date_from: datetime | None,
                      date_to: datetime | None, flag: str | None, include_superseded: bool, page: int,
                      size: int) -> ResultsPage:
        if flag is not None and flag not in ALLOWED_FLAGS:
            raise ValidationFailed([("flag", f"Must be one of: {', '.join(sorted(ALLOWED_FLAGS))}.")])
        async with self._session.begin():
            if test is not None:
                await self._require_tests([test])
            rows, total = await self._repo.list_results(
                patient_id, test=test, date_from=date_from, date_to=date_to, flag=flag,
                include_superseded=include_superseded, offset=(page - 1) * size, limit=size)
            await audit.record(self._session, actor_id=user.id, action="lab.results.view", resource="lab_results",
                               patient_id=patient_id, details={"returned": len(rows)})
        return ResultsPage(items=[result_out(r) for r in rows], total=total, page=page, size=size)

    async def _require_tests(self, codes: Sequence[str]) -> Mapping[str, TestDef]:
        tests = (await self._catalog.get()).by_code
        unknown = [c for c in codes if c not in tests]
        if unknown:
            raise ValidationFailed([("tests", f"Unknown test: {', '.join(unknown)}.")])
        return tests

    async def trends(self, patient_id: uuid.UUID, user: User, tests: Sequence[str], date_from: datetime | None,
                     date_to: datetime | None) -> TrendsOut:
        async with self._session.begin():
            catalog = await self._require_tests(tests)
            rows = await self._repo.series(patient_id, tests, date_from, date_to)
            await audit.record(self._session, actor_id=user.id, action="lab.trends.view", resource="lab_results",
                               patient_id=patient_id, details={"tests": sorted(tests)})
        series: list[TrendSeries] = []
        for code in tests:                                  # keep the order the caller asked for
            mine = [r for r in rows if r.test_code == code]
            series.append(TrendSeries(
                test_code=code, unit=catalog[code].canonical_unit,
                points=[TrendPoint(collected_at=r.collected_at, value=float(r.value), flag=r.flag,
                                   ref_low=_f(r.ref_low), ref_high=_f(r.ref_high)) for r in mine],
                # stats describe THIS window, so the chips under a chart match what the chart shows
                stats=trend_stats(code, [Point(r.collected_at, r.value) for r in mine]).as_dict()))
        return TrendsOut(patient_id=patient_id, series=series)

    async def latest(self, patient_id: uuid.UUID, user: User) -> LatestOut:
        async with self._session.begin():
            st = await self._repo.status(patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.latest.view", resource="lab_status",
                               patient_id=patient_id)
        return self._latest(patient_id, st)

    @staticmethod
    def _latest(patient_id: uuid.UUID, st: PatientLabStatus | None) -> LatestOut:
        if st is None:       # nothing documented: empty, never a guessed value
            return LatestOut(patient_id=patient_id, latest={}, egfr_category=None, uacr_category=None,
                             has_critical=False, rapid_decline=False, last_result_at=None)
        return LatestOut(
            patient_id=patient_id, latest=st.latest,
            egfr_category=CategoryOut(code=st.egfr_category, label=EGFR_LABELS[st.egfr_category])
            if st.egfr_category else None,
            uacr_category=CategoryOut(code=st.uacr_category, label=UACR_LABELS[st.uacr_category])
            if st.uacr_category else None,
            has_critical=st.has_critical, rapid_decline=st.rapid_decline, last_result_at=st.last_result_at)

    async def summary(self, ids: Sequence[uuid.UUID], user: User) -> SummaryOut:
        if len(ids) > self._settings.summary_max_ids:
            raise ValidationFailed([("patient_ids", f"At most {self._settings.summary_max_ids} ids per request.")])
        async with self._session.begin():
            found = await self._repo.statuses(ids)        # ONE indexed read of the read model
            await audit.record(self._session, actor_id=user.id, action="lab.summary.view", resource="lab_status",
                               details={"patients": len(ids)})
        items = []
        for pid in ids:
            st = found.get(pid)
            items.append(SummaryItem(
                patient_id=pid, has_data=st is not None,
                latest_egfr=st.latest.get("EGFR") if st else None,
                egfr_category=st.egfr_category if st else None,
                egfr_spark=st.egfr_spark if st else [],
                has_critical=bool(st and st.has_critical), rapid_decline=bool(st and st.rapid_decline),
                last_result_at=st.last_result_at if st else None))
        return SummaryOut(items=items)

    async def status_page(self, cursor: uuid.UUID | None, limit: int, user: User) -> StatusPage:
        limit = min(limit, self._settings.internal_bulk_max_limit)
        async with self._session.begin():
            rows = await self._repo.status_page(cursor, limit)
            # one audit row per page, not per patient: a system-wide aggregate read
            await audit.record(self._session, actor_id=user.id, action="lab.status.bulk_export",
                               resource="lab_status", details={"returned": len(rows)})
        items = [StatusItem(patient_id=r.patient_id, latest=r.latest, egfr_category=r.egfr_category,
                            uacr_category=r.uacr_category, egfr_stats=r.egfr_stats, creat_stats=r.creat_stats,
                            has_critical=r.has_critical, rapid_decline=r.rapid_decline,
                            last_result_at=r.last_result_at) for r in rows]
        return StatusPage(items=items, next_cursor=rows[-1].patient_id if len(rows) == limit else None)
