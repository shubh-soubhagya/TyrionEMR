"""/patients/{id}/conditions (LLD §11.5)."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response

from app.api.deps import ConditionSvc
from app.core.security import Clinician
from app.schemas.chart import ConditionCreate, ConditionList, ConditionOut, ConditionPatch, ConditionPatchResult

router = APIRouter(prefix="/patients/{pid}/conditions", tags=["conditions"])


@router.get("", response_model=ConditionList)
async def list_conditions(pid: uuid.UUID, svc: ConditionSvc, _: Clinician,
                          status: Literal["active", "resolved"] | None = None) -> dict:
    return {"items": await svc.list(pid, status)}


@router.post("", status_code=201, response_model=ConditionOut)
async def create_condition(pid: uuid.UUID, body: ConditionCreate, svc: ConditionSvc, user: Clinician,
                           response: Response):
    cond = await svc.create(pid, body, user)
    response.headers["Location"] = f"/patients/{pid}/conditions/{cond.id}"
    return cond


@router.patch("/{cid}", response_model=ConditionPatchResult)
async def patch_condition(pid: uuid.UUID, cid: uuid.UUID, body: ConditionPatch, svc: ConditionSvc, user: Clinician):
    cond, primary_cleared = await svc.patch(pid, cid, body, user)
    return {**ConditionOut.model_validate(cond).model_dump(), "primary_cleared": primary_cleared}


@router.delete("/{cid}", status_code=204)
async def delete_condition(pid: uuid.UUID, cid: uuid.UUID, svc: ConditionSvc, user: Clinician) -> Response:
    await svc.delete(pid, cid, user)
    return Response(status_code=204)
