"""HTTP layer only: parse -> call service -> shape response. No SQL here."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response

from app.api.cookies import clear_refresh_cookie, set_refresh_cookie
from app.api.deps import get_auth_service, get_clock, get_settings_dep
from app.core.config import Settings
from app.core.errors import RefreshMissing
from app.core.ratelimit import rate_limit
from app.core.security import Claims, require_role, require_trusted_origin
from app.domain.clock import Clock
from app.schemas.auth import LoginIn, SignupIn, TokenOut, UserOut
from app.schemas.errors import ErrorEnvelope
from app.services.auth_service import AuthService, SessionResult

router = APIRouter()

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _err(*codes: int) -> dict:
    return {c: {"model": ErrorEnvelope} for c in codes}


def _token_response(r: SessionResult, response: Response, s: Settings, clock: Clock) -> TokenOut:
    set_refresh_cookie(response, r.raw_refresh, r.refresh_expires_at, s, clock)
    response.headers.update(NO_STORE)
    return TokenOut(access_token=r.access_token, expires_in=r.expires_in, user=UserOut.of(r.user))


@router.post("/signup", response_model=TokenOut, status_code=201, dependencies=[Depends(rate_limit)],
             responses=_err(403, 409, 422, 429, 503))
async def signup(body: SignupIn, request: Request, response: Response,
                 svc: AuthService = Depends(get_auth_service), s: Settings = Depends(get_settings_dep),
                 clock: Clock = Depends(get_clock)) -> TokenOut:
    r = await svc.signup(body, request.headers.get("user-agent"))
    return _token_response(r, response, s, clock)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit)],
             responses=_err(401, 403, 422, 429, 503))
async def login(body: LoginIn, request: Request, response: Response,
                svc: AuthService = Depends(get_auth_service), s: Settings = Depends(get_settings_dep),
                clock: Clock = Depends(get_clock)) -> TokenOut:
    r = await svc.login(body, request.headers.get("user-agent"))
    return _token_response(r, response, s, clock)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(require_trusted_origin)],
             responses=_err(401, 403, 409))
async def refresh(request: Request, response: Response,
                  svc: AuthService = Depends(get_auth_service), s: Settings = Depends(get_settings_dep),
                  clock: Clock = Depends(get_clock)) -> TokenOut:
    raw = request.cookies.get(s.refresh_cookie_name)
    if not raw:
        raise RefreshMissing()
    # Errors carrying clear_cookie get a clearing Set-Cookie from the app-level handler
    r = await svc.refresh(raw, request.headers.get("user-agent"))
    return _token_response(r, response, s, clock)


@router.post("/logout", status_code=204, dependencies=[Depends(require_trusted_origin)],
             responses=_err(403))
async def logout(request: Request, svc: AuthService = Depends(get_auth_service),
                 s: Settings = Depends(get_settings_dep)) -> Response:
    await svc.logout(request.cookies.get(s.refresh_cookie_name))
    resp = Response(status_code=204, headers=NO_STORE)
    clear_refresh_cookie(resp, s)
    return resp


@router.get("/me", response_model=UserOut, responses=_err(401, 403, 404))
async def me(claims: Claims = Depends(require_role("clinician")),
             svc: AuthService = Depends(get_auth_service)) -> UserOut:
    return UserOut.of(await svc.me(uuid.UUID(claims.sub)))
