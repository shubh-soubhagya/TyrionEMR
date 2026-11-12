"""ResilientClient (HLD §9, LLD B14): one policy for every upstream read.

connect 1 s, read 3 s (bulk 8 s), at most 2 retries with exponential backoff and jitter, only for connect errors
and 502/503/504 (a GET is idempotent), a bounded pool per upstream (bulkhead). The caller's JWT and X-Request-ID are
forwarded, so the upstream audits the real clinician. Failures map to the domain errors, naming the upstream.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from app.core.errors import UpstreamTimeout, UpstreamUnavailable
from app.core.metrics import UPSTREAM_CALLS

log = logging.getLogger("ai.http")
RETRY_STATUS = frozenset({502, 503, 504})


class UpstreamNotFound(Exception):
    """The upstream answered 404. Callers map it to PatientNotFound or similar."""


class ResilientClient:
    def __init__(self, name: str, base_url: str, *, connect_timeout_s: float, read_timeout_s: float,
                 bulk_read_timeout_s: float, retries: int, pool_size: int,
                 transport: httpx.AsyncBaseTransport | None = None, backoff_s: float = 0.1) -> None:
        self.name = name
        self._retries = retries
        self._backoff_s = backoff_s
        self._bulk_timeout = httpx.Timeout(bulk_read_timeout_s, connect=connect_timeout_s)
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport,
            timeout=httpx.Timeout(read_timeout_s, connect=connect_timeout_s),
            limits=httpx.Limits(max_connections=pool_size))          # bulkhead

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(self, path: str, *, authorization: str, request_id: str | None,
                       params: dict[str, Any] | None = None, bulk: bool = False) -> Any:
        headers = {"Authorization": authorization}
        if request_id and request_id != "-":
            headers["X-Request-ID"] = request_id
        extra: dict[str, Any] = {"timeout": self._bulk_timeout} if bulk else {}
        last = "error"
        for attempt in range(self._retries + 1):
            try:
                r = await self._http.get(path, headers=headers, params=params, **extra)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = "connect_timeout" if isinstance(exc, httpx.ConnectTimeout) else "connect_error"
            except httpx.TimeoutException:
                UPSTREAM_CALLS.labels(self.name, "timeout").inc()      # read/pool timeout: not retried
                raise UpstreamTimeout(self.name) from None
            except httpx.HTTPError:
                UPSTREAM_CALLS.labels(self.name, "error").inc()
                raise UpstreamUnavailable(self.name) from None
            else:
                if r.status_code == 200:
                    try:
                        body = r.json()
                    except ValueError:
                        UPSTREAM_CALLS.labels(self.name, "bad_response").inc()
                        raise UpstreamUnavailable(self.name) from None
                    UPSTREAM_CALLS.labels(self.name, "ok").inc()
                    return body
                if r.status_code == 404:
                    UPSTREAM_CALLS.labels(self.name, "not_found").inc()
                    raise UpstreamNotFound
                last = str(r.status_code)
                if r.status_code not in RETRY_STATUS:
                    # any other 4xx is a contract bug (B14): logged, answered as an upstream failure
                    log.error("upstream.unexpected_status", extra={"upstream": self.name, "status": r.status_code})
                    break
            if attempt < self._retries:
                UPSTREAM_CALLS.labels(self.name, "retry").inc()
                await asyncio.sleep(self._backoff_s * 2**attempt + random.uniform(0, self._backoff_s / 2))  # noqa: S311
        UPSTREAM_CALLS.labels(self.name, "timeout" if last == "connect_timeout" else "error").inc()
        log.warning("upstream.failed", extra={"upstream": self.name, "last": last})
        if last == "connect_timeout":
            raise UpstreamTimeout(self.name)
        raise UpstreamUnavailable(self.name)
