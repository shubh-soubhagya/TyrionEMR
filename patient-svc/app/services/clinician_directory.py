"""Resolves a clinician's display name from auth-svc (LLD §27.1 #1, review fix).

auth-svc deliberately issues NO name or other PII in the access token (its LLD §17.9), so the name is looked
up with ``GET /auth/me`` using the CALLER'S OWN token, and cached per user. It is a snapshot stored on the
encounter, so patient-svc never needs auth-svc to render history.

Design rules:
  * never raises: any failure returns ``None`` and the write still succeeds (``clinician_name`` is nullable);
  * the caller makes this call BEFORE opening a database transaction, never while holding the patient lock;
  * logs and metrics carry a reason and a status code only, never the name, e-mail or token.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.metrics import CLINICIAN_NAME_LOOKUPS

log = logging.getLogger("patient.clinician_directory")

MAX_NAME_LEN = 120


class ClinicianNames(Protocol):
    async def name_for(self, user_id: uuid.UUID, authorization: str, request_id: str | None) -> str | None: ...


def _clean_name(value: object) -> str | None:
    """Accept only a string of 1-120 characters after stripping."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= MAX_NAME_LEN else None


class ClinicianDirectory:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                 mono: Callable[[], float] = time.monotonic) -> None:
        self._s, self._mono = settings, mono
        # One shared client for the whole process: connect 1 s, read 2 s (a slow auth-svc must not stall writes)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=2.0), transport=transport)
        self._cache: OrderedDict[uuid.UUID, tuple[float, str | None]] = OrderedDict()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- public ------------------------------------------------------------------------------
    async def name_for(self, user_id: uuid.UUID, authorization: str, request_id: str | None) -> str | None:
        try:
            hit = self._cached(user_id)
            if hit is not None:
                CLINICIAN_NAME_LOOKUPS.labels(result="cache_hit").inc()
                return hit[0]
            name, result = await self._fetch(user_id, authorization, request_id)
            ttl = self._s.clinician_name_cache_ttl_s if name else self._s.clinician_name_negative_ttl_s
            self._store(user_id, name, ttl)
            CLINICIAN_NAME_LOOKUPS.labels(result=result).inc()
            return name
        except Exception as exc:                       # must never raise to the caller
            log.warning("clinician_name_unavailable", extra={"reason": type(exc).__name__, "status": None})
            CLINICIAN_NAME_LOOKUPS.labels(result="error").inc()
            return None

    # ---- cache -------------------------------------------------------------------------------
    def _cached(self, user_id: uuid.UUID) -> tuple[str | None] | None:
        entry = self._cache.get(user_id)
        if entry is None:
            return None
        expires, name = entry
        if expires <= self._mono():
            del self._cache[user_id]
            return None
        return (name,)

    def _store(self, user_id: uuid.UUID, name: str | None, ttl: float) -> None:
        self._cache.pop(user_id, None)
        while len(self._cache) >= self._s.clinician_name_cache_max:
            self._cache.popitem(last=False)             # evict the oldest
        self._cache[user_id] = (self._mono() + ttl, name)

    # ---- HTTP --------------------------------------------------------------------------------
    async def _fetch(self, user_id: uuid.UUID, authorization: str, request_id: str | None) -> tuple[str | None, str]:
        headers = {"Authorization": authorization}
        if request_id:
            headers["X-Request-ID"] = request_id
        response = None
        for attempt in (1, 2):                          # retry ONCE, on connect errors only
            try:
                response = await self._client.get(self._s.auth_me_url, headers=headers)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 2:
                    return self._failed("connect_error", None, exc)
            except httpx.HTTPError as exc:              # read timeout, protocol error, ...: no retry
                return self._failed(type(exc).__name__, None, exc)
        assert response is not None
        if response.status_code != 200:                 # 401/403/404/5xx: no retry on any status
            return self._failed("http_status", response.status_code, None)
        try:
            body = response.json()
        except ValueError:
            return self._failed("malformed_body", 200, None)
        if not isinstance(body, dict):
            return self._failed("malformed_body", 200, None)
        try:
            same_user = uuid.UUID(str(body.get("id"))) == user_id
        except ValueError:
            same_user = False
        if not same_user:
            return self._failed("id_mismatch", 200, None)
        name = _clean_name(body.get("full_name"))        # read ONLY full_name
        if name is None:
            return self._failed("invalid_name", 200, None)
        return name, "ok"

    @staticmethod
    def _failed(reason: str, status: int | None, _exc: Exception | None) -> tuple[None, str]:
        log.warning("clinician_name_unavailable", extra={"reason": reason, "status": status})
        return None, reason
