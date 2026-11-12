from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ARRAY, ForeignKey, Numeric, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    encounter_date: Mapped[datetime]
    encounter_type: Mapped[str] = mapped_column(server_default="follow_up")
    clinician_id: Mapped[uuid.UUID]
    clinician_name: Mapped[str]
    chief_complaint: Mapped[str | None]
    symptoms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    examination_notes: Mapped[str | None]
    assessment: Mapped[str | None]
    plan: Mapped[str | None]
    follow_up_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="draft")
    version: Mapped[int] = mapped_column(server_default="1")
    finalized_at: Mapped[datetime | None]
    finalized_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]

    # lazy="raise": every load is explicit (selectinload), so no hidden N+1 can appear in an async handler
    vitals: Mapped[EncounterVitals | None] = relationship(lazy="raise", uselist=False)
    diagnoses: Mapped[list[EncounterDiagnosis]] = relationship(lazy="raise", order_by="EncounterDiagnosis.seq")


class EncounterVitals(Base):
    __tablename__ = "encounter_vitals"

    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"), primary_key=True)
    systolic_bp: Mapped[int | None]
    diastolic_bp: Mapped[int | None]
    heart_rate: Mapped[int | None]
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))


class EncounterDiagnosis(Base):
    __tablename__ = "encounter_diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"))
    seq: Mapped[int]
    icd10_code: Mapped[str | None]
    description: Mapped[str]
    category: Mapped[str | None]            # explicit category from the form; NULL = infer from ICD-10 (§13.6)
    add_to_problem_list: Mapped[bool] = mapped_column(server_default=text("false"))
    condition_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient_conditions.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
