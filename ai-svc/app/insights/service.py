"""InsightsService (LLD B11): gaps for one patient, and the bulk snapshot behind the worklist and dashboard.

Insights never touch the database and never call the LLM, so they keep working when either is down (A7).
The snapshot holds names and MRNs in memory only; it is never persisted or logged (A6).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.clients.base import CallContext
from app.clients.lab import LabClient
from app.clients.models import ChartItem, StatusItem
from app.clients.patient import PatientClient
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import InsightsTooLarge
from app.core.metrics import INSIGHTS_CACHE, INSIGHTS_REFRESH
from app.insights.cache import SnapshotCache
from app.insights.hydrate import hydrate_all
from app.insights.rules.adapters import from_bulk, from_chart
from app.insights.rules.attention import attention
from app.insights.rules.constants import RULES_VERSION
from app.insights.rules.dashboard import Dashboard, PatientRow, attention_rows, build_dashboard
from app.insights.rules.facts import Attention, Finding, PatientFacts, RuleConfig
from app.insights.rules.gaps import evaluate

log = logging.getLogger("ai.insights")


async def gather_all[T](*coros: Awaitable[T]) -> list[T]:
    """Runs awaitables in parallel; the first failure cancels the rest and is re-raised as itself (not wrapped in
    an ExceptionGroup), so domain errors keep their HTTP mapping."""
    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(c) for c in coros]
    except ExceptionGroup as eg:      # a plain except: raising inside except* would re-wrap it in a group
        raise eg.exceptions[0] from None
    return [t.result() for t in tasks]


@dataclass(frozen=True)
class PatientGaps:
    patient_id: uuid.UUID
    as_of: date
    facts: PatientFacts
    findings: tuple[Finding, ...]
    evidence: tuple[tuple[dict, ...], ...]          # hydrated, parallel to findings
    attention: Attention | None


@dataclass(frozen=True)
class Snapshot:
    as_of: date
    generated_at: datetime
    rows: tuple[PatientRow, ...]


class InsightsService:
    def __init__(self, settings: Settings, clock: Clock, patients: PatientClient, labs: LabClient,
                 mono: Callable[[], float] = time.monotonic) -> None:
        self._s, self._clock, self._patients, self._labs = settings, clock, patients, labs
        self._tz = ZoneInfo(settings.clinic_tz)
        self._cache: SnapshotCache[Snapshot] = SnapshotCache(settings.insights_cache_ttl_s, mono)
        self._cfg = RuleConfig(no_recent_labs_days=settings.no_recent_labs_days,
                               egfr_discordance_tolerance=settings.egfr_discordance_tolerance,
                               no_stage_lt60_min_days=settings.no_stage_lt60_min_days)

    def today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    def _findings(self, facts: PatientFacts) -> tuple[Finding, ...]:
        return tuple(evaluate(facts, today=self.today(), now=self._clock(), tz=self._tz, cfg=self._cfg))

    # ---- B11.1 single patient -----------------------------------------------------------------
    async def gaps(self, patient_id: uuid.UUID, ctx: CallContext) -> PatientGaps:
        """The same three reads as summary step 2, in parallel. 404 from patient-svc -> PatientNotFound."""
        chart, latest, trends = await gather_all(
            self._patients.chart(patient_id, ctx), self._labs.latest(patient_id, ctx),
            self._labs.trends(patient_id, ctx))
        facts = from_chart(chart, latest, trends, today=self.today())
        findings = self._findings(facts)
        hydrated = hydrate_all(findings, chart, self._tz)
        return PatientGaps(patient_id, self.today(), facts, findings, tuple(tuple(h) for h in hydrated),
                           attention(facts, findings))

    # ---- B11.2 bulk path ----------------------------------------------------------------------
    async def snapshot(self, ctx: CallContext, *, force: bool = False) -> Snapshot:
        snap, outcome = await self._cache.get(lambda: self._compute(ctx), force=force)
        INSIGHTS_CACHE.labels(outcome).inc()
        return snap

    async def _pages[P](self, fetch: Callable[[uuid.UUID | None], Awaitable[P]]) -> list:
        """Keyset paging, at most INSIGHTS_MAX_PAGES pages (B11.2)."""
        items: list = []
        cursor: uuid.UUID | None = None
        for _ in range(self._s.insights_max_pages):
            page = await fetch(cursor)
            items.extend(page.items)  # type: ignore[attr-defined]
            cursor = page.next_cursor  # type: ignore[attr-defined]
            if cursor is None:
                return items
        raise InsightsTooLarge(self._s.insights_max_pages * self._s.insights_bulk_page)

    async def _compute(self, ctx: CallContext) -> Snapshot:
        started = time.perf_counter()
        limit = self._s.insights_bulk_page
        charts, statuses = await gather_all(
            self._pages(lambda c: self._patients.charts_page(c, limit, ctx)),
            self._pages(lambda c: self._labs.status_page(c, limit, ctx)))
        # lab rows for ids patient-svc no longer returns (soft-deleted) are ignored by the join
        by_patient: dict[uuid.UUID, StatusItem] = {s.patient_id: s for s in statuses}
        rows: list[PatientRow] = []
        for item in charts:
            assert isinstance(item, ChartItem)
            facts = from_bulk(item, by_patient.get(item.id))
            findings = self._findings(facts)
            rows.append(PatientRow(facts, item.mrn, f"{item.first_name} {item.last_name}", item.age, findings,
                                   attention(facts, findings)))
        elapsed = time.perf_counter() - started
        INSIGHTS_REFRESH.observe(elapsed)
        log.info("insights.snapshot", extra={
            "patients": len(rows), "pages": -(-len(charts) // limit) or 1, "latency_ms": round(elapsed * 1000),
            "need_attention": sum(1 for r in rows if r.attention is not None)})
        return Snapshot(self.today(), self._clock(), tuple(rows))

    def dashboard(self, snap: Snapshot) -> Dashboard:
        s = self._s
        return build_dashboard(snap.rows, attention_limit=s.dashboard_attention_limit,
                               per_patient=s.dashboard_abnormal_per_patient, total=s.dashboard_abnormal_total)

    @staticmethod
    def worklist(snap: Snapshot):
        return attention_rows(snap.rows)

    @property
    def rules_version(self) -> str:
        return RULES_VERSION
