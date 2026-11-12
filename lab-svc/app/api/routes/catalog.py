from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import SessionDep
from app.core.security import Clinician
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import CatalogOut
from app.services.catalog import CatalogService

router = APIRouter(prefix="/labs", tags=["catalog"])


def get_catalog_service(request: Request, session: SessionDep) -> CatalogService:
    return CatalogService(CatalogRepository(session), request.app.state.clock)


@router.get("/tests", response_model=CatalogOut)
async def list_tests(
    _: Clinician,
    svc: Annotated[CatalogService, Depends(get_catalog_service)],
    sex: Annotated[Literal["M", "F"] | None, Query(description="Selects sex-specific ranges")] = None,
) -> CatalogOut:
    """Test catalog: units, factors, plausibility limit and the reference range for ``sex`` (feeds the
    lab form preview). Without ``sex`` only sex-independent ranges are returned."""
    return await svc.get(sex)
