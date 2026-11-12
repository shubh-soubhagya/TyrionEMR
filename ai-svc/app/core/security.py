"""Access-token verification and role checks (LLD A8).

Same rules as auth-svc and the gateway: RS256 only, iss/aud/exp/iat/sub required, 30 s leeway, key chosen
by ``kid`` from the cached JWKS. Only the ``clinician`` role may use this service .
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request

from app.core.config import Settings
from app.core.errors import Forbidden, TokenExpired, Unauthenticated
from app.core.jwks import JwksCache

ALGORITHM = "RS256"
LEEWAY_S = 30
REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    role: str
    raw: Mapping[str, Any]


async def verify_access_token(
    token: str, jwks: JwksCache, *, issuer: str, audience: str, now: float | None = None
) -> User:
    """``now`` (epoch seconds) is injectable so expiry can be tested with a fake clock."""
    now = time.time() if now is None else now
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc
    if header.get("alg") != ALGORITHM:          # rejects "none" and HS256 key confusion
        raise Unauthenticated()
    kid = header.get("kid")
    key = await jwks.key_for(kid) if isinstance(kid, str) else None
    if key is None:
        raise Unauthenticated()
    try:
        payload = jwt.decode(
            token, key, algorithms=[ALGORITHM], audience=audience, issuer=issuer, leeway=LEEWAY_S,
            # time claims are required here but checked below against the injected clock
            options={"require": REQUIRED_CLAIMS, "verify_exp": False, "verify_nbf": False, "verify_iat": False},
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc
    try:
        exp, iat = float(payload["exp"]), float(payload["iat"])
        nbf = float(payload.get("nbf", iat))
        user_id = uuid.UUID(str(payload["sub"]))
    except (TypeError, ValueError) as exc:
        raise Unauthenticated() from exc
    if exp + LEEWAY_S <= now:
        raise TokenExpired()
    if nbf - LEEWAY_S > now or iat - LEEWAY_S > now:
        raise Unauthenticated()
    # Any `name` claim is deliberately ignored: auth-svc keeps tokens free of PII
    return User(id=user_id, role=str(payload.get("role", "")), raw=payload)


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated()
    return token.strip()


async def current_user(request: Request) -> User:
    settings: Settings = request.app.state.settings
    user = await verify_access_token(
        bearer_token(request), request.app.state.jwks,
        issuer=settings.jwt_issuer, audience=settings.jwt_audience,
        now=request.app.state.clock().timestamp(),
    )
    request.state.user_id = str(user.id)        # picked up by the access log
    return user


def require_role(*roles: str):
    """Dependency factory: ``Depends(require_role("clinician"))``."""

    async def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return checker


Clinician = Annotated[User, Depends(require_role("clinician"))]
