"""One httpx.AsyncClient per upstream (LLD §23.1, ADR-G4): bulkheads, and per-upstream metrics."""
from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.core.config import Settings


class UpstreamRegistry:
    def __init__(self, s: Settings, transports: Mapping[str, httpx.AsyncBaseTransport] | None = None) -> None:
        self._bases = {name: url.rstrip("/") for name, url in s.upstream_urls().items() if url}
        self._clients: dict[str, httpx.AsyncClient] = {
            name: httpx.AsyncClient(
                base_url=base,
                transport=(transports or {}).get(name),
                timeout=httpx.Timeout(connect=s.upstream_connect_timeout_s, read=s.upstream_default_timeout_s,
                                      write=5.0, pool=s.upstream_pool_timeout_s),
                limits=httpx.Limits(max_connections=s.upstream_max_connections,
                                    max_keepalive_connections=s.upstream_max_keepalive, keepalive_expiry=30),
                follow_redirects=False,
                trust_env=False,                 # never route internal traffic through a host proxy
            )
            for name, base in self._bases.items()
        }

    def configured(self, name: str) -> bool:
        return name in self._clients

    def client(self, name: str) -> httpx.AsyncClient:
        return self._clients[name]

    def base_url(self, name: str) -> str:
        return self._bases[name]

    def names(self) -> list[str]:
        return list(self._clients)

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()
