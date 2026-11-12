"""patient-svc internal reads (LLD B14). Read-only: ai-svc never writes to another service."""
from __future__ import annotations

import uuid

import httpx

from app.clients.base import CallContext, parse
from app.clients.models import Chart, ChartsPage, PatientBasic
from app.core.config import Settings
from app.core.errors import PatientNotFound, UpstreamUnavailable
from app.core.http import ResilientClient, UpstreamNotFound

UPSTREAM = "patient-svc"


class PatientClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = ResilientClient(
            UPSTREAM, settings.patient_svc_url, connect_timeout_s=settings.upstream_connect_timeout_s,
            read_timeout_s=settings.upstream_read_timeout_s, bulk_read_timeout_s=settings.upstream_bulk_read_timeout_s,
            retries=settings.upstream_retries, pool_size=settings.upstream_pool_size, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def basic(self, patient_id: uuid.UUID, ctx: CallContext) -> PatientBasic:
        return parse(PatientBasic, await self._get(f"/internal/patients/{patient_id}/basic", patient_id, ctx), UPSTREAM)

    async def chart(self, patient_id: uuid.UUID, ctx: CallContext, encounters: int = 2) -> Chart:
        body = await self._get(f"/internal/patients/{patient_id}/chart", patient_id, ctx,
                               params={"encounters": encounters})
        return parse(Chart, body, UPSTREAM)

    async def tool(self, patient_id: uuid.UUID, what: str, ctx: CallContext, params: dict | None = None) -> dict:
        """The tool endpoints: /conditions, /medications-allergies, /encounters. Returned as plain JSON; the tool
        layer whitelists and shapes it."""
        body = await self._get(f"/internal/patients/{patient_id}/{what}", patient_id, ctx, params=params)
        if not isinstance(body, dict):
            raise UpstreamUnavailable(UPSTREAM)
        return body

    async def charts_page(self, cursor: uuid.UUID | None, limit: int, ctx: CallContext) -> ChartsPage:
        params: dict = {"limit": limit}
        if cursor is not None:
            params["cursor"] = str(cursor)
        body = await self._http.get_json("/internal/patients/charts", authorization=ctx.authorization,
                                         request_id=ctx.request_id, params=params, bulk=True)
        return parse(ChartsPage, body, UPSTREAM)

    async def _get(self, path: str, patient_id: uuid.UUID, ctx: CallContext, params: dict | None = None):
        try:
            return await self._http.get_json(path, authorization=ctx.authorization, request_id=ctx.request_id,
                                             params=params)
        except UpstreamNotFound:
            raise PatientNotFound(patient_id) from None
