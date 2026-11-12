"""/patients/{id}/allergies (LLD §11.7)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import AllergySvc
from app.core.security import Clinician
from app.schemas.chart import AllergyCreate, AllergyCreated, AllergyList, AllergyRemoved

router = APIRouter(prefix="/patients/{pid}/allergies", tags=["allergies"])


@router.get("", response_model=AllergyList)
async def list_allergies(pid: uuid.UUID, svc: AllergySvc, _: Clinician) -> dict:
    return await svc.list(pid)


@router.post("", status_code=201, response_model=AllergyCreated)
async def create_allergy(pid: uuid.UUID, body: AllergyCreate, svc: AllergySvc, user: Clinician,
                         response: Response) -> dict:
    result = await svc.create(pid, body, user)
    response.headers["Location"] = f"/patients/{pid}/allergies/{result['allergy'].id}"
    return result


@router.delete("/{aid}", response_model=AllergyRemoved)
async def remove_allergy(pid: uuid.UUID, aid: uuid.UUID, svc: AllergySvc, user: Clinician) -> dict:
    return await svc.remove(pid, aid, user)
