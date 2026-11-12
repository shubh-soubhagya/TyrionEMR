"""Gateway-owned probes (LLD section 27). /ready is added in Phase 7."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.context import set_route

router = APIRouter()


@router.get("/health", include_in_schema=False)
async def health(request: Request) -> dict[str, str]:
    """Liveness only: the process is up. No dependencies are checked."""
    set_route(request.scope, "/health")
    return {"status": "ok"}
