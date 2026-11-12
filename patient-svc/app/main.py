"""App factory and lifespan (LLD §20, §22). CORS is NOT configured here: the gateway owns it."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from app.api.routes import allergies as routes_allergies
from app.api.routes import conditions as routes_conditions
from app.api.routes import encounter_queries as routes_encounter_queries
from app.api.routes import encounters as routes_encounters
from app.api.routes import health as routes_health
from app.api.routes import internal as routes_internal
from app.api.routes import medications as routes_medications
from app.api.routes import patients as routes_patients
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.dberrors import db_error_handler
from app.core.logging import configure_logging
from app.core.metrics import mount_metrics
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import Clock, utcnow
from app.services.clinician_directory import ClinicianDirectory, ClinicianNames
from app.services.jwks import JwksCache, http_fetch


def build_state(app: FastAPI, settings: Settings, clock: Clock, jwks: JwksCache | None = None,
                directory: ClinicianNames | None = None) -> None:
    """Creates everything the app needs. Separate from the lifespan so tests can call it directly."""
    app.state.settings = settings
    app.state.clock = clock
    app.state.jwks = jwks or JwksCache(http_fetch(settings), settings)
    app.state.clinician_directory = directory or ClinicianDirectory(settings)
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)


def _is_production(settings: Settings | None) -> bool:
    if settings is not None:
        return settings.environment == "production"
    try:
        return get_settings().environment == "production"
    except Exception:      # settings incomplete (e.g. exporting the OpenAPI schema without a database)
        return os.environ.get("ENVIRONMENT") == "production"


def create_app(settings: Settings | None = None, clock: Clock = utcnow, jwks: JwksCache | None = None,
               directory: ClinicianNames | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        configure_logging(s.service_name, s.log_level)
        build_state(app, s, clock, jwks, directory)
        # Keep the key set fresh. A stub JWKS passed in by tests has no background refresh.
        refresher = asyncio.create_task(app.state.jwks.run_forever()) if jwks is None else None
        try:
            yield
        finally:
            if refresher:
                refresher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher
            closer = getattr(app.state.clinician_directory, "aclose", None)
            if closer is not None:
                await closer()                      # closes the shared httpx client
            await app.state.engine.dispose()

    prod = _is_production(settings)
    # No interactive docs or schema in production
    app = FastAPI(
        title="patient-svc", version="1.0.0", lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )
    install_common_middleware(app)
    app.add_exception_handler(DBAPIError, db_error_handler)  # type: ignore[arg-type]
    app.include_router(routes_health.router)
    app.include_router(routes_patients.router)
    app.include_router(routes_conditions.router)
    app.include_router(routes_medications.router)
    app.include_router(routes_allergies.router)
    app.include_router(routes_encounters.router)
    app.include_router(routes_encounter_queries.router)
    app.include_router(routes_internal.router)
    mount_metrics(app)
    logging.getLogger("patient").debug("app.created")
    return app




def _default_app() -> FastAPI:
    return create_app()


app = _default_app()
