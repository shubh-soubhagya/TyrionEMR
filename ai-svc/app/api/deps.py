from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.context import CallContext, get_request_id
from app.core.errors import ValidationFailed
from app.insights.service import InsightsService
from app.services.summary import SummaryService


def get_insights(request: Request) -> InsightsService:
    return request.app.state.insights


def call_context(request: Request) -> CallContext:
    """The caller's own bearer token is forwarded upstream, so patient-svc audits the real clinician (A8)."""
    return CallContext(request.headers.get("authorization", ""), get_request_id())


def only_params(*allowed: str):
    """Rejects unknown query parameters with 422 (B12.1)."""

    def check(request: Request) -> None:
        unknown = sorted(set(request.query_params) - set(allowed))
        if unknown:
            raise ValidationFailed([(k, "Unknown query parameter.") for k in unknown])

    return check


def get_summaries(request: Request) -> SummaryService:
    return request.app.state.summaries


SummarySvc = Annotated[SummaryService, Depends(get_summaries)]
InsightsSvc = Annotated[InsightsService, Depends(get_insights)]
Ctx = Annotated[CallContext, Depends(call_context)]
