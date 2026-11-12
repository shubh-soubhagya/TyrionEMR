"""Authentication gate (LLD §20.3): bearer -> kid -> JWKS key -> verify. Authenticates, never authorizes."""
from __future__ import annotations

import logging

from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import AppError, TokenExpired, Unauthenticated
from app.core.metrics import AUTH_FAILURES
from app.core.security import Claims, bearer_token, unverified_kid, verify_access_token
from app.domain.clock import Clock
from app.services.jwks_cache import JwksCache

log = logging.getLogger("gateway.auth")


def _reject(reason: str, exc: AppError) -> AppError:
    AUTH_FAILURES.labels(reason=reason).inc()
    log.info("gateway.auth.rejected", extra={"reason": reason})        # the reason only, never the token
    return exc


class AuthGate:
    def __init__(self, jwks: JwksCache, settings: Settings, clock: Clock) -> None:
        self._jwks, self._s, self._clock = jwks, settings, clock

    async def authenticate(self, request: Request) -> Claims:
        try:
            token = bearer_token(request)
        except Unauthenticated as exc:
            has_header = "authorization" in request.headers
            raise _reject("malformed" if has_header else "missing", exc) from exc
        try:
            kid = unverified_kid(token)
        except Unauthenticated as exc:
            raise _reject("malformed", exc) from exc
        key = await self._jwks.key_for(kid)
        if key is None:
            raise _reject("unknown_kid", Unauthenticated())
        try:
            claims = verify_access_token(token, {kid: key}, issuer=self._s.jwt_issuer,
                                         audience=self._s.jwt_audience, now=self._clock.wall())
        except TokenExpired as exc:
            raise _reject("expired", exc) from exc
        except Unauthenticated as exc:
            raise _reject("invalid", exc) from exc
        request.state.user_id = claims.sub                  # picked up by the access log
        return claims
