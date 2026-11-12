"""Encounter request/response models (LLD §11.8, §11.9)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.domain.encounter_rules import dedupe_symptoms
from app.schemas.common import ICD10, Category, Out, Strict

EncounterType = Literal["new", "follow_up", "emergency"]


def _in_range(value, lo, hi, unit: str):
    if value is not None and not (lo <= value <= hi):
        raise PydanticCustomError("out_of_range", f"Enter {lo} to {hi} {unit}.")
    return value


class VitalsIn(Strict):
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    heart_rate: int | None = None
    temperature_c: Decimal | None = None
    weight_kg: Decimal | None = None

    @field_validator("systolic_bp")
    @classmethod
    def _sys(cls, v: int | None) -> int | None:
        return _in_range(v, 50, 300, "mmHg")

    @field_validator("diastolic_bp")
    @classmethod
    def _dia(cls, v: int | None) -> int | None:
        return _in_range(v, 20, 200, "mmHg")

    @field_validator("heart_rate")
    @classmethod
    def _hr(cls, v: int | None) -> int | None:
        return _in_range(v, 20, 300, "bpm")

    @field_validator("temperature_c")
    @classmethod
    def _temp(cls, v: Decimal | None) -> Decimal | None:
        v = None if v is None else v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)   # round, don't reject
        return _in_range(v, 30, 45, "°C")

    @field_validator("weight_kg")
    @classmethod
    def _wt(cls, v: Decimal | None) -> Decimal | None:
        v = None if v is None else v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return _in_range(v, 1, 500, "kg")

    @model_validator(mode="after")
    def _bp_order(self) -> VitalsIn:
        if self.systolic_bp is not None and self.diastolic_bp is not None and self.systolic_bp <= self.diastolic_bp:
            raise PydanticCustomError("bp_order", "Systolic must be higher than diastolic.")
        return self

    def is_empty(self) -> bool:
        return all(v is None for v in (self.systolic_bp, self.diastolic_bp, self.heart_rate,
                                       self.temperature_c, self.weight_kg))


class DiagnosisIn(Strict):
    icd10_code: ICD10 | None = None
    description: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    add_to_problem_list: bool = False
    category: Category | None = None            # inferred from the ICD-10 code when null (§13.6)

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise PydanticCustomError("description_required", "Each diagnosis needs a description.")
        return v


Symptom = Annotated[str, StringConstraints(min_length=1, max_length=60)]


def _check_diagnoses(diagnoses: list[DiagnosisIn] | None) -> None:
    codes = [d.icd10_code for d in diagnoses or [] if d.icd10_code]
    if len(codes) != len(set(codes)):
        raise PydanticCustomError("dx_duplicate", "The same ICD-10 code appears twice.")


class EncounterBase(Strict):
    encounter_date: AwareDatetime
    encounter_type: EncounterType = "follow_up"
    chief_complaint: Annotated[str | None, Field(max_length=200)] = None
    symptoms: list[Symptom] = Field(default_factory=list, max_length=30)
    examination_notes: Annotated[str | None, Field(max_length=4000)] = None
    assessment: Annotated[str | None, Field(max_length=4000)] = None
    plan: Annotated[str | None, Field(max_length=4000)] = None
    follow_up_date: date | None = None
    vitals: VitalsIn | None = None
    diagnoses: list[DiagnosisIn] = Field(default_factory=list, max_length=20)

    @field_validator("symptoms")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return dedupe_symptoms(v)

    @model_validator(mode="after")
    def _no_duplicate_icd(self) -> EncounterBase:
        _check_diagnoses(self.diagnoses)
        return self


class EncounterCreate(EncounterBase):
    status: Literal["draft", "final"] = "draft"


class EncounterPatch(Strict):
    version: int = Field(ge=1)
    encounter_date: AwareDatetime | None = None
    encounter_type: EncounterType | None = None
    chief_complaint: Annotated[str | None, Field(max_length=200)] = None
    symptoms: list[Symptom] | None = Field(None, max_length=30)
    examination_notes: Annotated[str | None, Field(max_length=4000)] = None
    assessment: Annotated[str | None, Field(max_length=4000)] = None
    plan: Annotated[str | None, Field(max_length=4000)] = None
    follow_up_date: date | None = None
    vitals: VitalsIn | None = None
    diagnoses: list[DiagnosisIn] | None = Field(None, max_length=20)
    status: Literal["draft", "final"] | None = None

    @field_validator("symptoms")
    @classmethod
    def _dedupe(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else dedupe_symptoms(v)

    @model_validator(mode="after")
    def _checks(self) -> EncounterPatch:
        _check_diagnoses(self.diagnoses)
        for name in ("encounter_date", "encounter_type", "symptoms", "diagnoses", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise PydanticCustomError("not_nullable", f"{name} cannot be null.")
        return self


class FinalizeBody(Strict):
    version: int = Field(ge=1)


# ---------------------------------- responses ----------------------------------------------------
class VitalsOut(Out):
    systolic_bp: int | None
    diastolic_bp: int | None
    heart_rate: int | None
    temperature_c: float | None
    weight_kg: float | None


class DiagnosisOut(Out):
    seq: int
    icd10_code: str | None
    description: str
    category: str | None
    add_to_problem_list: bool
    condition_id: uuid.UUID | None


class EncounterDetail(Out):
    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_date: datetime
    encounter_type: str
    clinician_id: uuid.UUID
    clinician_name: str
    chief_complaint: str | None
    symptoms: list[str]
    examination_notes: str | None
    assessment: str | None
    plan: str | None
    follow_up_date: date | None
    vitals: VitalsOut | None
    diagnoses: list[DiagnosisOut]
    status: str
    version: int
    finalized_at: datetime | None
    finalized_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProblemListChanges(Out):
    added: int = 0
    reactivated: int = 0
    linked: int = 0


class EncounterResult(Out):
    encounter: EncounterDetail
    problem_list_changes: ProblemListChanges


class VitalsBrief(Out):
    systolic_bp: int | None
    diastolic_bp: int | None
    heart_rate: int | None


class EncounterListItem(Out):
    id: uuid.UUID
    encounter_date: datetime
    encounter_type: str
    clinician_name: str
    chief_complaint: str | None
    assessment: str | None
    vitals_brief: VitalsBrief | None
    follow_up_date: date | None
    status: str


class EncounterList(Out):
    items: list[EncounterListItem]
    page: int
    size: int
    total: int
