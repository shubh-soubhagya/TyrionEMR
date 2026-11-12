"""JSON logging with a redaction safety net.

Rule: never log emails, passwords, tokens, cookies or Authorization headers. Callers must not pass
them; this module additionally masks well-known keys in structured extras as defense in depth.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id

SENSITIVE_KEYS = frozenset({
    # credentials
    "password", "new_password", "token", "access_token", "refresh_token", "authorization",
    "cookie", "set-cookie", "set_cookie", "email", "secret", "api_key", "token_hash",
    # patient data (PHI): a future ``extra={...}`` must not be able to leak any of it. Matched case-insensitively.
    "first_name", "last_name", "name", "full_name", "patient_name", "phone", "address", "date_of_birth", "dob",
    "mrn", "past_medical_history", "family_history", "social_history", "chief_complaint", "symptoms",
    "examination_notes", "assessment", "plan", "allergen", "reaction", "description", "q",
    # lab data: results are PHI too
    "notes", "value", "value_original", "lab_name",
})
_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                doc[key] = "[redacted]" if key.lower() in SENSITIVE_KEYS else _clean(value)
        if record.exc_info and record.exc_info[0] is not None:
            # Type only: exception messages can echo request data.
            doc["exc_type"] = record.exc_info[0].__name__
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
