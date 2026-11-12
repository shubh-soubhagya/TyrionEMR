"""SummaryService (LLD B10.2, B10.3): start, get, history. The only code that opens summary transactions besides
the orchestrator. The job itself runs in the background (JobRunner)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.patient import PatientClient
from app.core.clock import Clock
from app.core.config import Settings
from app.core.context import CallContext
from app.core.errors import AiQuotaExceeded, SummaryNotFound, TokenExpired
from app.core.metrics import AI_QUOTA_REJECTIONS
from app.core.security import User
from app.insights.rules.constants import RULES_VERSION
from app.jobs.runner import JobRunner
from app.llm.mock import SCENARIOS
from app.llm.resilience import ResilientLLM
from app.orchestrator.orchestrator import JobContext
from app.prompts.loader import PromptSet
from app.repositories import summaries as repo
from app.validation.output_schema import SCHEMA_VERSION

log = logging.getLogger("ai.summary")


@dataclass(frozen=True)
class Started:
    row: dict[str, Any]
    deduplicated: bool


class SummaryService:
    def __init__(self, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], patients: PatientClient,
                 runner: JobRunner, llm: ResilientLLM, prompts: PromptSet, clock: Clock, tools_enabled: bool) -> None:
        self.s, self._sm, self._patients, self._runner = settings, sessionmaker, patients, runner
        self._llm, self._prompts, self._clock, self._tools = llm, prompts, clock, tools_enabled
        self._tz = ZoneInfo(settings.clinic_tz)

    # ---- B10.2 ---------------------------------------------------------------------------------
    async def start(self, patient_id: uuid.UUID, user: User, ctx: CallContext, *, force: bool,
                    scenario: str | None) -> Started:
        now = self._clock()
        exp = float(user.raw["exp"])
        if exp - now.timestamp() < self.s.job_min_token_ttl_s:
            raise TokenExpired()                      # the interceptor refreshes and retries once
        await self._patients.basic(patient_id, ctx)   # existence: 404 / 502 / 504 with no row created

        day_start, day_end = self._clinic_day(now)
        async with self._sm() as session, session.begin():
            await repo.lock_user_quota(session, user.id)
            running = await repo.find_running(session, patient_id, user.id)
            if running is not None:                    # a duplicate POST joins the running job, no quota used
                return Started(dict(running), True)
            used = await repo.count_quota(session, user.id, day_start, day_end)
            if used >= self.s.ai_daily_quota_per_user:
                AI_QUOTA_REJECTIONS.inc()
                raise AiQuotaExceeded(self.s.ai_daily_quota_per_user, day_end.isoformat(),
                                      int((day_end - now).total_seconds()))
            row = await repo.insert_running(
                session, patient_id=patient_id, requested_by=user.id, request_id=ctx.request_id, force=force,
                provider=self._llm.name, model=self._llm.model, prompt_version=self._prompts.version,
                schema_version=SCHEMA_VERSION, rules_version=RULES_VERSION, tools_enabled=self._tools)
            if row is None:                            # lost a race with another POST: read the winner
                winner = await repo.find_running(session, patient_id, user.id)
                assert winner is not None
                return Started(dict(winner), True)
        job = JobContext(summary_id=row["id"], patient_id=patient_id, user_id=user.id,
                         authorization=ctx.authorization, request_id=ctx.request_id, force=force,
                         scenario=self._scenario(scenario))
        self._runner.start(job)
        log.info("summary.started", extra={"summary_id": str(row["id"]), "patient_id": str(patient_id),
                                           "deduplicated": False, "force": force, "provider": self._llm.name,
                                           "model": self._llm.model})
        return Started(dict(row), False)

    def _scenario(self, requested: str | None) -> str | None:
        """X-Mock-Scenario is honoured only with the mock provider in dev; anywhere else it is ignored."""
        if requested and self.s.app_env == "dev" and self._llm.name == "mock" and requested in SCENARIOS:
            return requested
        return None

    def _clinic_day(self, now: datetime) -> tuple[datetime, datetime]:
        local = now.astimezone(self._tz)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    # ---- reads ---------------------------------------------------------------------------------
    async def get(self, summary_id: uuid.UUID) -> tuple[dict[str, Any], dict[str, Any] | None]:
        async with self._sm() as session:
            row = await repo.get(session, summary_id)
            if row is None:
                raise SummaryNotFound(summary_id)
            original = await repo.get(session, row["cached_from"]) if row["cached_from"] else None
        return dict(row), dict(original) if original else None

    async def history(self, patient_id: uuid.UUID, page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        async with self._sm() as session:
            rows, total = await repo.history(session, patient_id, page, size)
        return [dict(r) for r in rows], total
