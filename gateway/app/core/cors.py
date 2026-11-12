"""CORS (LLD §8.5, §24). Exact-origin allow-list, credentials allowed (the refresh cookie).

Sits inside the metrics and security-header middlewares and outside the routes, so every response the
application produces, including gateway errors (401, 429, 502, 500), carries the CORS headers. Without that
a gateway error would look like a CORS failure in the browser and Angular's interceptor would see status 0.
"""
from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import get_request_id, set_route

ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
ALLOWED_HEADERS = "Authorization, Content-Type, X-Request-ID, If-None-Match, If-Match, Cache-Control, Idempotency-Key"
EXPOSED_HEADERS = "X-Request-ID, Retry-After, ETag, Location, Content-Disposition"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CorsMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str], max_age_s: int) -> None:
        self.app, self.allowed, self.max_age = app, frozenset(allowed_origins), str(max_age_s)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        method = scope["method"]
        allowed = origin is not None and origin in self.allowed

        if method == "OPTIONS" and origin is not None and "access-control-request-method" in headers:
            # exact method match (the LLD's substring test would let "PO" or "" through)
            wanted = headers["access-control-request-method"].strip().upper()
            if not allowed or wanted not in ALLOWED_METHODS:
                await self._reject(scope, send)
                return
            set_route(scope, "preflight")
            await send({"type": "http.response.start", "status": 204, "headers": [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-credentials", b"true"),
                (b"access-control-allow-methods", ", ".join(ALLOWED_METHODS).encode()),
                (b"access-control-allow-headers", ALLOWED_HEADERS.encode()),
                (b"access-control-max-age", self.max_age.encode()),
                (b"vary", b"Origin"),
            ]})
            await send({"type": "http.response.body", "body": b""})
            return

        # Defense in depth beside Bearer tokens (R12): an unsafe request from a foreign origin never runs.
        if origin is not None and not allowed and method in UNSAFE:
            await self._reject(scope, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [(b"vary", b"Origin")]
                if allowed and origin is not None:
                    extra += [(b"access-control-allow-origin", origin.encode("latin-1")),
                              (b"access-control-allow-credentials", b"true"),
                              (b"access-control-expose-headers", EXPOSED_HEADERS.encode())]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _reject(self, scope: Scope, send: Send) -> None:
        set_route(scope, "origin_rejected")
        body = json.dumps({"error": {"code": "ORIGIN_NOT_ALLOWED", "message": "Request blocked.",
                                     "details": [], "request_id": get_request_id()}}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"vary", b"Origin")]})
        await send({"type": "http.response.body", "body": body})
