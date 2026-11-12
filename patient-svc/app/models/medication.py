from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    name: Mapped[str]
    dose: Mapped[str]
    route: Mapped[str] = mapped_column(server_default="oral")
    frequency: Mapped[str]
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
