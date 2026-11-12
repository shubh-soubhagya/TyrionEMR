"""Problem-list rules (LLD §13.5, §13.6). Pure functions."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Category = Literal["nephrology", "comorbidity"]

# The prototype used ^(N|Q61|M32). That files E11.21 (diabetic nephropathy) under comorbidity while the seed
# data files it as nephrology, so E1x.2 and I12/I13 are added and M32 is narrowed to M32.1x (§13.6).
NEPHROLOGY_PREFIXES = ("N", "Q61", "M32.1", "E10.2", "E11.2", "E13.2", "I12", "I13")


def infer_category(icd10: str | None) -> Category:
    if icd10 and icd10.upper().startswith(NEPHROLOGY_PREFIXES):
        return "nephrology"
    return "comorbidity"


@dataclass(frozen=True)
class ConditionRef:
    id: UUID
    icd10_code: str | None
    description: str
    status: str


@dataclass(frozen=True)
class LinkDecision:
    kind: Literal["linked", "reactivated", "added"]
    condition: ConditionRef | None      # None when a new condition must be inserted


def resolve_link(icd10: str | None, description: str, existing: Sequence[ConditionRef]) -> LinkDecision:
    """First matching rule wins (§13.5): same ICD active -> link; same ICD resolved -> reactivate;
    no ICD and same description active -> link; otherwise add."""
    if icd10:
        active = next((c for c in existing if c.status == "active" and c.icd10_code == icd10), None)
        if active:
            return LinkDecision("linked", active)
        resolved = next((c for c in existing if c.status == "resolved" and c.icd10_code == icd10), None)
        if resolved:
            return LinkDecision("reactivated", resolved)
    else:
        wanted = description.strip().lower()
        same = next((c for c in existing if c.status == "active" and c.description.strip().lower() == wanted), None)
        if same:
            return LinkDecision("linked", same)
    return LinkDecision("added", None)
