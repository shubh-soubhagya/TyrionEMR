"""Aggregated API docs (LLD §27.4, ADR-G14). Dev only: mounted when DOCS_ENABLED=true, refused in production.

``/docs`` is one Swagger UI with a dropdown of every configured service. Each spec is fetched from the
service over nephro-net and rewritten so ``servers`` is ``/api``: "Try it out" then goes through the real
gateway path (JWT check, rate limits), not around it. Swagger UI itself is loaded from the jsDelivr CDN, which
is acceptable for a developer-only page and keeps the gateway free of vendored front-end assets.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.context import set_route
from app.core.errors import NotFound, UpstreamNotDeployed, UpstreamUnavailable
from app.services.health_prober import UPSTREAMS

router = APIRouter()
FETCH_TIMEOUT_S = 2.0
CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>NephroCare API (via gateway)</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({
  dom_id: "#swagger-ui",
  urls: __URLS__,
  "urls.primaryName": __PRIMARY__,
  persistAuthorization: true
});
</script></body></html>"""


def _through_the_gateway(spec: dict[str, Any]) -> dict[str, Any]:
    """Point the spec at /api and add a Bearer scheme so Swagger's Authorize button appears."""
    spec = dict(spec)
    spec["servers"] = [{"url": "/api"}]
    components = dict(spec.get("components", {}))
    schemes = dict(components.get("securitySchemes", {}))
    schemes.setdefault("bearerAuth", {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"})
    components["securitySchemes"] = schemes
    spec["components"] = components
    spec.setdefault("security", [{"bearerAuth": []}])
    return spec


@router.get("/docs", include_in_schema=False)
async def docs(request: Request) -> HTMLResponse:
    set_route(request.scope, "/docs")
    registry = request.app.state.upstreams
    names = [n for n in UPSTREAMS if registry.configured(n)]
    urls = "[" + ",".join(f'{{"url":"/docs/{n}/openapi.json","name":"{n}-svc"}}' for n in names) + "]"
    primary = f'"{names[0]}-svc"' if names else '""'
    return HTMLResponse(_PAGE.replace("__URLS__", urls).replace("__PRIMARY__", primary))


@router.get("/docs/{upstream}/openapi.json", include_in_schema=False)
async def openapi(upstream: str, request: Request) -> JSONResponse:
    set_route(request.scope, "/docs/{upstream}/openapi.json")
    if upstream not in UPSTREAMS:
        raise NotFound()
    registry = request.app.state.upstreams
    if not registry.configured(upstream):
        raise UpstreamNotDeployed(upstream=upstream)
    now = request.app.state.clock.monotonic()
    cached = _cache.get(upstream)
    if cached and now - cached[0] < CACHE_TTL_S:
        return JSONResponse(cached[1])
    try:
        resp = await registry.client(upstream).get("/openapi.json", timeout=FETCH_TIMEOUT_S)
        resp.raise_for_status()
        spec = _through_the_gateway(resp.json())
    except (httpx.HTTPError, ValueError):
        # A service that is down, or runs with its schema off (production), fails alone; the others still load.
        raise UpstreamUnavailable(upstream=upstream) from None
    _cache[upstream] = (now, spec)
    return JSONResponse(spec)
