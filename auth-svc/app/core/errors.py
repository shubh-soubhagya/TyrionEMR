"""Uniform error envelope (HLD-v2 §12) and the exception handlers that produce it."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

log = logging.getLogger("nephro.errors")

_HTTP_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "VALIDATION_ERROR",
    429: "RATE_LIMITED", 502: "UPSTREAM_UNAVAILABLE", 503: "NOT_READY", 504: "UPSTREAM_TIMEOUT",
}


class AppError(Exception):
    """A deliberate, client-visible error. Subclass it per service."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or []
        self.headers = headers or {}


def envelope(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or [], "request_id": get_request_id()}}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(envelope(code, message, details), status_code=status_code, headers=headers)


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    message = "Not found." if exc.status_code == 404 else str(exc.detail)
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Deliberately omit each error's "input": it can contain the submitted password.
    details = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", ()) if p != "body"]
        details.append({
            "field": ".".join(loc),
            "code": str(e.get("type", "invalid")).upper(),
            "message": str(e.get("msg", "Invalid value.")),
        })
    return error_response(422, "VALIDATION_ERROR", "Request validation failed.", details)


def install_exception_handlers(app: FastAPI) -> None:
    # The catch-all for unexpected exceptions lives in RequestContextMiddleware so the 500
    # still carries X-Request-ID (Starlette's ServerErrorMiddleware sits outside our middleware).
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# auth-svc error classes (LLD §18)
# --------------------------------------------------------------------------------------
class AuthError(AppError):
    """Base for auth errors. ``clear_cookie`` makes the handler add a clearing Set-Cookie."""

    clear_cookie: bool = False


class InvalidCredentials(AuthError):
    status_code, code, message = 401, "INVALID_CREDENTIALS", "Invalid email or password."


class AccountLocked(AuthError):
    status_code, code = 429, "ACCOUNT_LOCKED"

    def __init__(self, retry_after: int) -> None:
        minutes = max(1, -(-retry_after // 60))
        super().__init__(f"Too many failed attempts. Try again in {minutes} minutes.",
                         headers={"Retry-After": str(retry_after)})


class AccountDisabled(AuthError):
    status_code, code = 403, "ACCOUNT_DISABLED"
    message = "This account has been deactivated. Contact your clinic's support."


class SignupDisabled(AuthError):
    status_code, code = 403, "SIGNUP_DISABLED"
    message = "Public signup is turned off. Ask for an invitation."


class EmailTaken(AuthError):
    status_code, code = 409, "EMAIL_TAKEN"
    message = "An account with this email already exists."


class PasswordPolicyError(AuthError):
    status_code, code = 422, "VALIDATION_ERROR"
    message = "Password does not meet the rules."


class RefreshMissing(AuthError):
    status_code, code, message = 401, "REFRESH_MISSING", "Please sign in."


class RefreshInvalid(AuthError):
    status_code, code = 401, "REFRESH_INVALID"
    message = "Your session has ended. Please sign in again."
    clear_cookie = True


class RefreshExpired(AuthError):
    status_code, code = 401, "REFRESH_EXPIRED"
    message = "Your session expired. Please sign in again."
    clear_cookie = True


class RefreshReused(AuthError):
    status_code, code = 401, "REFRESH_REUSED"
    message = "You were signed out for security. Please sign in again."
    clear_cookie = True


class RefreshRace(AuthError):
    """Two tabs refreshed at once. The cookie is deliberately NOT cleared (ADR-A5)."""

    status_code, code = 409, "REFRESH_RACE"
    message = "Refresh already in progress. Retry."


class OriginNotAllowed(AuthError):
    status_code, code, message = 403, "ORIGIN_NOT_ALLOWED", "Request blocked."


class Unauthenticated(AuthError):
    status_code, code, message = 401, "UNAUTHENTICATED", "Please sign in."


class TokenExpired(AuthError):
    status_code, code, message = 401, "TOKEN_EXPIRED", "Your access token has expired."


class Forbidden(AuthError):
    status_code, code, message = 403, "FORBIDDEN", "You do not have permission to do this."


class NotFound(AuthError):
    status_code, code, message = 404, "NOT_FOUND", "Not found."


class NotReady(AuthError):
    status_code, code, message = 503, "NOT_READY", "Service unavailable."
