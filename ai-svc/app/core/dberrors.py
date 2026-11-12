"""Maps database errors to the error catalog (LLD B13). One handler for every route.

``23505`` on ``ux_summaries_running`` is not an error (single-flight, handled in SummaryService); every other
constraint/trigger failure is a bug and answers 500. The statement and its parameters are never logged.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, DbUnavailable, error_response
from app.core.metrics import DB_TRIGGER_REJECTIONS

log = logging.getLogger("ai.db")

# 55P03 lock_not_available, 57014 query_canceled (statement_timeout), 25P03 idle-in-transaction timeout,
# 40P01 deadlock, 08xxx connection failures
BUSY_SQLSTATES = frozenset({"55P03", "57014", "25P03", "40P01"})


def _pg_exc(exc: BaseException) -> BaseException:
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
    state = sqlstate_of(exc)
    if state in BUSY_SQLSTATES or (state or "").startswith("08"):
        return DbUnavailable()
    pg = _pg_exc(exc)
    if state == "P0001" and getattr(pg, "hint", None):
        DB_TRIGGER_REJECTIONS.labels(hint=str(pg.hint)).inc()
    return None


async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    mapped = map_db_error(exc)
    state = sqlstate_of(exc)
    if mapped is not None:
        log.warning("db.busy", extra={"sqlstate": state})
        return error_response(mapped.status_code, mapped.code, mapped.message, mapped.details, mapped.headers)
    log.error("db.error", extra={"sqlstate": state, "constraint": getattr(_pg_exc(exc), "constraint_name", None),
                                 "error_type": type(exc.orig).__name__}, exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
