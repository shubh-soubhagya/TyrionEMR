"""Forward a request upstream and relay the response (LLD §23).

Request bodies are buffered (bounded, ADR-G3) so httpx sends an exact Content-Length; responses are
streamed. Non-JSON upstream errors are wrapped in the envelope (ADR-G13, deviation D5).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.core.context import get_request_id
from app.core.errors import (
    GatewayBusy,
    UpstreamError,
    UpstreamTimeout,
    UpstreamUnavailable,
    error_response,
    status_code_name,
)
from app.core.metrics import UPSTREAM_DURATION, UPSTREAM_ERRORS
from app.routing.resolver import RouteMatch
from app.services.headers import filter_response_headers, upstream_request_headers
from app.services.upstreams import UpstreamRegistry

log = logging.getLogger("gateway.proxy")
_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout)    # the request never reached the upstream


class ProxyService:
    def __init__(self, registry: UpstreamRegistry) -> None:
        self._reg = registry

    async def forward(self, request: Request, match: RouteMatch, body: bytes, client_ip: str) -> Response:
        name = match.route.upstream
        client = self._reg.client(name)
        request.state.upstream = name
        # D6: path and query go to httpx as the client's own raw bytes (proved byte for byte by
        # tests/api/test_url_passthrough.py). The query is passed only when present: httpx.URL(query=b"")
        # would append a stray "?" to every request without one.
        query = request.scope.get("query_string", b"")
        url = httpx.URL(path=match.upstream_path, query=query) if query else httpx.URL(path=match.upstream_path)
        upstream_req = client.build_request(
            request.method,
            url,
            headers=upstream_request_headers(request.headers, client_ip=client_ip, request_id=get_request_id(),
                                             scheme=request.url.scheme,
                                             forward_cookies=match.route.forward_cookies),
            content=body or None,
            # per-route idle read timeout; connect and pool limits come from the client defaults
            timeout=httpx.Timeout(connect=client.timeout.connect, read=match.route.timeout_s,
                                  write=5.0, pool=client.timeout.pool),
        )

        # One retry, GET only, and only when the connection could not be established (ADR-G9)
        attempts = 2 if request.method == "GET" else 1
        started = time.perf_counter()
        for attempt in range(1, attempts + 1):
            try:
                async with asyncio.timeout(match.route.timeout_s):           # time to response headers
                    upstream = await client.send(upstream_req, stream=True)
                break
            except _RETRYABLE:
                if attempt < attempts:
                    await asyncio.sleep(0.05 + random.random() * 0.05)
                    continue
                UPSTREAM_ERRORS.labels(upstream=name, kind="connect").inc()
                log.warning("gateway.upstream.error", extra={"upstream": name, "kind": "connect"})
                raise UpstreamUnavailable(upstream=name) from None
            except httpx.PoolTimeout:
                UPSTREAM_ERRORS.labels(upstream=name, kind="pool").inc()
                log.warning("gateway.upstream.error", extra={"upstream": name, "kind": "pool"})
                raise GatewayBusy(upstream=name) from None
            except (TimeoutError, httpx.TimeoutException):
                UPSTREAM_ERRORS.labels(upstream=name, kind="timeout").inc()
                log.warning("gateway.upstream.error", extra={"upstream": name, "kind": "timeout"})
                raise UpstreamTimeout(upstream=name) from None
            except httpx.TransportError:
                UPSTREAM_ERRORS.labels(upstream=name, kind="transport").inc()
                log.warning("gateway.upstream.error", extra={"upstream": name, "kind": "transport"})
                raise UpstreamUnavailable(upstream=name) from None

        elapsed = time.perf_counter() - started
        UPSTREAM_DURATION.labels(upstream=name).observe(elapsed)
        request.state.upstream_status = upstream.status_code
        request.state.upstream_ms = round(elapsed * 1000, 1)
        return await self._relay(upstream, match)

    async def _relay(self, upstream: httpx.Response, match: RouteMatch) -> Response:
        name = match.route.upstream
        headers = filter_response_headers(upstream.headers.multi_items(),
                                          pass_set_cookie=match.route.pass_set_cookie,
                                          upstream_base=self._reg.base_url(name))
        ctype = upstream.headers.get("content-type", "")

        # ADR-G13: services' JSON (including their error envelopes) passes through untouched;
        # a non-JSON error (framework plain text, HTML) is wrapped so the envelope guarantee holds.
        if upstream.status_code >= 400 and not ctype.startswith("application/json"):
            await upstream.aread()
            await upstream.aclose()
            UPSTREAM_ERRORS.labels(upstream=name, kind="non_json").inc()
            log.warning("gateway.upstream.non_json_error", extra={"upstream": name, "status": upstream.status_code})
            return _wrap_non_json_error(name, upstream.status_code)

        if upstream.status_code in (204, 304):
            await upstream.aclose()
            resp = Response(status_code=upstream.status_code)
            resp.raw_headers = [h for h in headers if h[0] != b"content-length"]
            return resp

        resp = StreamingResponse(_body(upstream, name), status_code=upstream.status_code)
        resp.raw_headers = headers           # replaces Starlette's defaults; keeps repeated Set-Cookie
        return resp


def _wrap_non_json_error(upstream: str, status: int) -> Response:
    """D5: keep the upstream status. 4xx gets the code from the status map; 5xx is always UPSTREAM_ERROR
    (INTERNAL_ERROR stays reserved for gateway bugs)."""
    if status >= 500:
        exc = UpstreamError(upstream, status)
        return error_response(exc.status_code, exc.code, exc.message, exc.details)
    return error_response(status, status_code_name(status), "The service returned an unexpected response.",
                          [{"upstream": upstream}])


async def _body(upstream: httpx.Response, name: str = "unknown") -> AsyncIterator[bytes]:
    """Stream bytes unchanged. finally: the upstream connection is released even when the client
    disconnects mid-stream (Starlette cancels the generator)."""
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    except httpx.TransportError as exc:
        # headers are already sent, so no envelope is possible; log and close the connection
        UPSTREAM_ERRORS.labels(upstream=name, kind="stream").inc()
        log.warning("gateway.upstream.error",
                    extra={"upstream": name, "kind": "stream", "error_type": type(exc).__name__})
        raise
    finally:
        await upstream.aclose()
