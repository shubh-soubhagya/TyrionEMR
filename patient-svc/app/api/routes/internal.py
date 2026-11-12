"""/internal/patients/** (LLD §12.2-12.5). Same JWT + clinician rule as the public routes (§17.2); the gateway
does not route /internal, so these are reachable only from inside the private network."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import InternalSvc
from app.core.security import Clinician

router = APIRouter(prefix="/internal/patients", tags=["internal"])


# NOTE: declared before the {pid} routes. "charts" is a literal segment, not a patient id.
@router.get("/charts")
async def bulk_charts(svc: InternalSvc, user: Clinician, cursor: uuid.UUID | None = None,
                      limit: Annotated[int, Query(ge=1, le=200)] = 200) -> dict:
    return await svc.bulk_charts(cursor, limit, user)


@router.get("/{pid}/basic")
async def basic(pid: uuid.UUID, svc: InternalSvc, _: Clinician) -> dict:
    return await svc.basic(pid)


@router.get("/{pid}/chart")
async def chart(pid: uuid.UUID, svc: InternalSvc, user: Clinician,
                encounters: Annotated[int, Query(ge=1, le=5)] = 2) -> dict:
    return await svc.chart(pid, encounters, user)


@router.get("/{pid}/conditions")
async def conditions(pid: uuid.UUID, svc: InternalSvc, user: Clinician,
                     status: Literal["active", "resolved"] | None = None) -> dict:
    return await svc.conditions(pid, status, user)


@router.get("/{pid}/medications-allergies")
async def medications_allergies(pid: uuid.UUID, svc: InternalSvc, user: Clinician) -> dict:
    return await svc.medications_allergies(pid, user)


@router.get("/{pid}/encounters")
async def encounters(pid: uuid.UUID, svc: InternalSvc, user: Clinician,
                     limit: Annotated[int, Query(ge=1, le=5)] = 5, include_notes: bool = False) -> dict:
    return await svc.encounters(pid, limit, include_notes, user)
