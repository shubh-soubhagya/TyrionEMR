"""LLM resilience (LLD B7.4): deadline, retry, 429 handling, circuit breaker, concurrency limit.

One policy for every provider, wrapped around the adapter. Counts of failures, breaker state changes and slot waits
are metrics (B16). Nothing here logs prompts or model text.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.metrics import (
    LLM_BREAKER_OPEN,
    LLM_REQUEST_DURATION,
    LLM_REQUESTS,
    LLM_SLOT_WAIT,
    LLM_SLOTS_IN_USE,
)
from app.llm.base import (
    LLMAuthError,
    LLMBusy,
    LLMCircuitOpen,
    LLMProvider,
    LLMRateLimited,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    LLMUnavailable,
)

log = logging.getLogger("ai.llm")
Mono = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class CircuitBreaker:
    """Per provider, per process: opens after N consecutive failures, stays open for the cooldown, then lets ONE
    probe through (half-open). A success closes it; a failed probe re-opens it."""

    def __init__(self, provider: str, failures: int, cooldown_s: float, mono: Mono = time.monotonic) -> None:
        self._provider, self._threshold, self._cooldown, self._mono = provider, failures, cooldown_s, mono
        self._count = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._mono() - self._opened_at >= self._cooldown else "open"

    def allow(self) -> bool:
        s = self.state
        if s == "closed":
            return True
        if s == "half_open" and not self._probing:
            self._probing = True
            self._transition("half_open")
            return True
        return False

    def success(self) -> None:
        was_open = self._opened_at is not None
        self._count, self._opened_at, self._probing = 0, None, False
        if was_open:
            self._transition("closed")

    def failure(self) -> None:
        self._count += 1
        if self._probing or self._count >= self._threshold:
            if self._opened_at is None or self._probing:
                self._transition("open")
            self._opened_at, self._probing = self._mono(), False

    def _transition(self, to: str) -> None:
        log.warning("breaker.state", extra={"provider": self._provider, "to": to})
        LLM_BREAKER_OPEN.labels(self._provider).set(1 if to == "open" else 0)


@dataclass(frozen=True)
class ResilienceConfig:
    retries: int = 1
    rate_limit_max_wait_s: float = 10.0
    max_concurrency: int = 4
    slot_wait_s: float = 20.0
    breaker_failures: int = 5
    breaker_cooldown_s: float = 60.0
    http_timeout_s: float = 30.0


class ResilientLLM:
    """Wraps a provider. ``generate`` raises only LLMError subclasses."""

    def __init__(self, provider: LLMProvider, cfg: ResilienceConfig, *, mono: Mono = time.monotonic,
                 sleep: Sleep = asyncio.sleep) -> None:
        self.provider, self.cfg, self._mono, self._sleep = provider, cfg, mono, sleep
        self.breaker = CircuitBreaker(provider.name, cfg.breaker_failures, cfg.breaker_cooldown_s, mono)
        self._slots = asyncio.Semaphore(cfg.max_concurrency)

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str:
        return self.provider.model

    @property
    def capabilities(self):
        return self.provider.capabilities

    async def generate(self, req: LLMRequest, *, deadline_left: Callable[[], float],
                       on_wait: Callable[[], Awaitable[None]] | None = None) -> LLMResponse:
        if deadline_left() <= 2:
            raise LLMTimeout("job deadline reached")
        if not self.breaker.allow():
            LLM_REQUESTS.labels(self.name, "circuit_open").inc()
            raise LLMCircuitOpen("circuit open")
        await self._acquire(on_wait)
        try:
            return await self._call(req, deadline_left)
        finally:
            self._slots.release()
            LLM_SLOTS_IN_USE.dec()

    async def _acquire(self, on_wait: Callable[[], Awaitable[None]] | None) -> None:
        started = self._mono()
        if self._slots.locked() and on_wait:
            await on_wait()                                  # progress note: "Waiting for an AI slot"
        try:
            await asyncio.wait_for(self._slots.acquire(), self.cfg.slot_wait_s)
        except TimeoutError:
            LLM_REQUESTS.labels(self.name, "busy").inc()
            raise LLMBusy("no free slot") from None
        finally:
            LLM_SLOT_WAIT.observe(self._mono() - started)
        LLM_SLOTS_IN_USE.inc()

    async def _call(self, req: LLMRequest, deadline_left: Callable[[], float]) -> LLMResponse:
        retries_left = self.cfg.retries
        waited_for_rate_limit = False
        attempt = 0
        while True:
            attempt += 1
            # each HTTP timeout is min(LLM_TIMEOUT_S, remaining - 2 s)
            timeout = min(self.cfg.http_timeout_s, deadline_left() - 2)
            if timeout <= 0:
                raise LLMTimeout("job deadline reached")
            call_started = self._mono()
            try:
                resp = await self.provider.generate(_with_timeout(req, timeout))
            except LLMRateLimited as exc:
                self._log_call("rate_limited", call_started)
                self.breaker.failure()
                LLM_REQUESTS.labels(self.name, "rate_limited").inc()
                wait = exc.retry_after
                if (not waited_for_rate_limit and wait is not None and wait <= self.cfg.rate_limit_max_wait_s
                        and deadline_left() > wait + 2):
                    waited_for_rate_limit = True                    # honour Retry-After once, never a tight loop
                    await self._sleep(wait)
                    continue
                raise
            except (LLMTimeout, LLMUnavailable) as exc:
                self._log_call("timeout" if isinstance(exc, LLMTimeout) else "unavailable", call_started)
                self.breaker.failure()
                LLM_REQUESTS.labels(self.name, "timeout" if isinstance(exc, LLMTimeout) else "unavailable").inc()
                backoff = random.uniform(0.5, 1.5)                   # noqa: S311 (jitter only)
                if retries_left > 0 and deadline_left() > backoff + 2:
                    retries_left -= 1
                    await self._sleep(backoff)
                    continue
                raise
            except LLMAuthError:
                self._log_call("auth_error", call_started)
                LLM_REQUESTS.labels(self.name, "auth_error").inc()
                log.error("llm.auth_error", extra={"provider": self.name})
                raise
            self.breaker.success()
            LLM_REQUESTS.labels(self.name, "ok").inc()
            self._log_call("ok", call_started)
            return resp

    def _log_call(self, outcome: str, started: float) -> None:
        """B16 `llm.call`: provider, model, outcome and latency only. Never a prompt, a reply or a key."""
        elapsed = self._mono() - started
        LLM_REQUEST_DURATION.labels(self.name).observe(elapsed)
        log.info("llm.call", extra={"provider": self.name, "model": self.model, "outcome": outcome,
                                    "latency_ms": round(elapsed * 1000)})


def _with_timeout(req: LLMRequest, timeout_s: float) -> LLMRequest:
    from dataclasses import replace
    return replace(req, timeout_s=timeout_s)
