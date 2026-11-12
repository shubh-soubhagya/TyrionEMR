from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PatientCondition(Base):
    __tablename__ = "patient_conditions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    icd10_code: Mapped[str | None]
    description: Mapped[str]
    category: Mapped[str]
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))
    status: Mapped[str] = mapped_column(server_default="active")
    onset_date: Mapped[date | None]
    resolved_date: Mapped[date | None]
    source_encounter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("encounters.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
