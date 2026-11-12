"""/patients/{id}/encounters (LLD §11.8)."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.api.deps import EncounterSvc
from app.core.security import Clinician
from app.schemas.encounter import (
    EncounterCreate,
    EncounterDetail,
    EncounterList,
    EncounterPatch,
    EncounterResult,
    FinalizeBody,
)
from app.services.encounters import EncounterResult as Result

router = APIRouter(prefix="/patients/{pid}/encounters", tags=["encounters"])


def _out(result: Result) -> dict:
    return {"encounter": result.encounter, "problem_list_changes": result.problem_list_changes}


@router.get("", response_model=EncounterList)
async def list_encounters(pid: uuid.UUID, svc: EncounterSvc, _: Clinician,
                          status: Literal["draft", "final"] | None = None,
                          page: Annotated[int, Query(ge=1)] = 1,
                          size: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
    return await svc.history(pid, status, page, size)


@router.post("", status_code=201, response_model=EncounterResult)
async def create_encounter(pid: uuid.UUID, body: EncounterCreate, svc: EncounterSvc, user: Clinician,
                           response: Response) -> dict:
    result = await svc.create(pid, body, user)
    response.headers["Location"] = f"/patients/{pid}/encounters/{result.encounter.id}"
    return _out(result)


@router.get("/{eid}", response_model=EncounterDetail)
async def get_encounter(pid: uuid.UUID, eid: uuid.UUID, svc: EncounterSvc, user: Clinician):
    return await svc.get(pid, eid, user)


@router.patch("/{eid}", response_model=EncounterResult)
async def patch_encounter(pid: uuid.UUID, eid: uuid.UUID, body: EncounterPatch, svc: EncounterSvc,
                          user: Clinician) -> dict:
    return _out(await svc.patch(pid, eid, body, user))


@router.post("/{eid}/finalize", response_model=EncounterResult)
async def finalize_encounter(pid: uuid.UUID, eid: uuid.UUID, body: FinalizeBody, svc: EncounterSvc,
                             user: Clinician) -> dict:
    return _out(await svc.finalize(pid, eid, body.version, user))


@router.delete("/{eid}", status_code=204)
async def delete_encounter(pid: uuid.UUID, eid: uuid.UUID, svc: EncounterSvc, user: Clinician) -> Response:
    await svc.delete(pid, eid, user)
    return Response(status_code=204)
