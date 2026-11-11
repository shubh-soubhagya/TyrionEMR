"""Pure-ASGI middleware: request id, JSON access log, last-resort 500 envelope."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var, route_template

log = logging.getLogger("nephro.access")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
REQUEST_ID_HEADER = b"x-request-id"


def new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:12]


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER, b"").decode("latin-1")
        rid = incoming if _VALID_ID.match(incoming) else new_request_id()
        token = request_id_var.set(rid)
        state = scope.setdefault("state", {})
        start = time.perf_counter()
        status = 500
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status = message["status"]
                started = True
                headers = [h for h in message.get("headers", []) if h[0].lower() != REQUEST_ID_HEADER]
                headers.append((REQUEST_ID_HEADER, rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled exception")
            if not started:
                body = json.dumps({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong.",
                                             "details": [], "request_id": rid}}).encode()
                await send_wrapper({"type": "http.response.start", "status": 500,
                                    "headers": [(b"content-type", b"application/json"),
                                                (b"content-length", str(len(body)).encode())]})
                await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            # Route template (never the raw path, which may hold ids) and never the query string.
            template = route_template(scope)
            client = scope.get("client")
            log.info("http.request", extra={
                "method": scope["method"],
                "route": template,
                "status": status,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "user_id": state.get("user_id") if isinstance(state, dict) else None,
                "client_ip": client[0] if client else None,
            })
            request_id_var.reset(token)
