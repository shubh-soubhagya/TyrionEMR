"""Canonical JSON and the summary cache key (LLD B5.6, AI-ADR-3). PURE.

patient_id is part of the hash AND of the cache lookup WHERE: two patients with near-empty charts can produce the
same packet, and must never be served each other's summary.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class HashInputs:
    packet_version: str
    prompt_version: str
    schema_version: str
    rules_version: str
    provider: str
    model: str
    tools_enabled: bool


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return format(o.normalize(), "f")          # Decimal("38.0") and 38 hash the same
    if isinstance(o, UUID):
        return str(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default).encode("utf-8")


def context_hash(patient_id: UUID, packet: dict[str, Any], h: HashInputs) -> str:
    material = {"patient_id": str(patient_id), "packet": packet, **asdict(h)}
    return hashlib.sha256(canonical(material)).hexdigest()
