"""JWKS cache (LLD §20.2, ADR-G7).

SIBLING IMPLEMENTATION: patient-svc/app/services/jwks.py applies the same rules and MUST keep following
them: the keyset is replaced on success (never merged), kept on failure, RSA >= 2048 bits only, ``kid``
must be the RFC 7638 thumbprint, and an unknown ``kid`` triggers at most one refetch per
JWKS_MIN_REFETCH_S, single-flight. Change one, change the other. The gateway adds a staleness cap
(JWKS_MAX_STALE_S) and a ``require_thumbprint`` switch.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey, RSAPublicNumbers

from app.core.config import Settings
from app.core.metrics import JWKS_KEYS, JWKS_REFRESH
from app.domain.clock import Clock

log = logging.getLogger("gateway.jwks")
Fetch = Callable[[], Awaitable[Any]]


def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_to_int(s: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def thumbprint_kid(pub: RSAPublicKey) -> str:
    """RFC 7638 thumbprint, identical to auth-svc KeyStore (ADR-A7)."""
    nums = pub.public_numbers()
    canonical = json.dumps({"e": _b64u_uint(nums.e), "kty": "RSA", "n": _b64u_uint(nums.n)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


def parse_jwks(doc: Any, *, require_thumbprint: bool) -> dict[str, RSAPublicKey]:
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise ValueError("not a JWKS document")
    keys: dict[str, RSAPublicKey] = {}
    for jwk in doc["keys"]:
        if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
            continue
        if jwk.get("use", "sig") != "sig" or jwk.get("alg", "RS256") != "RS256":
            continue
        kid = jwk.get("kid")
        try:
            pub = RSAPublicNumbers(_b64u_to_int(jwk["e"]), _b64u_to_int(jwk["n"])).public_key()
        except (KeyError, TypeError, ValueError):
            log.warning("gateway.jwks.key_rejected", extra={"reason": "malformed"})
            continue
        if pub.key_size < 2048:
            log.warning("gateway.jwks.key_rejected", extra={"reason": "too_small"})
            continue
        if not isinstance(kid, str) or (require_thumbprint and kid != thumbprint_kid(pub)):
            log.warning("gateway.jwks.key_rejected", extra={"reason": "kid_mismatch"})
            continue
        keys[kid] = pub
    return keys


class JwksCache:
    def __init__(self, fetch: Fetch, settings: Settings, clock: Clock) -> None:
        self._fetch, self._s, self._clock = fetch, settings, clock
        self._keys: dict[str, RSAPublicKey] = {}
        self._last_success: float | None = None
        self._last_attempt = float("-inf")
        self._lock = asyncio.Lock()

    # ---- state -------------------------------------------------------------------------------
    @property
    def fresh(self) -> bool:
        return (self._last_success is not None
                and self._clock.monotonic() - self._last_success <= self._s.jwks_max_stale_s)

    @property
    def key_count(self) -> int:
        return len(self._keys) if self.fresh else 0

    def age_s(self) -> float | None:
        return None if self._last_success is None else self._clock.monotonic() - self._last_success

    # ---- lookups -----------------------------------------------------------------------------
    async def key_for(self, kid: str) -> RSAPublicKey | None:
        if self.fresh and kid in self._keys:
            return self._keys[kid]
        # unknown kid (rotation) or stale keyset: refetch, but never more often than JWKS_MIN_REFETCH_S
        await self.refresh("unknown_kid", min_interval_s=self._s.jwks_min_refetch_s)
        return self._keys.get(kid) if self.fresh else None

    # ---- refresh -----------------------------------------------------------------------------
    async def refresh(self, reason: str, *, min_interval_s: float = 0.0) -> bool:
        async with self._lock:                                   # single-flight
            if self._clock.monotonic() - self._last_attempt < min_interval_s:
                return False                                     # someone just tried; use what we have
            self._last_attempt = self._clock.monotonic()
            try:
                keys = parse_jwks(await self._fetch(), require_thumbprint=self._s.jwks_require_thumbprint_kid)
                if not keys:
                    raise ValueError("JWKS contained no usable key")
            except Exception as exc:                             # keep the previous keyset (ADR-G7)
                JWKS_REFRESH.labels(outcome="error").inc()
                log.warning("gateway.jwks.refresh_failed", extra={"reason": reason, "error_type": type(exc).__name__})
                return False
            self._keys = keys                                    # replace, never merge
            self._last_success = self._clock.monotonic()
            JWKS_REFRESH.labels(outcome="ok").inc()
            JWKS_KEYS.set(len(keys))
            log.info("gateway.jwks.refreshed", extra={"reason": reason, "keys": len(keys), "kids": sorted(keys)})
            return True

    async def run_forever(self) -> None:
        backoff = 2.0
        while True:
            ok = await self.refresh("scheduled")
            if ok:
                backoff = 2.0
                await asyncio.sleep(self._s.jwks_ttl_s)
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
