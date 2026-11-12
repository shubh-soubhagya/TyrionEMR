"""/ai/** (LLD B12.3-B12.5): start a summary job, poll it, list history."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import Ctx, SummarySvc, only_params
from app.core.security import Clinician
from app.schemas.summary import HistoryOut, StartOut, SummaryOut, render, render_progress

router = APIRouter(prefix="/ai", tags=["ai"])
NO_STORE = {"Cache-Control": "no-store"}
TERMINAL = ("completed", "degraded", "failed")


@router.post("/patients/{patient_id}/summary", response_model=StartOut, status_code=202,
             dependencies=[Depends(only_params("force"))])
async def start_summary(patient_id: uuid.UUID, svc: SummarySvc, ctx: Ctx, user: Clinician, response: Response,
                        force: bool = False,
                        x_mock_scenario: Annotated[str | None, Header()] = None) -> StartOut:
    started = await svc.start(patient_id, user, ctx, force=force, scenario=x_mock_scenario)
    row = started.row
    response.headers["Location"] = f"/ai/summaries/{row['id']}"
    response.headers.update(NO_STORE)
    return StartOut(summary_id=row["id"], patient_id=row["patient_id"], status=row["status"],
                    deduplicated=started.deduplicated, progress=render_progress(row))


@router.get("/summaries/{summary_id}", response_model=SummaryOut, dependencies=[Depends(only_params("include"))])
async def get_summary(summary_id: uuid.UUID, request: Request, svc: SummarySvc, _: Clinician,
                      include: Annotated[Literal["context"] | None, Query()] = None):
    row, original = await svc.get(summary_id)
    body = render(row, original, include_context=include == "context")
    if row["status"] not in TERMINAL:
        return JSONResponse(SummaryOut(**body).model_dump(mode="json"), headers=NO_STORE)
    etag = f'"{row["id"]}{"-ctx" if include else ""}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=3600, immutable"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    return JSONResponse(SummaryOut(**body).model_dump(mode="json"), headers=headers)


@router.get("/patients/{patient_id}/summaries", response_model=HistoryOut,
            dependencies=[Depends(only_params("page", "size"))])
async def history(patient_id: uuid.UUID, svc: SummarySvc, _: Clinician, response: Response,
                  page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=50)] = 10) -> HistoryOut:
    rows, total = await svc.history(patient_id, page, size)
    response.headers.update(NO_STORE)
    return HistoryOut(items=[SummaryOut(**render(r, progress=False)) for r in rows], page=page, size=size, total=total)
