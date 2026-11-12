"""Access-token verification (LLD §20.1; README deviation D9: newer than the LLD's code).

``verify_access_token`` is a copy of auth-svc/app/core/security.py as it is NOW on main (UUID ``sub``,
expiry checked against an injected clock), so both components apply identical rules (no shared library).
tests/unit/test_security.py repeats auth-svc's token cases to catch drift. The gateway checks authenticity
and expiry only; it never looks at ``role`` (ADR-G6), so there is no ``require_role`` here.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from starlette.requests import Request

from app.core.errors import TokenExpired, Unauthenticated

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
        subject = str(uuid.UUID(str(payload["sub"])))      # every user id is a UUID (auth-svc D23)
    except ValueError as exc:
        raise Unauthenticated() from exc
    return Claims(sub=subject, role=str(payload.get("role", "")), raw=payload)


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated()
    return token.strip()


def unverified_kid(token: str) -> str:
    """Read ``kid`` from the header without trusting it (used only to pick a key)."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc
    kid = header.get("kid")
    if header.get("alg") != ALGORITHM or not isinstance(kid, str) or not 1 <= len(kid) <= 128:
        raise Unauthenticated()
    return kid
