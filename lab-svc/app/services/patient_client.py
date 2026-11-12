"""patient-svc client (HLD 9): one read, only when creating a report or a correction.

Resilience policy: connect 1 s / read 3 s, max 2 retries with exponential backoff and jitter, only for
connect errors and 502/503/504 (a GET is idempotent). The caller's JWT and X-Request-ID are forwarded so the
audit trail shows who started the call. Failure maps to 502 UPSTREAM_UNAVAILABLE naming the upstream.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import NotFound, UpstreamUnavailable
from app.core.metrics import UPSTREAM_CALLS

log = logging.getLogger("lab.patients")
UPSTREAM = "patient-svc"
RETRY_STATUS = frozenset({502, 503, 504})


@dataclass(frozen=True, slots=True)
class PatientBasic:
    sex: str                 # "M" | "F" | "O"
    date_of_birth: date


class PatientDirectory(Protocol):
    async def basic(self, patient_id: uuid.UUID, authorization: str, request_id: str | None) -> PatientBasic: ...


class PatientClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._http = httpx.AsyncClient(
            base_url=settings.patient_svc_url, transport=transport,
            timeout=httpx.Timeout(settings.upstream_read_timeout_s, connect=settings.upstream_connect_timeout_s),
            limits=httpx.Limits(max_connections=20))        # bounded pool: a slow upstream cannot take all sockets

    async def aclose(self) -> None:
        await self._http.aclose()

    async def basic(self, patient_id: uuid.UUID, authorization: str, request_id: str | None) -> PatientBasic:
        headers = {"Authorization": authorization}
        if request_id and request_id != "-":
            headers["X-Request-ID"] = request_id
        last = "error"
        for attempt in range(self._s.upstream_max_retries + 1):
            try:
                r = await self._http.get(f"/internal/patients/{patient_id}/basic", headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                last = "connect_error"
            except httpx.HTTPError:
                UPSTREAM_CALLS.labels(UPSTREAM, "error").inc()        # read timeout etc.: not retried
                raise UpstreamUnavailable(UPSTREAM) from None
            else:
                if r.status_code == 200:
                    return self._parse(r)
                if r.status_code == 404:
                    UPSTREAM_CALLS.labels(UPSTREAM, "not_found").inc()
                    raise NotFound()
                last = str(r.status_code)
                if r.status_code not in RETRY_STATUS:
                    break
            if attempt < self._s.upstream_max_retries:
                await asyncio.sleep(0.1 * 2**attempt + random.uniform(0, 0.05))  # noqa: S311 (jitter only)
        UPSTREAM_CALLS.labels(UPSTREAM, "failed").inc()
        log.warning("patient_svc.failed", extra={"last": last})
        raise UpstreamUnavailable(UPSTREAM)

    @staticmethod
    def _parse(r: httpx.Response) -> PatientBasic:
        try:
            body = r.json()
            basic = PatientBasic(sex=str(body["sex"]), date_of_birth=date.fromisoformat(body["date_of_birth"]))
        except (ValueError, KeyError, TypeError):
            UPSTREAM_CALLS.labels(UPSTREAM, "bad_response").inc()
            raise UpstreamUnavailable(UPSTREAM) from None
        UPSTREAM_CALLS.labels(UPSTREAM, "ok").inc()
        return basic
