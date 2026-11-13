"""App factory and lifespan. CORS is NOT configured here: the gateway owns it."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from app.api.routes import catalog as routes_catalog
from app.api.routes import health as routes_health
from app.api.routes import labs as routes_labs
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.dberrors import db_error_handler
from app.core.logging import configure_logging
from app.core.metrics import mount_metrics
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import Clock, utcnow
from app.services.catalog import CatalogCache
from app.services.jwks import JwksCache, http_fetch
from app.services.patient_client import PatientClient, PatientDirectory


def build_state(app: FastAPI, settings: Settings, clock: Clock, jwks: JwksCache | None = None,
                patients: PatientDirectory | None = None) -> None:
    """Creates everything the app needs. Separate from the lifespan so tests can call it directly."""
    app.state.settings = settings
    app.state.clock = clock
    app.state.jwks = jwks or JwksCache(http_fetch(settings), settings)
    app.state.patients = patients or PatientClient(settings)
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.catalog = CatalogCache(app.state.sessionmaker, settings.catalog_cache_ttl_s)


def _is_production(settings: Settings | None) -> bool:
    if settings is not None:
        return settings.environment == "production"
    try:
        return get_settings().environment == "production"
    except Exception:      # settings incomplete (e.g. exporting the OpenAPI schema without a database)
        return os.environ.get("ENVIRONMENT") == "production"


def create_app(settings: Settings | None = None, clock: Clock = utcnow, jwks: JwksCache | None = None,
               patients: PatientDirectory | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        configure_logging(s.service_name, s.log_level)
        build_state(app, s, clock, jwks, patients)
        try:
            await app.state.catalog.load()
        except Exception as exc:          # the database may still be starting: /ready says so, requests retry
            logging.getLogger("lab").warning("catalog.initial_load_failed", extra={"error_type": type(exc).__name__})
        # Keep the key set fresh. A stub JWKS passed in by tests has no background refresh.
        refresher = asyncio.create_task(app.state.jwks.run_forever()) if jwks is None else None
        try:
            yield
        finally:
            if refresher:
                refresher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher
            closer = getattr(app.state.patients, "aclose", None)
            if closer is not None:
                await closer()                      # closes the shared httpx client
            await app.state.engine.dispose()

    prod = _is_production(settings)
    # No interactive docs or schema in production
    app = FastAPI(
        title="lab-svc", version="1.0.0", lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
        redirect_slashes=False,      # a trailing slash is a 404, not a 307 round trip through the gateway (R14)
    )
    install_common_middleware(app)
    app.add_exception_handler(DBAPIError, db_error_handler)  # type: ignore[arg-type]
    app.include_router(routes_health.router)
    app.include_router(routes_catalog.router)
    app.include_router(routes_labs.router)
    app.include_router(routes_labs.internal)
    mount_metrics(app)
    logging.getLogger("lab").debug("app.created")
    return app


app = create_app()
