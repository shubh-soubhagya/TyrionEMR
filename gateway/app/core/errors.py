"""Uniform error envelope (HLD-v2 §12), the handlers that produce it, and the gateway error catalog (LLD §26).

``AppError``, ``envelope``, ``error_response`` and the handlers follow auth-svc's errors.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

log = logging.getLogger("nephro.errors")

# Status -> code for plain-text/HTML errors that did not come from an envelope-speaking service
# (framework 404/405 and wrapped upstream 4xx, LLD §23.3 and deviation D5). The auth-svc map plus 413 and 414.
_HTTP_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 414: "URI_TOO_LONG",
    422: "VALIDATION_ERROR", 429: "RATE_LIMITED", 502: "UPSTREAM_UNAVAILABLE", 503: "NOT_READY",
    504: "UPSTREAM_TIMEOUT",
}


def status_code_name(status: int) -> str:
    return _HTTP_CODES.get(status, "HTTP_ERROR")


class AppError(Exception):
    """A deliberate, client-visible error."""

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
    code = status_code_name(exc.status_code)
    message = "Not found." if exc.status_code == 404 else str(exc.detail)
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Omit each error's "input": it could echo submitted data.
    details = [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
                "code": str(e.get("type", "invalid")).upper(),
                "message": str(e.get("msg", "Invalid value."))} for e in exc.errors()]
    return error_response(422, "VALIDATION_ERROR", "Request validation failed.", details)


def install_exception_handlers(app: FastAPI) -> None:
    # The catch-all for unexpected exceptions lives in RequestContextMiddleware so the 500
    # still carries X-Request-ID.
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Gateway error classes (LLD §26)
# --------------------------------------------------------------------------------------
class GatewayError(AppError):
    pass


class InvalidPath(GatewayError):
    status_code, code, message = 400, "INVALID_PATH", "Invalid request path."


class BadRequest(GatewayError):
    status_code, code, message = 400, "BAD_REQUEST", "Bad request."


class Unauthenticated(GatewayError):
    status_code, code, message = 401, "UNAUTHENTICATED", "Please sign in."


class TokenExpired(GatewayError):
    status_code, code, message = 401, "TOKEN_EXPIRED", "Your access token has expired."


class OriginNotAllowed(GatewayError):
    status_code, code, message = 403, "ORIGIN_NOT_ALLOWED", "Request blocked."


class Forbidden(GatewayError):
    status_code, code, message = 403, "FORBIDDEN", "You do not have permission to do this."


class NotFound(GatewayError):
    status_code, code, message = 404, "NOT_FOUND", "Not found."


class MethodNotAllowed(GatewayError):
    status_code, code, message = 405, "METHOD_NOT_ALLOWED", "Method not allowed."


class PayloadTooLarge(GatewayError):
    status_code, code, message = 413, "PAYLOAD_TOO_LARGE", "Request body is too large."

    def __init__(self, limit: int) -> None:
        super().__init__(details=[{"limit_bytes": limit}])


class UriTooLong(GatewayError):
    status_code, code, message = 414, "URI_TOO_LONG", "Request URL is too long."


class RateLimited(GatewayError):
    status_code, code = 429, "RATE_LIMITED"

    def __init__(self, policy: str, retry_after: int) -> None:
        super().__init__(f"Too many requests. Try again in {retry_after} seconds.",
                         details=[{"policy": policy}], headers={"Retry-After": str(retry_after)})


class InternalError(GatewayError):
    """A bug in the gateway. Reserved for that: wrapped upstream failures use UpstreamError (D5)."""

    status_code, code, message = 500, "INTERNAL_ERROR", "Something went wrong."


class _UpstreamBase(GatewayError):
    def __init__(self, upstream: str) -> None:
        super().__init__(details=[{"upstream": upstream}])


class UpstreamUnavailable(_UpstreamBase):
    status_code, code, message = 502, "UPSTREAM_UNAVAILABLE", "The service is unavailable. Try again shortly."


class UpstreamNotDeployed(_UpstreamBase):
    status_code, code, message = 503, "UPSTREAM_NOT_DEPLOYED", "This part of the system is not available yet."


class GatewayBusy(_UpstreamBase):
    status_code, code, message = 503, "GATEWAY_BUSY", "The system is busy. Try again shortly."


class UpstreamTimeout(_UpstreamBase):
    status_code, code, message = 504, "UPSTREAM_TIMEOUT", "The service took too long to respond."


class UpstreamError(GatewayError):
    """A 5xx from an upstream that was not a JSON envelope (D5). Keeps the upstream's status."""

    code, message = "UPSTREAM_ERROR", "The service returned an unexpected error."

    def __init__(self, upstream: str, upstream_status: int) -> None:
        super().__init__(status_code=upstream_status,
                         details=[{"upstream": upstream, "upstream_status": upstream_status}])


class NotReady(GatewayError):
    """The gateway's own /ready is failing."""

    status_code, code, message = 503, "NOT_READY", "Service unavailable."
