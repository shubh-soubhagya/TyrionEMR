"""A minimal catch-all route that wires path safety -> resolver -> ProxyService against fake upstreams.

Phase 4 tests use this before the real GatewayPipeline exists (Phase 5). Upstreams are
``httpx.MockTransport`` handlers, so nothing touches the network.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request

from app.core.common_setup import install_common_middleware
from app.core.config import Settings
from app.core.errors import InvalidPath, NotFound
from app.routing.paths import UnsafePath, safe_segments
from app.routing.resolver import resolve
from app.routing.table import build_routes
from app.services.proxy import ProxyService
from app.services.upstreams import UpstreamRegistry

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


class _Stream(httpx.AsyncByteStream):
    """Bytes served as a real stream and a flag that records whether the proxy closed it."""

    def __init__(self, data: bytes, chunk: int = 65536) -> None:
        self._data, self._chunk = data, chunk
        self.closed = False

    async def __aiter__(self):
        for i in range(0, len(self._data), self._chunk):
            yield self._data[i:i + self._chunk]

    async def aclose(self) -> None:
        self.closed = True


def as_streaming(resp: httpx.Response) -> httpx.Response:
    """httpx.Response(json=...) is already read into memory; a real transport streams. Mirror that."""
    if not resp.is_stream_consumed:
        return resp
    return httpx.Response(resp.status_code, headers=resp.headers, stream=_Stream(resp.content))


class Recorder:
    """Records every request an upstream received and answers with ``handler``."""

    def __init__(self, handler: Handler | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler or (lambda req: httpx.Response(200, json={"ok": True}))

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self._handler(request)
        if not isinstance(result, httpx.Response):
            result = await result
        return as_streaming(result)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def build_app(settings: Settings, upstreams: dict[str, Recorder]) -> tuple[FastAPI, UpstreamRegistry]:
    registry = UpstreamRegistry(settings, {n: httpx.MockTransport(r) for n, r in upstreams.items()})
    proxy = ProxyService(registry)
    routes = build_routes(settings)
    router = APIRouter()

    @router.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def catch_all(request: Request) -> Any:
        raw = request.scope.get("raw_path", b"").decode("latin-1")
        try:
            match = resolve(request.method, raw, safe_segments(raw), routes)
        except UnsafePath:
            raise InvalidPath() from None
        if match is None:
            raise NotFound()
        client = request.client.host if request.client else "0.0.0.0"
        return await proxy.forward(request, match, await request.body(), client)

    app = FastAPI(redirect_slashes=False)           # no JWT, no limits: the proxy layer on its own
    install_common_middleware(app)
    app.include_router(router)
    return app, registry


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 5555)),
                             base_url="http://localhost:8080")
