"""Drive an ASGI app with a hand-built scope.

httpx normalizes dot segments and some encodings before sending, so hostile paths (``curl --path-as-is``),
chunked bodies without Content-Length and invalid Content-Length values can only be tested this way.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


@dataclass
class RawResponse:
    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers if k == name.lower()), None)

    def json(self) -> Any:
        return json.loads(self.body)


async def call(app: Any, method: str, raw_path: str, *, query: bytes = b"",
               headers: list[tuple[str, str]] | None = None, body_chunks: list[bytes] | None = None,
               client: tuple[str, int] = ("203.0.113.9", 5555)) -> RawResponse:
    chunks = body_chunks if body_chunks is not None else [b""]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": unquote(raw_path), "raw_path": raw_path.encode("latin-1"), "query_string": query,
        "root_path": "", "headers": [(k.lower().encode(), v.encode("latin-1")) for k, v in (headers or [])],
        "client": client, "server": ("gateway", 8080),
    }
    pending = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]

    async def receive() -> dict[str, Any]:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    status = 0
    out_headers: list[tuple[str, str]] = []
    body = bytearray()

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            out_headers.extend((k.decode("latin-1"), v.decode("latin-1")) for k, v in message["headers"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    await app(scope, receive, send)
    return RawResponse(status, out_headers, bytes(body))
