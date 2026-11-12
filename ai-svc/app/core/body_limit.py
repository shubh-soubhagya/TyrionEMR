"""Request-body size limit (MAX_BODY_BYTES, default 1 MiB). Pure ASGI, never buffers the body itself.

Two layers, because a client controls how it frames the body:
  * a ``Content-Length`` above the limit is rejected immediately, before a single body byte is read;
  * a chunked body (no Content-Length) is counted as it streams, and the request is aborted the moment the
    running total passes the limit.

Both answer 413 in the standard error envelope (code PAYLOAD_TOO_LARGE). The streaming case raises an
HTTPException from ``receive()``: FastAPI re-raises HTTPException from body parsing (any other exception would be
turned into a 400), so the app's normal exception handler produces the envelope.
"""
from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response

DEFAULT_MAX_BODY_BYTES = 1_048_576
MESSAGE = "Request body is too large."


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _limit(scope: Scope) -> int:
        state = getattr(scope.get("app"), "state", None)
        settings = getattr(state, "settings", None)
        return getattr(settings, "max_body_bytes", DEFAULT_MAX_BODY_BYTES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            response = error_response(413, "PAYLOAD_TOO_LARGE", MESSAGE)
            await response(scope, receive, send)
            return

        seen = 0

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(status_code=413, detail=MESSAGE)
            return message

        await self.app(scope, counting_receive, send)
