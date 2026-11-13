"""App factory (LLD §25.4). ``build_state`` is separate so tests can inject fake upstream transports,
a fake JWKS fetch and a fake clock.

Deviation D10: the state is built in ``create_app`` (not in the lifespan) because httpx's ASGITransport
never runs lifespan events. The lifespan only starts and stops the background tasks.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from app.api.routes import docs as routes_docs
from app.api.routes import gateway as routes_gateway
from app.api.routes import health as routes_health
from app.core.common_setup import install_common_middleware
from app.core.config import Settings, get_settings
from app.core.guard import enforce_production
from app.core.logging import configure_logging
from app.core.metrics import mount_metrics
from app.domain.clock import Clock, SystemClock
from app.routing.table import build_routes
from app.services.auth_gate import AuthGate
from app.services.health_prober import HealthProber
from app.services.jwks_cache import JwksCache
from app.services.pipeline import GatewayPipeline
from app.services.proxy import ProxyService
from app.services.rate_limiter import DisabledRateLimiter, InMemoryRateLimiter, RateLimiter
from app.services.upstreams import UpstreamRegistry

JwksFetch = Callable[[], Awaitable[Any]]


def build_state(app: FastAPI, s: Settings, clock: Clock,
                transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
                jwks_fetch: JwksFetch | None = None) -> None:
    app.state.settings = s
    app.state.clock = clock
    app.state.upstreams = UpstreamRegistry(s, transports)
    app.state.jwks_client = httpx.AsyncClient(timeout=s.jwks_fetch_timeout_s, trust_env=False,
                                              transport=(transports or {}).get("jwks"))

    async def _fetch() -> Any:
        resp = await app.state.jwks_client.get(s.jwks_url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()

    app.state.jwks = JwksCache(jwks_fetch or _fetch, s, clock)
    limiter: RateLimiter = InMemoryRateLimiter(clock, s.rl_max_keys) if s.rate_limit_enabled \
        else DisabledRateLimiter()
    app.state.limiter = limiter
    app.state.prober = HealthProber(app.state.upstreams, s)
    app.state.pipeline = GatewayPipeline(
        s, build_routes(s), app.state.upstreams, limiter,
        AuthGate(app.state.jwks, s, clock), ProxyService(app.state.upstreams,
                                                  allow_mock_scenario=s.environment != "production"))


def create_app(settings: Settings | None = None, *, clock: Clock | None = None,
               transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
               jwks_fetch: JwksFetch | None = None) -> FastAPI:
    s = settings or get_settings()        # all settings have defaults, so import never fails
    enforce_production(s)                 # refuse to start on an unsafe production configuration (D3)
    configure_logging(s.service_name, s.log_level)
    clk = clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(app.state.jwks.run_forever()),
                 asyncio.create_task(app.state.prober.run_forever())]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await app.state.upstreams.aclose()
            await app.state.jwks_client.aclose()

    # FastAPI's own docs are off: /docs is the gateway's aggregated page (§27.4), dev only.
    app = FastAPI(title="gateway", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    build_state(app, s, clk, transports, jwks_fetch)
    install_common_middleware(app, s)
    app.include_router(routes_health.router)
    if s.docs_enabled:
        app.include_router(routes_docs.router)
    if s.metrics_enabled:
        mount_metrics(app, s.metrics_token)
    app.include_router(routes_gateway.router)
    return app


app = create_app()
