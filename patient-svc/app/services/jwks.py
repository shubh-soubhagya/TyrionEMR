"""JWKS client: fetches auth-svc's public keys, caches them, keeps the last good set on failure (LLD §3).

Same rules as the gateway's cache: keys are replaced (never merged), RSA >= 2048 bits only, the kid must
be the RFC 7638 thumbprint, an unknown kid triggers at most one refetch per JWKS_MIN_REFETCH_S.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey, RSAPublicNumbers

from app.core.config import Settings

log = logging.getLogger("patient.jwks")
Fetch = Callable[[], Awaitable[Any]]
Mono = Callable[[], float]


def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_to_int(s: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def thumbprint_kid(pub: RSAPublicKey) -> str:
    nums = pub.public_numbers()
    canonical = json.dumps({"e": _b64u_uint(nums.e), "kty": "RSA", "n": _b64u_uint(nums.n)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


def parse_jwks(doc: Any) -> dict[str, RSAPublicKey]:
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise ValueError("not a JWKS document")
    keys: dict[str, RSAPublicKey] = {}
    for jwk in doc["keys"]:
        if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
            continue
        if jwk.get("use", "sig") != "sig" or jwk.get("alg", "RS256") != "RS256":
            continue
        try:
            pub = RSAPublicNumbers(_b64u_to_int(jwk["e"]), _b64u_to_int(jwk["n"])).public_key()
        except (KeyError, TypeError, ValueError):
            log.warning("jwks.key_rejected", extra={"reason": "malformed"})
            continue
        kid = jwk.get("kid")
        if pub.key_size < 2048:
            log.warning("jwks.key_rejected", extra={"reason": "too_small"})
            continue
        if not isinstance(kid, str) or kid != thumbprint_kid(pub):
            log.warning("jwks.key_rejected", extra={"reason": "kid_mismatch"})
            continue
        keys[kid] = pub
    return keys


def http_fetch(settings: Settings) -> Fetch:
    async def fetch() -> Any:
        async with httpx.AsyncClient(timeout=settings.jwks_fetch_timeout_s) as client:
            resp = await client.get(settings.jwks_url)
            resp.raise_for_status()
            return resp.json()

    return fetch


class JwksCache:
    def __init__(self, fetch: Fetch, settings: Settings, mono: Mono = time.monotonic) -> None:
        self._fetch, self._s, self._mono = fetch, settings, mono
        self._keys: dict[str, RSAPublicKey] = {}
        self._last_success: float | None = None
        self._last_attempt = float("-inf")
        self._lock = asyncio.Lock()

    @property
    def fresh(self) -> bool:
        return self._last_success is not None and self._mono() - self._last_success <= self._s.jwks_max_stale_s

    @property
    def key_count(self) -> int:
        return len(self._keys) if self.fresh else 0

    async def key_for(self, kid: str) -> RSAPublicKey | None:
        if self.fresh and kid in self._keys:
            return self._keys[kid]
        await self.refresh("unknown_kid", min_interval_s=self._s.jwks_min_refetch_s)
        return self._keys.get(kid) if self.fresh else None

    async def refresh(self, reason: str, *, min_interval_s: float = 0.0) -> bool:
        async with self._lock:                                   # single-flight
            if self._mono() - self._last_attempt < min_interval_s:
                return False
            self._last_attempt = self._mono()
            try:
                keys = parse_jwks(await self._fetch())
                if not keys:
                    raise ValueError("JWKS contained no usable key")
            except Exception as exc:                             # keep the previous keyset
                log.warning("jwks.refresh_failed", extra={"reason": reason, "error_type": type(exc).__name__})
                return False
            self._keys = keys
            self._last_success = self._mono()
            log.info("jwks.refreshed", extra={"reason": reason, "keys": len(keys)})
            return True

    async def run_forever(self) -> None:
        backoff = 2.0
        while True:
            if await self.refresh("scheduled"):
                backoff = 2.0
                await asyncio.sleep(self._s.jwks_cache_ttl_s)
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
