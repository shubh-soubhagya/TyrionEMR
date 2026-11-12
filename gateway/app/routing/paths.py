"""Path safety (LLD §8.1, §19.1). Pure: no framework imports.

The gateway refuses unsafe paths instead of normalizing them (ADR-G10): normalizing in two parsers
differently is the classic gateway bypass.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

# encoded dot, slash, backslash, NUL, and percent itself (catches double encoding like %252e)
_FORBIDDEN_ENCODED = re.compile(r"%(2e|2f|5c|00|25)", re.IGNORECASE)
# RFC 3986 pchar after decoding (unreserved / sub-delims / ":" / "@")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@-]+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUMERIC = re.compile(r"^\d+$")


class UnsafePath(ValueError):
    """Raised for any path the gateway refuses to route (mapped to 400 INVALID_PATH)."""


def safe_segments(raw_path: str) -> list[str]:
    """Validate the raw (still percent-encoded) path and return its decoded segments.

    Refuses instead of normalizing (ADR-G10). One trailing slash is tolerated; the caller keeps the
    raw path for forwarding, so the upstream sees exactly what the client sent.
    """
    if _FORBIDDEN_ENCODED.search(raw_path):
        raise UnsafePath("encoded dot, slash, backslash, NUL or percent")
    if "\\" in raw_path or "//" in raw_path:
        raise UnsafePath("backslash or empty segment")
    path = unquote(raw_path)
    if not path.startswith("/"):
        raise UnsafePath("relative path")
    segments = path.split("/")[1:]
    if segments and segments[-1] == "":
        segments = segments[:-1]
    for seg in segments:
        if seg in (".", "..") or not _SAFE_SEGMENT.match(seg):
            raise UnsafePath("disallowed segment")
    return segments


def route_template(segments: list[str]) -> str:
    """'/api/labs/patients/{id}/results'. Used for logs, metric labels and policy matching.
    UUIDs and numbers become {id}, so labels have bounded cardinality and no identifiers."""
    return "/" + "/".join("{id}" if (_UUID.match(s) or _NUMERIC.match(s)) else s for s in segments)
