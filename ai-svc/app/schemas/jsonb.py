"""Pydantic models for the JSON columns (LLD B3.5). Every JSON value is validated by one of these before it is
written, so the database never holds a shape the API cannot render."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StepState = Literal["pending", "running", "done", "skipped", "failed"]

# The seven visible steps of the pipeline (HLD 10.3), always in this order.
STEP_LABELS: tuple[tuple[str, str], ...] = (
    ("open_chart", "Opening the chart"),
    ("gather", "Reading the chart and lab results"),
    ("rules", "Calculating trends and checking for gaps"),
    ("prepare", "Preparing what the AI will see"),
    ("write", "Writing the summary"),
    ("check", "Checking the summary"),
    ("save", "Saving"),
)


class ProgressStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    state: StepState = "pending"
    ms: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=200)


def initial_progress() -> list[dict]:
    """Seven steps, the first running, the rest pending (what POST returns and stores)."""
    steps = [ProgressStep(key=k, label=label) for k, label in STEP_LABELS]
    steps[0] = steps[0].model_copy(update={"state": "running"})
    return [s.model_dump() for s in steps]


def validate_progress(steps: list[dict]) -> list[dict]:
    """Raises ValueError unless there are exactly the seven steps in order."""
    parsed = [ProgressStep.model_validate(s) for s in steps]
    if [s.key for s in parsed] != [k for k, _ in STEP_LABELS]:
        raise ValueError("progress must list the seven steps in order")
    return [s.model_dump() for s in parsed]


class ValidationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_valid: bool
    refs_total: int = 0
    refs_resolved: int = 0
    refs_stripped: int = 0
    grounding_warnings: list[str] = Field(default_factory=list)
    safety_flags: int = 0
    safety_warnings: int = 0
    safety_redactions: list[str] = Field(default_factory=list)
    attempts: int = 1
    repaired: bool = False
    repair_reasons: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    tokens_estimated: bool = False
