"""Security headers on every response (LLD §8.7, §25.3)."""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BASE = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
         (b"referrer-policy", b"no-referrer"), (b"cross-origin-resource-policy", b"same-site")]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.extra = _BASE + ([(b"strict-transport-security", b"max-age=31536000")] if hsts else [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                # Clinical data must not sit in shared caches, but a service's own Cache-Control
                # (lab-svc's catalog max-age) and ETag revalidation keep working.
                if b"cache-control" not in names:
                    headers.append((b"cache-control", b"no-store"))
                headers += [h for h in self.extra if h[0] not in names]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
