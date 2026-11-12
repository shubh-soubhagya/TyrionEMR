from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_id: Mapped[uuid.UUID]
    patient_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    resource: Mapped[str]
    resource_id: Mapped[uuid.UUID | None]
    at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    request_id: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
