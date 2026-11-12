"""Access-token verification, ``current_claims``, ``require_role`` and the Origin check.

Verification rules (LLD §19.5/§22.2) are identical to what the gateway and other services apply:
RS256 only, iss/aud/exp/iat/sub required, 30 s leeway, key chosen by ``kid``.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, Request

from app.core.config import Settings
from app.core.errors import Forbidden, OriginNotAllowed, TokenExpired, Unauthenticated

ALGORITHM = "RS256"
LEEWAY_S = 30
REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]


@dataclass(frozen=True)
class Claims:
    sub: str
    role: str
    raw: Mapping[str, Any]


def verify_access_token(
    token: str, keys: Mapping[str, Any], *, issuer: str, audience: str, now: float | None = None
) -> Claims:
    """``now`` (epoch seconds) is injectable so expiry can be tested with a fake clock."""
    now = time.time() if now is None else now
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc
    if header.get("alg") != ALGORITHM:          # rejects "none", HS256 key-confusion, anything else
        raise Unauthenticated()
    kid = header.get("kid")
    key = keys.get(kid) if isinstance(kid, str) else None
    if key is None:
        raise Unauthenticated()
    try:
        payload = jwt.decode(
            token, key, algorithms=[ALGORITHM], audience=audience, issuer=issuer,
            leeway=LEEWAY_S,
            # time claims are required here but checked below against the injected clock
            options={"require": REQUIRED_CLAIMS, "verify_exp": False, "verify_nbf": False,
                     "verify_iat": False},
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc
    try:
        exp, iat = float(payload["exp"]), float(payload["iat"])
        nbf = float(payload.get("nbf", iat))
    except (TypeError, ValueError) as exc:
        raise Unauthenticated() from exc
    if exp + LEEWAY_S <= now:
        raise TokenExpired()
    if nbf - LEEWAY_S > now or iat - LEEWAY_S > now:
        raise Unauthenticated()
    try:
        subject = str(uuid.UUID(str(payload["sub"])))      # every user id is a UUID
    except ValueError as exc:
        raise Unauthenticated() from exc
    return Claims(sub=subject, role=str(payload.get("role", "")), raw=payload)


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated()
    return token.strip()


async def current_claims(request: Request) -> Claims:
    settings: Settings = request.app.state.settings
    claims = verify_access_token(
        bearer_token(request), request.app.state.keystore.published,
        issuer=settings.jwt_issuer, audience=settings.jwt_audience,
        now=request.app.state.clock().timestamp(),
    )
    request.state.user_id = claims.sub          # picked up by the access log
    return claims


def require_role(*roles: str):
    """Dependency factory: ``Depends(require_role("clinician"))``."""

    async def checker(claims: Claims = Depends(current_claims)) -> Claims:
        if claims.role not in roles:
            raise Forbidden()
        return claims

    return checker


async def require_trusted_origin(request: Request) -> None:
    """CSRF defense in depth beside SameSite=Strict (R4). Absent Origin is allowed (non-browser)."""
    origin = request.headers.get("origin")
    settings: Settings = request.app.state.settings
    if origin is not None and origin not in settings.cors_allowed_origins:
        raise OriginNotAllowed()
