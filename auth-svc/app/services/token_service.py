"""Access-token issue/verify and refresh-secret helpers (LLD §20.5)."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

import jwt

from app.core.config import Settings
from app.core.security import Claims, verify_access_token
from app.domain.clock import Clock
from app.services.keystore import KeyStore


class TokenService:
    def __init__(self, keys: KeyStore, s: Settings, clock: Clock) -> None:
        self._keys, self._s, self._clock = keys, s, clock

    def issue_access_token(self, user: Any) -> tuple[str, int]:
        now = int(self._clock().timestamp())
        ttl = self._s.access_token_ttl_min * 60
        # No name, email or other PII in the token (LLD §17.9)
        claims = {
            "iss": self._s.jwt_issuer, "aud": self._s.jwt_audience, "sub": str(user.id),
            "role": user.role, "iat": now, "nbf": now, "exp": now + ttl, "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._keys.active.private_key, algorithm="RS256",
                           headers={"kid": self._keys.active.kid, "typ": "JWT"})
        return token, ttl

    def verify_access_token(self, token: str) -> Claims:
        return verify_access_token(token, self._keys.published,
                                   issuer=self._s.jwt_issuer, audience=self._s.jwt_audience,
                                   now=self._clock().timestamp())

    @staticmethod
    def new_refresh_secret() -> tuple[str, str]:
        raw = secrets.token_urlsafe(32)  # 256 bits, 43 chars
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def hash_refresh(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()
