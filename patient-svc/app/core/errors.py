"""Uniform error envelope (HLD-v2 §12) and the exception handlers that produce it."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

log = logging.getLogger("patient.errors")

_HTTP_CODES = {
    400: "MALFORMED_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
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
    # Deliberately omit each error's "input": it can contain PHI.
    details = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", ()) if p != "body"]
        # LLD §18.1 shape: field + issue. Never the submitted value ("input").
        msg = str(e.get("msg", "Invalid value.")).removeprefix("Value error, ")
        details.append({"field": ".".join(loc), "issue": msg})
    return error_response(422, "VALIDATION_ERROR", "Request validation failed.", details)


def install_exception_handlers(app: FastAPI) -> None:
    # The catch-all for unexpected exceptions lives in RequestContextMiddleware so the 500
    # still carries X-Request-ID (Starlette's ServerErrorMiddleware sits outside our middleware).
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# patient-svc error classes (LLD §18.2). Domain errors (VERSION_CONFLICT, ENCOUNTER_FINAL, ...)
# are added with the phase that needs them.
# --------------------------------------------------------------------------------------
class Unauthenticated(AppError):
    status_code, code, message = 401, "UNAUTHENTICATED", "Please sign in."


class TokenExpired(AppError):
    status_code, code, message = 401, "UNAUTHENTICATED", "Your access token has expired."


class Forbidden(AppError):
    status_code, code, message = 403, "FORBIDDEN", "You do not have permission to do this."


class NotFound(AppError):
    status_code, code, message = 404, "NOT_FOUND", "Not found."


class DbUnavailable(AppError):
    """Pool exhausted, lock/statement timeout, connection refused (§18.3)."""

    status_code, code = 503, "DB_UNAVAILABLE"
    message = "The service is busy. Please retry shortly."

    def __init__(self) -> None:
        super().__init__(headers={"Retry-After": "1"})


class NotReady(AppError):
    status_code, code, message = 503, "NOT_READY", "Service unavailable."


class ValidationFailed(AppError):
    """Rule failure that needs context beyond the schema (today, DOB, stored row). ``issues`` = [(field, msg)]."""

    status_code, code, message = 422, "VALIDATION_ERROR", "Some fields need attention."

    def __init__(self, issues: list[tuple[str, str]]) -> None:
        super().__init__(details=[{"field": f, "issue": m} for f, m in issues])


class VersionConflict(AppError):
    status_code, code = 409, "VERSION_CONFLICT"
    message = "This record was changed by someone else. Reload and try again."


class EncounterFinal(AppError):
    status_code, code = 409, "ENCOUNTER_FINAL"
    message = "Final encounters cannot be edited."


class AllergiesPresent(AppError):
    status_code, code = 409, "ALLERGIES_PRESENT"
    message = "The patient has active allergies. Remove them before changing the allergy status."


class DuplicateAllergy(AppError):
    status_code, code = 409, "DUPLICATE_ALLERGY"
    message = "This allergen is already on the list."


class ConditionNotActive(AppError):
    status_code, code = 409, "CONDITION_NOT_ACTIVE"
    message = "Only an active condition can be the primary diagnosis."


class MedicationAlreadyDiscontinued(AppError):
    status_code, code = 409, "MEDICATION_ALREADY_DISCONTINUED"
    message = "This medication is already discontinued."


class PrimaryConflict(AppError):
    status_code, code = 409, "PRIMARY_CONFLICT"
    message = "Another primary diagnosis was set at the same time. Reload and try again."
