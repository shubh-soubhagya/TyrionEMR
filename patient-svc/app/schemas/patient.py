"""Patient request/response models (LLD §11.2, §11.3). Messages are the ones the prototype shows."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from app.schemas.common import AllergyStatus, OptStr, Out, Sex, Stage, Strict

PHONE_RE = re.compile(r"^[+0-9 ()-]{7,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _phone(v: str | None) -> str | None:
    if v is not None and not PHONE_RE.match(v):
        raise ValueError("Use digits, spaces and + only (7 to 20 characters).")
    return v


def _email(v: str | None) -> str | None:
    if v is not None and (len(v) > 254 or not EMAIL_RE.match(v)):
        raise ValueError("Enter a valid email address.")
    return v


Name = Annotated[str, Field(min_length=1, max_length=60)]
Phone = Annotated[OptStr, AfterValidator(_phone)]
Email = Annotated[OptStr, AfterValidator(_email)]
Address = Annotated[OptStr, Field(max_length=300)]
History = Annotated[OptStr, Field(max_length=4000)]


class PatientCreate(Strict):
    first_name: Name
    last_name: Name
    date_of_birth: date
    sex: Sex
    phone: Phone = None
    email: Email = None
    address: Address = None
    past_medical_history: History = None
    family_history: History = None
    social_history: History = None
    allergy_status: Literal["unknown", "nka"] = "unknown"      # specific allergies are added afterwards

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _required_name(cls, v: object, info) -> object:
        if isinstance(v, str) and not v.strip():
            label = "First name" if info.field_name == "first_name" else "Last name"
            raise ValueError(f"{label} is required.")
        return v


class PatientPatch(Strict):
    version: int = Field(ge=1)
    first_name: Name | None = None
    last_name: Name | None = None
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone: Phone = None
    email: Email = None
    address: Address = None
    past_medical_history: History = None
    family_history: History = None
    social_history: History = None
    allergy_status: Literal["unknown", "nka"] | None = None     # has_allergies is derived, never accepted
    established_ckd_stage: Stage | None = None

    @model_validator(mode="after")
    def _required_not_null(self) -> PatientPatch:
        # null clears an optional field, but first_name/last_name/date_of_birth/sex/allergy_status cannot be null
        for name in ("first_name", "last_name", "date_of_birth", "sex", "allergy_status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class PrimaryDiagnosisBrief(Out):
    icd10_code: str | None
    description: str


class PrimaryDiagnosis(PrimaryDiagnosisBrief):
    id: uuid.UUID


class PatientListItem(Out):
    id: uuid.UUID
    mrn: str
    first_name: str
    last_name: str
    age: int
    sex: str
    phone: str | None
    primary_diagnosis: PrimaryDiagnosisBrief | None
    established_ckd_stage: str | None
    allergy_status: AllergyStatus
    last_visit: datetime | None


class PatientList(Out):
    items: list[PatientListItem]
    page: int
    size: int
    total: int


class AllergyBrief(Out):
    id: uuid.UUID
    allergen: str
    severity: str


class Counts(Out):
    conditions: int
    active_conditions: int
    active_medications: int
    encounters: int


class PatientDetail(Out):
    id: uuid.UUID
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: date
    age: int
    sex: str
    phone: str | None
    email: str | None
    address: str | None
    past_medical_history: str | None
    family_history: str | None
    social_history: str | None
    allergy_status: AllergyStatus
    allergy_summary: list[AllergyBrief]
    established_ckd_stage: str | None
    primary_diagnosis: PrimaryDiagnosis | None
    counts: Counts
    last_visit: datetime | None
    next_follow_up: date | None
    version: int
    created_at: datetime
    updated_at: datetime


class ListQuery(Strict):
    q: str | None = Field(None, max_length=100)
    sex: Sex | None = None
    stage: Stage | Literal["none"] | None = None
    ids: list[uuid.UUID] | None = None
    sort: Literal["name", "mrn", "age", "dx", "visit"] | None = None
    dir: Literal["asc", "desc"] | None = None
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
