"""/patients routes (LLD §11.2-11.3). Routers import services only, never repositories."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from pydantic import ValidationError

from app.api.deps import PatientSvc
from app.core.errors import ValidationFailed
from app.core.security import Clinician
from app.schemas.patient import ListQuery, PatientCreate, PatientDetail, PatientList, PatientPatch

router = APIRouter(prefix="/patients", tags=["patients"])


def _parse_ids(raw: str | None) -> list[uuid.UUID] | None:
    if raw is None:
        return None
    parts = [p for p in (x.strip() for x in raw.split(",")) if p]
    try:
        return [uuid.UUID(p) for p in parts]
    except ValueError as exc:
        raise ValidationFailed([("ids", "ids must be comma-separated UUIDs.")]) from exc


@router.get("", response_model=PatientList)
async def list_patients(
    svc: PatientSvc, _: Clinician,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sex: Literal["M", "F", "O"] | None = None,
    stage: Literal["G1", "G2", "G3a", "G3b", "G4", "G5", "none"] | None = None,
    ids: str | None = None,
    sort: Literal["name", "mrn", "age", "dx", "visit"] | None = None,   # egfr -> 422 (ADR-020)
    dir: Literal["asc", "desc"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    try:
        query = ListQuery(q=q, sex=sex, stage=stage, ids=_parse_ids(ids), sort=sort, dir=dir, page=page, size=size)
    except ValidationError as exc:
        raise ValidationFailed([(str(e["loc"][0]), e["msg"]) for e in exc.errors()]) from exc
    return await svc.list(query)


@router.post("", status_code=201, response_model=PatientDetail)
async def create_patient(body: PatientCreate, svc: PatientSvc, user: Clinician, response: Response) -> dict:
    detail = await svc.create(body, user)
    response.headers["Location"] = f"/patients/{detail['id']}"
    return detail


@router.get("/{pid}", response_model=PatientDetail)
async def get_patient(pid: uuid.UUID, svc: PatientSvc, _: Clinician) -> dict:
    return await svc.get(pid)


@router.patch("/{pid}", response_model=PatientDetail)
async def patch_patient(pid: uuid.UUID, body: PatientPatch, svc: PatientSvc, user: Clinician) -> dict:
    return await svc.update(pid, body, user)


@router.delete("/{pid}", status_code=204)
async def delete_patient(pid: uuid.UUID, svc: PatientSvc, user: Clinician) -> Response:
    await svc.delete(pid, user)
    return Response(status_code=204)
