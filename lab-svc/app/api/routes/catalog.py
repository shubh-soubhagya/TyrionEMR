from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.errors import ValidationFailed
from app.core.security import Clinician
from app.schemas.catalog import CatalogOut
from app.services.catalog import CatalogService

router = APIRouter(prefix="/labs", tags=["catalog"])


def get_catalog_service(request: Request) -> CatalogService:
    return CatalogService(request.app.state.catalog, request.app.state.clock)


@router.get("/tests", response_model=CatalogOut)
async def list_tests(
    request: Request, response: Response, _: Clinician,
    svc: Annotated[CatalogService, Depends(get_catalog_service)],
    sex: Annotated[Literal["M", "F", "O"] | None, Query(description="Selects the range that applies")] = None,
    age: Annotated[int | None, Query(ge=0, le=130)] = None,
):
    """Catalog for the lab form preview: units with exact factors, plausibility limit and reference ranges.
    The server stays authoritative; this only lets the browser show the flag while typing."""
    if age is not None and sex is None:
        raise ValidationFailed([("age", "age needs sex: a range cannot be chosen from age alone.")])
    out, etag = await svc.view(sex, age)
    max_age = int(request.app.state.settings.catalog_cache_ttl_s)
    headers = {"ETag": etag, "Cache-Control": f"private, max-age={max_age}"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return out
