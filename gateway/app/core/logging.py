"""JSON logging with a redaction safety net.

Rule: never log emails, passwords, tokens, cookies or Authorization headers. Callers must not pass
them; this module additionally masks well-known keys in structured extras as defense in depth.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id

SENSITIVE_KEYS = frozenset({
    "password", "new_password", "token", "access_token", "refresh_token", "authorization",
    "cookie", "set-cookie", "set_cookie", "email", "secret", "api_key", "token_hash",
})
_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "taskName", "request_id"}

_previous_factory = logging.getLogRecordFactory()


def _stamping_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Capture the request id when the record is CREATED, so it survives handlers that format later."""
    record = _previous_factory(*args, **kwargs)
    record.request_id = get_request_id()
    return record


logging.setLogRecordFactory(_stamping_factory)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _short_path(filename: str) -> str:
    parts = filename.replace("\\", "/").split("/")
    return "/".join(parts[-3:])        # enough to find the file, without leaking the host's directory layout


def _exception_fields(exc_info) -> dict[str, Any]:
    """Type, call stack (file, line, function) and the chain of causes. Deliberately NOT included:
    exception messages (they often echo request data such as an email or a token) and frame locals."""
    exc_type, exc, tb = exc_info
    chain: list[str] = []
    root = exc
    cur = exc
    while cur is not None and len(chain) < 5:
        chain.append(type(cur).__name__)
        root = cur
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)

    def frames(trace) -> list[dict[str, Any]]:
        return [{"file": _short_path(f.filename), "line": f.lineno, "function": f.name}
                for f in traceback.extract_tb(trace)][-25:]

    fields: dict[str, Any] = {"exc_type": exc_type.__name__, "exc_chain": chain, "stack": frames(tb)}
    if root is not exc and root is not None and root.__traceback__ is not None:
        fields["cause_stack"] = frames(root.__traceback__)       # where the original error was raised
    return fields


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                doc[key] = "[redacted]" if key.lower() in SENSITIVE_KEYS else _clean(value)
        if record.exc_info and record.exc_info[0] is not None:
            doc.update(_exception_fields(record.exc_info))
        return json.dumps(doc, separators=(",", ":"), default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn's own access log would duplicate ours (and can leak query strings).
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").handlers[:] = []
    logging.getLogger("uvicorn.error").propagate = True
    # httpx logs every request as "HTTP Request: GET <full url>" at INFO, which would put query strings
    # (patient search text) into the logs. The gateway writes its own access line instead.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
