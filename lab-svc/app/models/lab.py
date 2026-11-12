"""ORM mirror of 0001_baseline.sql (HLD §5.4). The migration is the source of truth for constraints."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LabTest(Base):
    __tablename__ = "lab_tests"

    code: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    canonical_unit: Mapped[str]
    allowed_units: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decimals: Mapped[int]
    max_value: Mapped[Decimal]
    sort_order: Mapped[int]


class LabReferenceRange(Base):
    __tablename__ = "lab_reference_ranges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    test_code: Mapped[str] = mapped_column(ForeignKey("lab_tests.code"))
    sex: Mapped[str | None]
    age_min: Mapped[int | None]
    age_max: Mapped[int | None]
    low: Mapped[Decimal | None]
    high: Mapped[Decimal | None]
    critical_low: Mapped[Decimal | None]
    critical_high: Mapped[Decimal | None]
    effective_from: Mapped[date]


class LabReport(Base):
    __tablename__ = "lab_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID]
    collected_at: Mapped[datetime]
    lab_name: Mapped[str | None]
    notes: Mapped[str | None]
    entered_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime]


class LabResult(Base):
    __tablename__ = "lab_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_reports.id"))
    patient_id: Mapped[uuid.UUID]
    collected_at: Mapped[datetime]
    test_code: Mapped[str] = mapped_column(ForeignKey("lab_tests.code"))
    value: Mapped[Decimal]
    unit: Mapped[str]
    value_original: Mapped[Decimal]
    unit_original: Mapped[str]
    ref_low: Mapped[Decimal | None]
    ref_high: Mapped[Decimal | None]
    flag: Mapped[str]
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_results.id"))
    created_at: Mapped[datetime]


class PatientLabStatus(Base):
    __tablename__ = "patient_lab_status"

    patient_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    latest: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    egfr_category: Mapped[str | None]
    uacr_category: Mapped[str | None]
    egfr_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    creat_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    egfr_spark: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    has_critical: Mapped[bool] = mapped_column(server_default=text("false"))
    rapid_decline: Mapped[bool] = mapped_column(server_default=text("false"))
    last_result_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))
