"""Maps database timeouts to 503 SERVICE_BUSY instead of a 500 (item 6)."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core.errors import ServiceBusy, error_response

log = logging.getLogger("auth.db")

# 55P03 lock_not_available (lock_timeout), 57014 query_canceled (statement_timeout),
# 25P03 idle_in_transaction_session_timeout, 40P01 deadlock_detected
BUSY_SQLSTATES = frozenset({"55P03", "57014", "25P03", "40P01"})


def sqlstate_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        state = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if state:
            return str(state)
    return None


async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    state = sqlstate_of(exc)
    if state in BUSY_SQLSTATES:
        log.warning("db.busy", extra={"sqlstate": state})     # the SQLSTATE only: never the statement or params
        busy = ServiceBusy()
        return error_response(busy.status_code, busy.code, busy.message, headers=busy.headers)
    log.error("db.error", extra={"sqlstate": state, "error_type": type(exc.orig).__name__}, exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
