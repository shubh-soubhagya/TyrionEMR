"""API DTOs and rendering for /ai/** (LLD B12.3-B12.5, B10.8).

``render`` turns a stored row (and, for a cache hit, its original) into the response contract. The disclaimer is
server text, never model text; the context ``ref_index`` (which holds target UUIDs) is never returned.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

DISCLAIMER = ("AI-generated summary for clinician review only. It may be incomplete or inaccurate. It is not a "
              "diagnosis or treatment recommendation. Verify against the patient record.")

ERROR_MESSAGES = {
    "UPSTREAM_UNAVAILABLE": "The patient record or lab results could not be loaded. Try again in a moment.",
    "UPSTREAM_TIMEOUT": "Loading the record took too long. Try again in a moment.",
    "PATIENT_NOT_FOUND": "This patient record is no longer available.",
    "LLM_TIMEOUT": "The AI service did not respond in time. Calculated facts and rule findings are shown.",
    "LLM_UNAVAILABLE": "The AI service is unavailable. Calculated facts and rule findings are shown.",
    "LLM_RATE_LIMITED": "The AI service is at its usage limit. Calculated facts and rule findings are shown.",
    "LLM_CIRCUIT_OPEN": "The AI service is temporarily unavailable. Calculated facts and rule findings are shown.",
    "LLM_BUSY": "The AI service is busy. Calculated facts and rule findings are shown.",
    "LLM_INVALID_OUTPUT": "The AI response could not be verified, so it is not shown. "
                          "Calculated facts and rule findings are shown.",
    "JOB_TIMEOUT": "The summary was interrupted. Try again.",
    "JOB_ABORTED": "The summary was interrupted. Try again.",
    "INTERNAL_ERROR": "Something went wrong. Try again.",
}


class StepOut(BaseModel):
    key: str
    label: str
    state: str
    ms: int | None = None
    note: str | None = None


class StartOut(BaseModel):
    summary_id: UUID
    patient_id: UUID
    status: str
    deduplicated: bool
    poll_after_ms: int = 1000
    progress: list[StepOut]


class SummaryOut(BaseModel):
    summary_id: UUID
    patient_id: UUID
    status: str
    cached: bool
    cached_from: UUID | None
    as_of: date | None
    generated_at: datetime | None
    progress: list[StepOut] | None = None
    facts: dict[str, Any] | None
    gaps: dict[str, Any] | None
    ai: dict[str, Any] | None
    sources: dict[str, Any] | None
    validation: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    disclaimer: str = DISCLAIMER
    context: dict[str, Any] | None = None


class HistoryOut(BaseModel):
    items: list[SummaryOut]
    page: int
    size: int
    total: int


def render_progress(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A failed row whose progress still shows a running step renders that step as failed (the reaper does not
    rewrite the progress JSON, B10.7)."""
    steps = [dict(s) for s in row["progress"]]
    if row["status"] != "running":
        for s in steps:
            if s["state"] == "running":
                s["state"] = "failed"
    return steps


def _ai_block(src: Mapping[str, Any]) -> dict[str, Any]:
    return {"provenance": "ai_generated", "provider": src["provider"], "model": src["model"],
            "prompt_version": src["prompt_version"], "content": src["output"],
            "grounding_warnings": (src["validation"] or {}).get("grounding_warnings", [])}


def render(row: Mapping[str, Any], original: Mapping[str, Any] | None = None, *, include_context: bool = False,
           progress: bool = True) -> dict[str, Any]:
    status = row["status"]
    src = original or row                         # a cache hit shows the original's content
    out: dict[str, Any] = {
        "summary_id": row["id"], "patient_id": row["patient_id"], "status": status,
        "cached": row["cached_from"] is not None, "cached_from": row["cached_from"], "as_of": None,
        "generated_at": None, "progress": render_progress(row) if progress else None, "facts": None, "gaps": None,
        "ai": None, "sources": None, "validation": None, "error_code": row["error_code"], "error_message": None,
        "disclaimer": DISCLAIMER, "context": None}
    if status in ("completed", "degraded"):
        out |= {"facts": src["facts"], "gaps": src["gaps"], "generated_at": src["finished_at"]}
        snap = src["context_snapshot"] or {}
        as_of = (snap.get("packet") or {}).get("as_of")
        out["as_of"] = date.fromisoformat(as_of) if as_of else None
    if status == "completed":
        out |= {"ai": _ai_block(src), "sources": src["sources"], "validation": src["validation"]}
    elif status == "degraded":
        out["ai"] = {"provenance": "ai_generated", "content": None, "unavailable": True}
    if row["error_code"]:
        out["error_message"] = ERROR_MESSAGES.get(row["error_code"], ERROR_MESSAGES["INTERNAL_ERROR"])
    if include_context and src["context_snapshot"]:
        snap = src["context_snapshot"]
        out["context"] = {"packet": snap.get("packet"), "tool_results": snap.get("tool_results", [])}
    return out
