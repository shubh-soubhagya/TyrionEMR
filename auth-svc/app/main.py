"""App factory and lifespan (LLD §20.2). CORS is NOT configured here: the gateway owns it."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.api.cookies import clear_refresh_cookie
from app.api.routes import auth as routes_auth
from app.api.routes import health as routes_health
from app.api.routes import wellknown as routes_wellknown
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.dberrors import db_error_handler
from app.core.errors import AuthError, error_response
from app.core.guard import ConfigurationError, enforce_production
from app.core.logging import configure_logging
from app.core.metrics import bind_pool_gauges, mount_metrics
from app.core.ratelimit import TokenBucketLimiter
from app.db.migration_url import runtime_role_problem
from app.db.session import create_engine, create_sessionmaker
from app.domain.clock import Clock, utcnow
from app.domain.password_policy import load_common_passwords
from app.jobs.cleanup import run_cleanup_forever
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.keystore import KeyStore
from app.services.password_hasher import PasswordHasherService
from app.services.token_service import TokenService


def build_state(app: FastAPI, settings: Settings, clock: Clock, keystore: KeyStore | None = None) -> None:
    """Creates everything the app needs. Separate from the lifespan so tests can call it directly."""
    enforce_production(settings)               # refuses to start on an unsafe production config
    role_problem = runtime_role_problem(settings.auth_database_url)
    if role_problem:                           # production already refused above; elsewhere it is a warning
        logging.getLogger("auth").warning("config.runtime_role_not_least_privilege", extra={"detail": role_problem})
    app.state.settings = settings
    app.state.rate_limiter = TokenBucketLimiter(
        settings.rate_limit_login_per_min, settings.rate_limit_login_burst, clock)
    app.state.clock = clock
    app.state.keystore = keystore or KeyStore.from_files(
        settings.jwt_private_key_path, settings.jwt_additional_public_key_paths)   # fails fast if missing
    app.state.hasher = PasswordHasherService(settings)
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    bind_pool_gauges(app.state.engine.pool)
    tokens = TokenService(app.state.keystore, settings, clock)
    app.state.auth_service = AuthService(
        app.state.sessionmaker, UserRepository(), RefreshTokenRepository(), app.state.hasher, tokens,
        settings, load_common_passwords(), clock)


async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    resp = error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)
    if exc.clear_cookie:
        clear_refresh_cookie(resp, request.app.state.settings)   # RefreshRace deliberately does not clear
    return resp


def _peek(settings: Settings | None, name: str, default):
    """A setting needed while the app object is built, before the lifespan loads full settings. Falls back to
    the environment when settings are incomplete (e.g. exporting the OpenAPI schema without a database)."""
    if settings is not None:
        return getattr(settings, name)
    try:
        return getattr(get_settings(), name)
    except Exception:
        raw = os.environ.get(name.upper())
        if raw is None:
            return default
        return raw.lower() not in ("0", "false", "no") if isinstance(default, bool) else raw


def _is_production(settings: Settings | None) -> bool:
    return _peek(settings, "environment", "development") == "production"


def create_app(settings: Settings | None = None, clock: Clock = utcnow,
               keystore: KeyStore | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or get_settings()
        configure_logging(s.service_name, s.log_level)
        try:
            build_state(app, s, clock, keystore)
        except ConfigurationError as exc:
            logging.getLogger("auth").critical("startup.refused", extra={"problems": exc.problems})
            raise
        app.state.cleanup_task = asyncio.create_task(run_cleanup_forever(app.state.sessionmaker, s, clock))
        try:
            yield
        finally:
            app.state.cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app.state.cleanup_task          # let it finish unwinding before the pool closes
            await app.state.engine.dispose()

    prod = _is_production(settings)
    # No interactive docs or schema in production
    app = FastAPI(
        title="auth-svc", version="1.0.0", lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )
    install_common_middleware(app)
    app.add_exception_handler(AuthError, _auth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DBAPIError, db_error_handler)  # type: ignore[arg-type]
    app.include_router(routes_auth.router, prefix="/auth", tags=["auth"])
    app.include_router(routes_wellknown.router)
    app.include_router(routes_health.router)
    if _peek(settings, "metrics_enabled", True):
        mount_metrics(app)
    return app


def _default_app() -> FastAPI:
    return create_app()


app = _default_app()
