"""lab-svc internal reads (LLD B14). Read-only."""
from __future__ import annotations

import uuid

import httpx

from app.clients.base import CallContext, parse
from app.clients.models import Latest, StatusPage, Trends
from app.core.config import Settings
from app.core.errors import UpstreamUnavailable
from app.core.http import ResilientClient, UpstreamNotFound

UPSTREAM = "lab-svc"


class LabClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = ResilientClient(
            UPSTREAM, settings.lab_svc_url, connect_timeout_s=settings.upstream_connect_timeout_s,
            read_timeout_s=settings.upstream_read_timeout_s, bulk_read_timeout_s=settings.upstream_bulk_read_timeout_s,
            retries=settings.upstream_retries, pool_size=settings.upstream_pool_size, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def latest(self, patient_id: uuid.UUID, ctx: CallContext) -> Latest:
        """A patient without results answers 200 with empty tiles; a 404 means the same for our purposes."""
        try:
            body = await self._http.get_json(f"/internal/labs/patients/{patient_id}/latest",
                                             authorization=ctx.authorization, request_id=ctx.request_id)
        except UpstreamNotFound:
            return Latest(patient_id=patient_id)
        return parse(Latest, body, UPSTREAM)

    async def results(self, patient_id: uuid.UUID, ctx: CallContext, *, test: str, date_from: str | None,
                      date_to: str | None, size: int) -> dict:
        params: dict = {"test": test, "size": size}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        try:
            body = await self._http.get_json(f"/internal/labs/patients/{patient_id}/results",
                                             authorization=ctx.authorization, request_id=ctx.request_id, params=params)
        except UpstreamNotFound:
            return {"items": [], "total": 0}
        if not isinstance(body, dict):
            raise UpstreamUnavailable(UPSTREAM)
        return body

    async def trends(self, patient_id: uuid.UUID, ctx: CallContext,
                     tests: tuple[str, ...] = ("CREAT", "EGFR")) -> Trends:
        try:
            body = await self._http.get_json(f"/internal/labs/patients/{patient_id}/trends",
                                             authorization=ctx.authorization, request_id=ctx.request_id,
                                             params={"tests": ",".join(tests)})
        except UpstreamNotFound:
            return Trends(patient_id=patient_id)
        return parse(Trends, body, UPSTREAM)

    async def status_page(self, cursor: uuid.UUID | None, limit: int, ctx: CallContext) -> StatusPage:
        params: dict = {"limit": limit}
        if cursor is not None:
            params["cursor"] = str(cursor)
        body = await self._http.get_json("/internal/labs/status", authorization=ctx.authorization,
                                         request_id=ctx.request_id, params=params, bulk=True)
        return parse(StatusPage, body, UPSTREAM)
