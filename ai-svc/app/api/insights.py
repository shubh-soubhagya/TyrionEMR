"""/insights/** (LLD B12.6-B12.8). Rule-engine output only: these routes never call the LLM (HLD 10.2)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import Ctx, InsightsSvc, only_params
from app.core.errors import ValidationFailed
from app.core.security import Clinician
from app.insights.rules.constants import RULES_VERSION
from app.schemas.insights import (
    AbnormalResultOut,
    AttentionOut,
    AttentionRowOut,
    DashboardOut,
    EvidenceOut,
    FindingOut,
    GapsOut,
    KpisOut,
    ReasonOut,
    WorklistItemOut,
    WorklistOut,
)

router = APIRouter(prefix="/insights", tags=["insights"])
NO_STORE = {"Cache-Control": "no-store"}


def _reasons(reasons) -> list[ReasonOut]:
    return [ReasonOut(severity=r.severity, code=r.code, text=r.text) for r in reasons]


def _wants_fresh(request: Request) -> bool:
    return "no-cache" in request.headers.get("cache-control", "").lower()


@router.get("/patients/{patient_id}/gaps", response_model=GapsOut, dependencies=[Depends(only_params())])
async def gaps(patient_id: uuid.UUID, svc: InsightsSvc, ctx: Ctx, _: Clinician, response: Response) -> GapsOut:
    result = await svc.gaps(patient_id, ctx)
    response.headers.update(NO_STORE)
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in result.findings:
        counts[f.severity] += 1
    att = result.attention
    return GapsOut(
        patient_id=patient_id, as_of=result.as_of, rules_version=RULES_VERSION, counts=counts,
        findings=[FindingOut(code=f.code, severity=f.severity, kind=f.kind, message=f.message,
                             evidence=[EvidenceOut(**e) for e in ev])
                  for f, ev in zip(result.findings, result.evidence, strict=True)],
        attention=AttentionOut(needs_attention=att is not None, reasons=_reasons(att.reasons) if att else []))


@router.get("/dashboard", response_model=DashboardOut, dependencies=[Depends(only_params())])
async def dashboard(request: Request, svc: InsightsSvc, ctx: Ctx, _: Clinician, response: Response) -> DashboardOut:
    snap = await svc.snapshot(ctx, force=_wants_fresh(request))
    d = svc.dashboard(snap)
    response.headers.update(NO_STORE)
    return DashboardOut(
        as_of=snap.as_of, generated_at=snap.generated_at, rules_version=RULES_VERSION, kpis=KpisOut(**d.kpis),
        attention=[AttentionRowOut(patient_id=r.patient_id, mrn=r.mrn, name=r.name, age=r.age,
                                   reasons=_reasons(r.reasons)) for r in d.attention],
        egfr_distribution=d.egfr_distribution,
        abnormal_results=[AbnormalResultOut(patient_id=a.patient_id, name=a.name, mrn=a.mrn, test=a.test,
                                            test_name=a.test_name, value=a.value, unit=a.unit, flag=a.flag,
                                            collected_at=a.collected_at, result_id=a.result_id)
                          for a in d.abnormal_results])


@router.get("/worklist", response_model=WorklistOut, dependencies=[Depends(only_params("attention"))])
async def worklist(request: Request, svc: InsightsSvc, ctx: Ctx, _: Clinician, response: Response,
                   attention: Annotated[bool, Query()] = True) -> WorklistOut:
    if not attention:
        raise ValidationFailed([("attention", "Only attention=true is supported.")])
    snap = await svc.snapshot(ctx, force=_wants_fresh(request))
    rows = svc.worklist(snap)
    response.headers.update(NO_STORE)
    return WorklistOut(as_of=snap.as_of, generated_at=snap.generated_at, total=len(rows),
                       items=[WorklistItemOut(patient_id=r.patient_id, rank=r.rank, reasons=_reasons(r.reasons))
                              for r in rows])
