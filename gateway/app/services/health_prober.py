"""Background /health probes of the upstreams (LLD §27.2, ADR-G9, ADR-G11).

The result only feeds /ready and a gauge. Routing never consults it: a probe can be up to
HEALTH_PROBE_INTERVAL_S stale, and the real request is the better health check.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx

from app.core.config import Settings
from app.core.metrics import UPSTREAM_UP
from app.services.upstreams import UpstreamRegistry

log = logging.getLogger("gateway.prober")
State = Literal["up", "down", "unknown", "not_configured"]
PROBE_TIMEOUT_S = 1.0
UPSTREAMS = ("auth", "patient", "lab", "ai")


class HealthProber:
    def __init__(self, registry: UpstreamRegistry, settings: Settings) -> None:
        self._reg, self._s = registry, settings
        self._state: dict[str, State] = {n: "unknown" if registry.configured(n) else "not_configured"
                                         for n in UPSTREAMS}

    def state(self, name: str) -> State:
        return self._state.get(name, "not_configured")

    def snapshot(self) -> dict[str, State]:
        return dict(self._state)

    async def probe_once(self) -> None:
        await asyncio.gather(*(self._probe(n) for n in UPSTREAMS if self._reg.configured(n)))

    async def _probe(self, name: str) -> None:
        try:
            resp = await self._reg.client(name).get("/health", timeout=PROBE_TIMEOUT_S)
            new: State = "up" if resp.status_code == 200 else "down"
        except (httpx.HTTPError, OSError):
            new = "down"
        UPSTREAM_UP.labels(upstream=name).set(1 if new == "up" else 0)
        if new != self._state[name]:
            log.info("gateway.upstream.health_changed", extra={"upstream": name, "from": self._state[name], "to": new})
            self._state[name] = new

    async def run_forever(self) -> None:
        while True:
            await self.probe_once()
            await asyncio.sleep(self._s.health_probe_interval_s)
