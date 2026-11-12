from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Allergy(Base):
    __tablename__ = "allergies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    allergen: Mapped[str]
    reaction: Mapped[str | None]
    severity: Mapped[str] = mapped_column(server_default="moderate")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
    deleted_by: Mapped[uuid.UUID | None]
