"""Strict model of the LLM output (LLD B9.2). PURE.

There is deliberately no field for a diagnosis, a drug, a dose or an order (HLD 10.6): the model can only write
narrative sections and follow-up *considerations*, each tied to source refs.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.context.refs import REF_PATTERN

SCHEMA_VERSION = "out-1"

Ref = Annotated[str, StringConstraints(pattern=REF_PATTERN, max_length=48)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Section(Strict):
    text: str = Field(min_length=1, max_length=1200)
    source_refs: list[Ref] = Field(default_factory=list, max_length=12)


class FollowUp(Strict):
    consideration: str = Field(min_length=3, max_length=300)
    rationale: str = Field(min_length=3, max_length=400)
    source_refs: list[Ref] = Field(min_length=1, max_length=8)


class SummaryOutput(Strict):
    history_summary: Section
    comorbidity_summary: Section
    trend_commentary: Section
    abnormal_commentary: Section
    follow_up_considerations: list[FollowUp] = Field(default_factory=list, max_length=6)
    not_documented: list[Annotated[str, StringConstraints(min_length=2, max_length=80)]] = Field(
        default_factory=list, max_length=10)


def json_schema() -> dict:
    """The JSON Schema rendering stored as prompts/<version>/output_schema.json."""
    return SummaryOutput.model_json_schema()
