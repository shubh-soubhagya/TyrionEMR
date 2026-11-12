"""Maps database errors to the error catalog (LLD §18.3). One handler for every route.

Constraint names come from asyncpg (``constraint_name``), trigger hints from ``hint``. The statement and
its parameters are never logged: they can contain PHI.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core.errors import (
    AlreadyCorrected,
    AppError,
    DbUnavailable,
    NotFound,
    error_response,
)
from app.core.metrics import DB_TRIGGER_REJECTIONS

log = logging.getLogger("lab.db")

# 55P03 lock_not_available (lock_timeout), 57014 query_canceled (statement_timeout),
# 25P03 idle_in_transaction_session_timeout, 40P01 deadlock_detected
BUSY_SQLSTATES = frozenset({"55P03", "57014", "25P03", "40P01"})


def _pg_exc(exc: BaseException) -> BaseException:
    """The underlying asyncpg exception (SQLAlchemy wraps it twice)."""
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "__cause__", None) or orig


def sqlstate_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        state = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if state:
            return str(state)
    return None


def map_db_error(exc: BaseException) -> AppError | None:
    """The catalog entry for a database error, or None when it is a genuine server error."""
    state = sqlstate_of(exc)
    pg = _pg_exc(exc)
    hint = getattr(pg, "hint", None)
    if state in BUSY_SQLSTATES:
        return DbUnavailable()
    if state == "23505" and getattr(pg, "constraint_name", None) == "lab_results_one_correction":
        return AlreadyCorrected()      # two corrections raced; the unique index decided
    if state == "23503":
        return NotFound()
    if state == "P0001" and hint:
        DB_TRIGGER_REJECTIONS.labels(hint=str(hint)).inc()
    return None


async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    mapped = map_db_error(exc)
    state = sqlstate_of(exc)
    if mapped is not None:
        if isinstance(mapped, DbUnavailable):
            log.warning("db.busy", extra={"sqlstate": state})
        return error_response(mapped.status_code, mapped.code, mapped.message, mapped.details, mapped.headers)
    if state == "23514":                              # CHECK violation the service should have caught
        log.error("db.check_violation", extra={"constraint": getattr(_pg_exc(exc), "constraint_name", None)})
        return error_response(422, "VALIDATION_ERROR", "Some fields need attention.")
    log.error("db.error", extra={"sqlstate": state, "error_type": type(exc.orig).__name__}, exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
