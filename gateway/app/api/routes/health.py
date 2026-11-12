"""Gateway-owned probes (LLD §27.1, §27.2). Outside /api, never forwarded."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.context import set_route
from app.core.errors import NotReady

router = APIRouter()


@router.get("/health", include_in_schema=False)
async def health(request: Request) -> dict[str, str]:
    """Liveness only: the process is up. No dependencies are checked."""
    set_route(request.scope, "/health")
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready(request: Request) -> dict[str, Any]:
    """Ready when the JWKS keyset is fresh and has a key, and every upstream in READY_REQUIRES is up.

    Only auth is required by default (ADR-G11): if lab-svc is down the patient screens still work, so the
    gateway must not take the whole API out of rotation.
    """
    set_route(request.scope, "/ready")
    state = request.app.state
    jwks, prober, required = state.jwks, state.prober, state.settings.ready_requires
    upstreams = prober.snapshot()

    failed: list[dict[str, str]] = []
    if not jwks.fresh or jwks.key_count < 1:
        failed.append({"check": "jwks", "status": "failed"})
    for name in required:
        if prober.state(name) != "up":
            failed.append({"check": f"upstream:{name}", "status": prober.state(name)})
    if failed:
        raise NotReady(details=failed)

    age = jwks.age_s()
    return {"status": "ready", "jwks": {"keys": jwks.key_count, "age_s": round(age, 1) if age is not None else None},
            "upstreams": upstreams}
