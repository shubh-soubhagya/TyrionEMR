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


def build_state(app: FastAPI, settings: Settings, clock: Clock, jwks: JwksCache | None = None,
                patients: PatientClient | None = None, labs: LabClient | None = None) -> None:
    """Creates everything the app needs. Separate from the lifespan so tests can call it directly."""
    app.state.settings = settings
    app.state.clock = clock
    app.state.jwks = jwks or JwksCache(http_fetch(settings), settings)
    app.state.patients = patients or PatientClient(settings)
    app.state.labs = labs or LabClient(settings)
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.insights = InsightsService(settings, clock, app.state.patients, app.state.labs)


def _is_production(settings: Settings | None) -> bool:
    if settings is not None:
        return settings.app_env == "production"
    try:
        return get_settings().app_env == "production"
    except Exception:      # settings incomplete (e.g. exporting the OpenAPI schema without a database)
        return os.environ.get("APP_ENV") == "production"


def create_app(settings: Settings | None = None, clock: Clock = utcnow, jwks: JwksCache | None = None,
               patients: PatientClient | None = None, labs: LabClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        configure_logging(s.service_name, s.log_level)
        build_state(app, s, clock, jwks, patients, labs)
        # Keep the key set fresh. A stub JWKS passed in by tests has no background refresh.
        refresher = asyncio.create_task(app.state.jwks.run_forever()) if jwks is None else None
        try:
            yield
        finally:
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
    )
    install_common_middleware(app)
    app.add_exception_handler(DBAPIError, db_error_handler)  # type: ignore[arg-type]
    app.include_router(routes_health.router)
    app.include_router(routes_insights.router)
    mount_metrics(app)
    logging.getLogger("ai").debug("app.created")
    return app


app = create_app()
