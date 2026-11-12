"""Shared schema building blocks (LLD §11.1, §11.9)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints


class Strict(BaseModel):
    """Request models: unknown fields are rejected (mass-assignment protection), strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    """Response models are built from dicts or ORM rows."""

    model_config = ConfigDict(from_attributes=True)


def blank_to_none(value: object) -> object:
    """An optional string that is empty after trimming is stored as NULL (§11.1)."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptStr = Annotated[str | None, BeforeValidator(blank_to_none)]

def _upper(value: object) -> object:
    """Upper-case BEFORE the pattern check (pydantic applies ``to_upper`` after it, so 'n18.32' would fail)."""
    return value.strip().upper() if isinstance(value, str) else value


ICD10 = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")]
Stage = Literal["G1", "G2", "G3a", "G3b", "G4", "G5"]
Sex = Literal["M", "F", "O"]
AllergyStatus = Literal["unknown", "nka", "has_allergies"]
Category = Literal["nephrology", "comorbidity"]


class Page(Out):
    page: int
    size: int
    total: int


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
