"""Public lab routes (LLD B7) and their internal twins for ai-svc (same handlers, /internal prefix)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import AuthHeader, ReadSvc, ReportSvc
from app.core.errors import InvalidCursor, Rejected, problem
from app.core.security import Clinician
from app.schemas.reads import InternalResultsPage, LatestOut, ResultsPage, StatusPage, SummaryOut, TrendsOut
from app.schemas.reports import Correction, CorrectionIn, CreatedReport, ReportIn

router = APIRouter(prefix="/labs", tags=["labs"])
internal = APIRouter(prefix="/internal/labs", tags=["internal"])


# ---- writes (public only) ---------------------------------------------------------------------------
@router.post("/patients/{patient_id}/reports", response_model=CreatedReport, status_code=201)
async def create_report(patient_id: uuid.UUID, body: ReportIn, svc: ReportSvc, user: Clinician,
                        auth: AuthHeader, response: Response) -> CreatedReport:
    out = await svc.create(patient_id, body, user, auth)
    response.headers["Location"] = f"/labs/patients/{patient_id}/results?report_id={out.report.id}"
    return out


@router.post("/results/{result_id}/correct", response_model=Correction, status_code=201)
async def correct_result(result_id: uuid.UUID, body: CorrectionIn, svc: ReportSvc, user: Clinician) -> Correction:
    """Appends a correction that supersedes the result. The original row is kept; no patient-svc call is made."""
    return await svc.correct(result_id, body, user)


# ---- reads (registered on both routers) -------------------------------------------------------------
def _split(value: str, field: str) -> list[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise Rejected([problem("VALIDATION_ERROR", field, "At least one value is required.")])
    return parts


@router.get("/patients/{patient_id}/results", response_model=ResultsPage)
async def results(
    patient_id: uuid.UUID, svc: ReadSvc, user: Clinician,
    test: Annotated[str | None, Query(max_length=16)] = None,
    date_from: Annotated[datetime | None, Query(alias="from", description="inclusive")] = None,
    date_to: Annotated[datetime | None, Query(alias="to", description="exclusive")] = None,
    flag: Annotated[str | None, Query(description="abnormal | critical | unknown | normal")] = None,
    report_id: uuid.UUID | None = None,
    include_superseded: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1)] = 10,
) -> ResultsPage:
    return await svc.results(patient_id, user, test=test, date_from=date_from, date_to=date_to, flag=flag,
                             report_id=report_id, include_superseded=include_superseded, page=page, size=size)


@internal.get("/patients/{patient_id}/results", response_model=InternalResultsPage)
async def internal_results(
    patient_id: uuid.UUID, svc: ReadSvc, user: Clinician,
    test: Annotated[str | None, Query(max_length=16)] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    flag: Annotated[str | None, Query()] = None,
    report_id: uuid.UUID | None = None,
    include_superseded: bool = False,
    limit: Annotated[int, Query(ge=1, le=50, description="AI tool results are capped (HLD 10.4)")] = 50,
) -> InternalResultsPage:
    page = await svc.results(patient_id, user, test=test, date_from=date_from, date_to=date_to, flag=flag,
                             report_id=report_id, include_superseded=include_superseded, page=1, size=limit)
    return InternalResultsPage(**page.model_dump(), truncated=page.total > len(page.items))


# trends and latest have the same handlers and contracts on both routers
for r in (router, internal):

    @r.get("/patients/{patient_id}/trends", response_model=TrendsOut, response_model_by_alias=True)
    async def trends(
        patient_id: uuid.UUID, svc: ReadSvc, user: Clinician,
        tests: Annotated[str, Query(description="Comma separated codes, e.g. CREAT,EGFR")] = "CREAT,EGFR",
        date_from: Annotated[datetime | None, Query(alias="from")] = None,
        date_to: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> TrendsOut:
        return await svc.trends(patient_id, user, _split(tests, "tests"), date_from, date_to)

    @r.get("/patients/{patient_id}/latest", response_model=LatestOut)
    async def latest(patient_id: uuid.UUID, svc: ReadSvc, user: Clinician, request: Request, response: Response):
        """Latest result per test plus the CKD block. ``ETag: W/"status-<version>"`` makes a re-poll cheap."""
        out = await svc.latest(patient_id, user)
        etag = f'W/"status-{out.status_version}"'
        if etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag
        return out


@router.get("/summary", response_model=SummaryOut)
async def summary(svc: ReadSvc, user: Clinician,
                  patient_ids: Annotated[str, Query(description="Comma separated ids, 1 to 50")]) -> SummaryOut:
    """Batch for list rows: latest eGFR, category, sparkline and attention flags. One entry per requested id, in
    request order; an id with no results has ``has_results: false``."""
    try:
        ids = list(dict.fromkeys(uuid.UUID(p) for p in _split(patient_ids, "patient_ids")))
    except ValueError:
        raise Rejected([problem("VALIDATION_ERROR", "patient_ids", "Every id must be a valid UUID.")]) from None
    return await svc.summary(ids, user)


@internal.get("/status", response_model=StatusPage)
async def status(svc: ReadSvc, user: Clinician, cursor: str | None = None,
                 limit: Annotated[int, Query(ge=1, le=200)] = 200) -> StatusPage:
    """Bulk read of the read model for the worklist and dashboard. Keyset paging: ``cursor`` is the
    ``next_cursor`` of the previous page (the last patient_id)."""
    try:
        after = uuid.UUID(cursor) if cursor else None
    except ValueError:
        raise InvalidCursor() from None
    return await svc.status_page(after, limit, user)
