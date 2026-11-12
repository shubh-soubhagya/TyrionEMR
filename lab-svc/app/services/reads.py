"""Reads: results history, trends, latest, batch summary and the internal bulk status (LLD B6.4-B6.8).

Every patient-scoped read is audited in the same short transaction as the read itself, so an unaudited chart
read cannot happen. The batch summary and the bulk export write one audit row per request, not per patient.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import Settings
from app.core.errors import Rejected, TooManyIds, problem
from app.core.security import User
from app.domain.ckd import EGFR_LABELS, STAGE_BANDS, UACR_LABELS
from app.domain.trends import Point, trend_stats
from app.domain.units import TestDef
from app.models import PatientLabStatus
from app.repositories.labs import FLAG_GROUPS, LabRepository
from app.schemas.reads import (
    CkdBlock,
    HistoryItem,
    LatestEgfr,
    LatestOut,
    LatestResult,
    LatestTile,
    Reference,
    ResultsPage,
    StageBand,
    StatusItem,
    StatusPage,
    SummaryItem,
    SummaryOut,
    TrendPoint,
    TrendSeries,
    TrendsOut,
)
from app.services.catalog import CatalogCache


def _f(v) -> float | None:
    return None if v is None else float(v)


def _dt(v: str | None) -> datetime | None:
    return None if v is None else datetime.fromisoformat(v)


class ReadService:
    def __init__(self, session: AsyncSession, settings: Settings, catalog: CatalogCache) -> None:
        self._session = session
        self._settings = settings
        self._repo = LabRepository(session)
        self._catalog = catalog

    # ---- B6.4 history ---------------------------------------------------------------------------------
    async def results(self, patient_id: uuid.UUID, user: User, *, test: str | None, date_from: datetime | None,
                      date_to: datetime | None, flag: str | None, report_id: uuid.UUID | None,
                      include_superseded: bool, page: int, size: int) -> ResultsPage:
        if flag is not None and flag not in FLAG_GROUPS:
            raise Rejected([problem("VALIDATION_ERROR", "flag", f"Must be one of: {', '.join(FLAG_GROUPS)}.")])
        if size > self._settings.results_page_max:
            raise Rejected([problem("VALIDATION_ERROR", "size", f"At most {self._settings.results_page_max}.")])
        if test is not None:
            await self._require_tests([test], "test")
        async with self._session.begin():
            rows, total = await self._repo.list_results(
                patient_id, test=test, date_from=date_from, date_to=date_to, flag=flag, report_id=report_id,
                include_superseded=include_superseded, offset=(page - 1) * size, limit=size)
            await audit.record(self._session, actor_id=user.id, action="lab.results.view", resource="lab_results",
                               patient_id=patient_id, details={"returned": len(rows)})
        items = [HistoryItem(
            id=r.id, report_id=r.report_id, test_code=r.test_code, test_name=r.test_name,
            collected_at=r.collected_at, value=float(r.value), unit=r.unit, value_original=float(r.value_original),
            unit_original=r.unit_original, ref_low=_f(r.ref_low), ref_high=_f(r.ref_high), flag=r.flag,
            lab_name=r.lab_name, is_correction=r.supersedes_id is not None, superseded=bool(r.superseded))
            for r in rows]
        return ResultsPage(items=items, page=page, size=size, total=total)

    async def _require_tests(self, codes: Sequence[str], field: str) -> Mapping[str, TestDef]:
        tests = (await self._catalog.get()).by_code
        unknown = [c for c in codes if c not in tests]
        if unknown:
            raise Rejected([problem("UNKNOWN_TEST", field, f"Unknown test: {', '.join(unknown)}.",
                                    allowed=sorted(tests))])
        return tests

    # ---- B6.5 trends ----------------------------------------------------------------------------------
    async def trends(self, patient_id: uuid.UUID, user: User, tests: Sequence[str], date_from: datetime | None,
                     date_to: datetime | None) -> TrendsOut:
        catalog = await self._require_tests(tests, "tests")
        async with self._session.begin():
            rows = await self._repo.series(patient_id, tests, date_from, date_to)
            await audit.record(self._session, actor_id=user.id, action="lab.trends.view", resource="lab_results",
                               patient_id=patient_id, details={"tests": sorted(tests)})
        cfg = self._settings.trend_config()
        series: list[TrendSeries] = []
        for code in tests:                                  # keep the order the caller asked for
            mine = [r for r in rows if r.test_code == code]
            latest = mine[-1] if mine else None
            series.append(TrendSeries(
                test_code=code, unit=catalog[code].canonical_unit,
                points=[TrendPoint(result_id=r.id, collected_at=r.collected_at, value=float(r.value), flag=r.flag)
                        for r in mine],
                # stats describe THIS window, so the chips under a chart match what the chart shows
                stats=trend_stats(code, [Point(r.collected_at, r.value) for r in mine], cfg).as_dict(),
                # the band comes from the snapshot of the latest point, so the creatinine chart shows the patient's
                # own sex-specific range without asking patient-svc
                reference=None if latest is None else Reference(low=_f(latest.ref_low), high=_f(latest.ref_high)),
                stage_bands=[StageBand(code=str(b["code"]), lower=int(b["lower"])) for b in STAGE_BANDS]
                if code == "EGFR" else None))
        return TrendsOut.model_validate({"patient_id": patient_id, "from": date_from, "to": date_to, "series": series})

    # ---- B6.6 latest ----------------------------------------------------------------------------------
    async def latest(self, patient_id: uuid.UUID, user: User) -> LatestOut:
        cat = await self._catalog.get()
        async with self._session.begin():
            st = await self._repo.status(patient_id)
            await audit.record(self._session, actor_id=user.id, action="lab.latest.view", resource="lab_status",
                               patient_id=patient_id)
        return self.latest_from(patient_id, st, cat.tests)

    @staticmethod
    def latest_from(patient_id: uuid.UUID, st: PatientLabStatus | None, tests: Sequence[TestDef]) -> LatestOut:
        latest: dict[str, Any] = st.latest if st else {}
        tiles = []
        for t in tests:
            e = latest.get(t.code)
            result = None if e is None else LatestResult(
                result_id=e["result_id"], report_id=e["report_id"], value=e["value"], flag=e["flag"],
                collected_at=e["collected_at"], ref_low=e.get("ref_low"), ref_high=e.get("ref_high"))
            tiles.append(LatestTile(test_code=t.code, name=t.name, canonical_unit=t.canonical_unit, result=result))
        egfr, uacr = latest.get("EGFR"), latest.get("UACR")
        cat_e, cat_u = (st.egfr_category if st else None), (st.uacr_category if st else None)
        ckd = CkdBlock(
            egfr_category=cat_e, egfr_label=EGFR_LABELS[cat_e] if cat_e else None,
            egfr_value=egfr["value"] if egfr else None, egfr_collected_at=_dt(egfr["collected_at"]) if egfr else None,
            uacr_category=cat_u, uacr_label=UACR_LABELS[cat_u] if cat_u else None,
            uacr_value=uacr["value"] if uacr else None, uacr_collected_at=_dt(uacr["collected_at"]) if uacr else None)
        return LatestOut(patient_id=patient_id, tests=tiles, ckd=ckd, has_critical=bool(st and st.has_critical),
                         rapid_decline=bool(st and st.rapid_decline), last_result_at=st.last_result_at if st else None,
                         status_version=st.version if st else 0)

    # ---- B6.7 batch summary ---------------------------------------------------------------------------
    async def summary(self, ids: Sequence[uuid.UUID], user: User) -> SummaryOut:
        if len(ids) > self._settings.summary_max_ids:
            raise TooManyIds(self._settings.summary_max_ids)
        async with self._session.begin():
            found = await self._repo.statuses(ids)        # ONE indexed read of the read model
            await audit.record(self._session, actor_id=user.id, action="lab.summary.view", resource="lab_status",
                               details={"patients": len(ids)})
        items = []
        for pid in ids:                                    # one entry per requested id, in request order
            st = found.get(pid)
            egfr = st.latest.get("EGFR") if st else None
            items.append(SummaryItem(
                patient_id=pid, has_results=st is not None,
                latest_egfr=None if egfr is None else LatestEgfr(value=egfr["value"], flag=egfr["flag"],
                                                                   collected_at=egfr["collected_at"]),
                egfr_category=st.egfr_category if st else None,
                egfr_direction=(st.egfr_stats or {}).get("direction") if st else None,
                spark=st.egfr_spark if st else [],
                has_critical=bool(st and st.has_critical), rapid_decline=bool(st and st.rapid_decline),
                last_result_at=st.last_result_at if st else None))
        return SummaryOut(items=items)

    # ---- B6.8 bulk status -----------------------------------------------------------------------------
    async def status_page(self, cursor: uuid.UUID | None, limit: int, user: User) -> StatusPage:
        limit = min(limit, self._settings.status_bulk_max)
        async with self._session.begin():
            rows = await self._repo.status_page(cursor, limit)
            # one audit row per page, not per patient: a system-wide aggregate read
            await audit.record(self._session, actor_id=user.id, action="lab.status.bulk_export",
                               resource="lab_status", details={"returned": len(rows)})
        items = [StatusItem(patient_id=r.patient_id, latest=r.latest, egfr_category=r.egfr_category,
                            uacr_category=r.uacr_category, egfr_stats=r.egfr_stats, creat_stats=r.creat_stats,
                            has_critical=r.has_critical, rapid_decline=r.rapid_decline, result_count=r.result_count,
                            last_result_at=r.last_result_at) for r in rows]
        return StatusPage(items=items, next_cursor=rows[-1].patient_id if len(rows) == limit else None)
