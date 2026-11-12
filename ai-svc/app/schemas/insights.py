"""API DTOs for /insights/** (LLD B12.6-B12.8). The contract, separate from the rule-engine dataclasses."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class EvidenceOut(BaseModel):
    ref: str
    type: str
    label: str
    tab: str
    target_id: str | None = None


class FindingOut(BaseModel):
    code: str
    severity: Literal["high", "medium", "low"]
    kind: Literal["missing", "inconsistent"]
    message: str
    evidence: list[EvidenceOut]


class ReasonOut(BaseModel):
    severity: Literal["danger", "warn"]
    code: str
    text: str


class AttentionOut(BaseModel):
    needs_attention: bool
    reasons: list[ReasonOut]


class GapsOut(BaseModel):
    patient_id: UUID
    as_of: date
    rules_version: str
    provenance: Literal["rule_engine"] = "rule_engine"
    counts: dict[str, int]
    findings: list[FindingOut]
    attention: AttentionOut


class KpisOut(BaseModel):
    patients: int
    need_attention: int
    critical_results: int
    rapid_decline: int


class AttentionRowOut(BaseModel):
    patient_id: UUID
    mrn: str
    name: str
    age: int
    reasons: list[ReasonOut]


class AbnormalResultOut(BaseModel):
    patient_id: UUID
    name: str
    mrn: str
    test: str
    test_name: str
    value: float
    unit: str
    flag: str
    collected_at: datetime
    result_id: UUID


class DashboardOut(BaseModel):
    as_of: date
    generated_at: datetime
    rules_version: str
    kpis: KpisOut
    attention: list[AttentionRowOut]
    egfr_distribution: dict[str, int]
    abnormal_results: list[AbnormalResultOut]


class WorklistItemOut(BaseModel):
    patient_id: UUID
    rank: int
    reasons: list[ReasonOut]


class WorklistOut(BaseModel):
    as_of: date
    generated_at: datetime
    items: list[WorklistItemOut]
    total: int
