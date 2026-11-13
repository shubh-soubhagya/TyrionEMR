"""App factory and lifespan. CORS is NOT configured here: the gateway owns it."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from app.api import health as routes_health
from app.api import insights as routes_insights
from app.api import summary as routes_summary
from app.clients.lab import LabClient
from app.clients.patient import PatientClient
from app.core.clock import Clock, utcnow
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.dberrors import db_error_handler
from app.core.jwks import JwksCache, http_fetch
from app.core.logging import configure_logging
from app.core.metrics import mount_metrics
from app.db.session import create_engine, create_sessionmaker
from app.insights.service import InsightsService
from app.jobs import reaper
from app.jobs.runner import JobRunner
from app.llm.base import LLMProvider
from app.llm.factory import build_llm
from app.orchestrator.orchestrator import SummaryOrchestrator
from app.prompts.loader import load_prompts
from app.services.summary import SummaryService
from app.tools.definitions import Deps
from app.tools.registry import ToolRegistry


def build_state(app: FastAPI, settings: Settings, clock: Clock, jwks: JwksCache | None = None,
                patients: PatientClient | None = None, labs: LabClient | None = None,
                provider: LLMProvider | None = None, registry=None) -> None:
    """Creates everything the app needs. Separate from the lifespan so tests can call it directly."""
    app.state.settings = settings
    app.state.clock = clock
    app.state.jwks = jwks or JwksCache(http_fetch(settings), settings)
    app.state.patients = patients or PatientClient(settings)
    app.state.labs = labs or LabClient(settings)
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.insights = InsightsService(settings, clock, app.state.patients, app.state.labs)
    app.state.prompts = load_prompts(settings.prompt_version)      # a missing prompt file fails at startup
    app.state.llm = build_llm(settings, provider)
    registry = registry or ToolRegistry(settings, app.state.sessionmaker, Deps(app.state.patients, app.state.labs))
    orchestrator = SummaryOrchestrator(settings, app.state.sessionmaker, app.state.patients, app.state.labs,
                                       app.state.llm, app.state.prompts, clock, registry)
    app.state.runner = JobRunner(orchestrator, settings.llm_job_deadline_s)
    app.state.summaries = SummaryService(settings, app.state.sessionmaker, app.state.patients, app.state.runner,
                                         app.state.llm, app.state.prompts, clock, orchestrator.tools_enabled)


def _is_production(settings: Settings | None) -> bool:
    if settings is not None:
        return settings.app_env == "production"
    try:
        return get_settings().app_env == "production"
    except Exception:      # settings incomplete (e.g. exporting the OpenAPI schema without a database)
        return os.environ.get("APP_ENV") == "production"


def create_app(settings: Settings | None = None, clock: Clock = utcnow, jwks: JwksCache | None = None,
               patients: PatientClient | None = None, labs: LabClient | None = None,
               provider: LLMProvider | None = None, registry=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        configure_logging(s.service_name, s.log_level)
        build_state(app, s, clock, jwks, patients, labs, provider, registry)
        # Keep the key set fresh. A stub JWKS passed in by tests has no background refresh.
        refresher = asyncio.create_task(app.state.jwks.run_forever()) if jwks is None else None
        reaper_task = asyncio.create_task(
            reaper.run_forever(app.state.sessionmaker, s.llm_job_ttl_s, s.reaper_interval_s), name="reaper")
        try:
            yield
        finally:
            reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper_task
            await app.state.runner.shutdown()          # running jobs write failed JOB_ABORTED (5 s grace)
            closer = getattr(app.state.llm.provider, "aclose", None)
            if closer is not None:
                await closer()
            if refresher:
                refresher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher
            await app.state.patients.aclose()
            await app.state.labs.aclose()
            await app.state.engine.dispose()

    prod = _is_production(settings)
    app = FastAPI(
        title="ai-svc", version="1.0.0", lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
        redirect_slashes=False,      # a trailing slash is a 404, not a 307 round trip through the gateway (R14)
    )
    install_common_middleware(app)
    app.add_exception_handler(DBAPIError, db_error_handler)  # type: ignore[arg-type]
    app.include_router(routes_health.router)
    app.include_router(routes_insights.router)
    app.include_router(routes_summary.router)
    mount_metrics(app)
    logging.getLogger("ai").debug("app.created")
    return app


app = create_app()
