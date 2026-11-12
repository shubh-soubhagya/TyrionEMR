"""/patients/{id}/medications (LLD §11.6)."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response

from app.api.deps import MedicationSvc
from app.core.security import Clinician
from app.schemas.chart import MedicationCreate, MedicationList, MedicationOut, MedicationPatch

router = APIRouter(prefix="/patients/{pid}/medications", tags=["medications"])


@router.get("", response_model=MedicationList)
async def list_medications(pid: uuid.UUID, svc: MedicationSvc, _: Clinician,
                           status: Literal["active", "all"] = "active") -> dict:
    return {"items": await svc.list(pid, include_all=status == "all")}


@router.post("", status_code=201, response_model=MedicationOut)
async def create_medication(pid: uuid.UUID, body: MedicationCreate, svc: MedicationSvc, user: Clinician,
                            response: Response):
    med = await svc.create(pid, body, user)
    response.headers["Location"] = f"/patients/{pid}/medications/{med.id}"
    return med


@router.patch("/{mid}", response_model=MedicationOut)
async def patch_medication(pid: uuid.UUID, mid: uuid.UUID, body: MedicationPatch, svc: MedicationSvc,
                           user: Clinician):
    return await svc.patch(pid, mid, body, user)
