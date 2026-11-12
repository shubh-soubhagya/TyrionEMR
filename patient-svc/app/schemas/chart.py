"""Conditions, medications and allergies (LLD §11.5-11.7)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.common import ICD10, AllergyStatus, Category, OptStr, Out, Strict

# ------------------------------- conditions ------------------------------------------------------
Description = Annotated[str, Field(min_length=1, max_length=160)]


class ConditionCreate(Strict):
    icd10_code: ICD10 | None = None
    description: Description
    category: Category
    onset_date: date | None = None
    is_primary: bool = False


class ConditionPatch(Strict):
    # is_primary: false is rejected (choose another primary or resolve instead), hence Literal[True]
    is_primary: Literal[True] | None = None
    status: Literal["active", "resolved"] | None = None
    description: Description | None = None
    icd10_code: ICD10 | None = None
    onset_date: date | None = None
    category: Category | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> ConditionPatch:
        if not self.model_fields_set:
            raise ValueError("Nothing to update.")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("Description is required.")
        return self


class ConditionOut(Out):
    id: uuid.UUID
    icd10_code: str | None
    description: str
    category: str
    is_primary: bool
    status: str
    onset_date: date | None
    resolved_date: date | None
    source_encounter_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConditionPatchResult(ConditionOut):
    primary_cleared: bool = False


class ConditionList(Out):
    items: list[ConditionOut]


# ------------------------------- medications -----------------------------------------------------
Route = Literal["oral", "sc", "iv", "topical", "inhaled", "other"]


class MedicationCreate(Strict):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    dose: Annotated[str, Field(min_length=1, max_length=40)]
    route: Route = "oral"
    frequency: Annotated[str, Field(min_length=1, max_length=80)]
    start_date: date | None = None
    end_date: date | None = None


class MedicationPatch(Strict):
    action: Literal["discontinue"] | None = None
    dose: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    frequency: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    route: Route | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> MedicationPatch:
        if not self.model_fields_set:
            raise ValueError("Nothing to update.")
        return self


class MedicationOut(Out):
    id: uuid.UUID
    name: str
    dose: str
    route: str
    frequency: str
    start_date: date | None
    end_date: date | None
    status: str
    created_at: datetime
    updated_at: datetime


class MedicationList(Out):
    items: list[MedicationOut]


# ------------------------------- allergies -------------------------------------------------------
class AllergyCreate(Strict):
    allergen: Annotated[str, Field(min_length=1, max_length=80)]
    reaction: Annotated[OptStr, Field(max_length=200)] = None
    severity: Literal["mild", "moderate", "severe"] = "moderate"


class AllergyOut(Out):
    id: uuid.UUID
    allergen: str
    reaction: str | None
    severity: str
    created_at: datetime


class AllergyList(Out):
    allergy_status: AllergyStatus
    items: list[AllergyOut]


class AllergyCreated(Out):
    allergy: AllergyOut
    allergy_status: AllergyStatus
    patient_version: int


class AllergyRemoved(Out):
    allergy_status: AllergyStatus
    patient_version: int
