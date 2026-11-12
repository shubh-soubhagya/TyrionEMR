"""GET /encounters: cross-patient dashboard queries (LLD §12.1)."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import EncounterSvc
from app.core.security import Clinician
from app.schemas.encounter import DashboardList

router = APIRouter(prefix="/encounters", tags=["encounters"])


@router.get("", response_model=DashboardList)
async def dashboard(svc: EncounterSvc, _: Clinician,
                    status: Literal["draft"] | None = None,
                    upcoming_followups: bool = False,
                    limit: Annotated[int | None, Query(ge=1, le=100)] = None) -> dict:
    return await svc.dashboard(status=status, upcoming_followups=upcoming_followups, limit=limit)
