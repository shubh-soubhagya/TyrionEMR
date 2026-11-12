"""ORM mirror of the DDL in migrations/versions/0001_baseline.sql (the SQL is the source of truth, LLD §10)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Computed, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    mrn: Mapped[str] = mapped_column(server_default=text("'PT-' || lpad(nextval('patient_mrn_seq')::text, 6, '0')"))
    first_name: Mapped[str]
    last_name: Mapped[str]
    search_name: Mapped[str] = mapped_column(Computed("lower(first_name || ' ' || last_name)", persisted=True))
    date_of_birth: Mapped[date]
    sex: Mapped[str]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    address: Mapped[str | None]
    past_medical_history: Mapped[str | None]
    family_history: Mapped[str | None]
    social_history: Mapped[str | None]
    allergy_status: Mapped[str] = mapped_column(server_default="unknown")
    established_ckd_stage: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
