"""Refs and the ref index (LLD B5.3, AI-ADR-4). PURE.

The model never sees a UUID: every citable item gets a short, deterministic ref (``cond:2``, ``lab:K:2026-11-06``)
and a server-side ``RefIndex`` maps each ref to its record. A ref the index cannot resolve was invented.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.clients.models import ChartAllergy, ChartCondition, ChartMedication, EncounterIndex
from app.insights.rules.gaps import fmt_date

REF_PATTERN = (r"^(?:pt:(?:pmh|fh|sh|allergy_status|stage)|ckd:latest"
               r"|(?:cond|med|alg|enc):[1-9][0-9]{0,2}"
               r"|lab:[A-Z]{1,10}:\d{4}-\d{2}-\d{2}(?:#[2-9])?"
               r"|trend:[A-Z]{1,10}"
               r"|gap:[A-Z_]{3,40}(?:#[2-9])?)$")
REF_RE = re.compile(REF_PATTERN)

FIXED_REFS = {
    "pt:pmh": ("Past medical history", "conditions"), "pt:fh": ("Family history", "conditions"),
    "pt:sh": ("Social history", "conditions"), "pt:allergy_status": ("Allergy status", "overview"),
    "pt:stage": ("Established CKD stage", "overview"), "ckd:latest": ("CKD classification", "labs"),
}


@dataclass(frozen=True)
class RefEntry:
    type: str
    target_id: str | None
    label: str
    tab: str


class RefIndex:
    """ref -> entry. Tool results register into the same index, so refs stay stable across the packet and tools."""

    def __init__(self) -> None:
        self._entries: dict[str, RefEntry] = {}

    def add(self, ref: str, entry: RefEntry) -> str:
        self._entries.setdefault(ref, entry)
        return ref

    def get(self, ref: str) -> RefEntry | None:
        return self._entries.get(ref)

    def __contains__(self, ref: object) -> bool:
        return ref in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def to_json(self) -> dict[str, dict[str, Any]]:
        """Stored in context_snapshot only. Never returned by the API (it holds target UUIDs)."""
        return {r: {"type": e.type, "target_id": e.target_id, "label": e.label, "tab": e.tab}
                for r, e in self._entries.items()}


def is_valid_ref(ref: str) -> bool:
    return bool(REF_RE.match(ref))


class RefBuilder:
    """Deterministic: the same chart always yields the same refs."""

    def __init__(self, tz: ZoneInfo, index: RefIndex | None = None) -> None:
        self.tz = tz
        self.index = index or RefIndex()
        self._lab_refs: dict[UUID, str] = {}
        self._lab_taken: dict[str, UUID] = {}
        self._gap_count: dict[str, int] = {}

    def fixed(self, ref: str, target_id: UUID | None = None) -> str:
        label, tab = FIXED_REFS[ref]
        kind = "pt" if ref.startswith("pt:") else "ckd"
        return self.index.add(ref, RefEntry(kind, str(target_id) if target_id else None, label, tab))

    # ---- ordinals ------------------------------------------------------------------------------
    def conditions(self, items: Sequence[ChartCondition]) -> list[tuple[str, ChartCondition]]:
        """cond:1..n, primary first, then nephrology before comorbidity, then onset descending."""
        ordered = sorted(items, key=lambda c: (not c.is_primary, c.category != "nephrology",
                                               _neg_date(c.onset_date), str(c.id)))
        return [(self.index.add(f"cond:{i}", RefEntry("condition", str(c.id), c.description or "Condition",
                                                      "conditions")), c) for i, c in enumerate(ordered, 1)]

    def medications(self, items: Sequence[ChartMedication]) -> list[tuple[str, ChartMedication]]:
        """med:1..n, active first, then start date descending."""
        ordered = sorted(items, key=lambda m: (m.status != "active", -(m.start_date or date.min).toordinal(),
                                               str(m.id)))
        return [(self.index.add(f"med:{i}", RefEntry("medication", str(m.id), f"{m.name} {m.dose}".strip(), "meds")), m)
                for i, m in enumerate(ordered, 1)]

    def allergies(self, items: Sequence[ChartAllergy]) -> list[tuple[str, ChartAllergy]]:
        ordered = sorted(items, key=lambda a: (a.allergen.casefold(), str(a.id)))
        return [(self.index.add(f"alg:{i}", RefEntry("allergy", str(a.id), f"Allergy: {a.allergen}", "meds")), a)
                for i, a in enumerate(ordered, 1)]

    def encounter_refs(self, index: Sequence[EncounterIndex]) -> dict[UUID, str]:
        """enc:1..n, newest first across the whole encounter index (also the ordering the Overview uses)."""
        ordered = sorted(index, key=lambda e: (e.encounter_date, str(e.id)), reverse=True)
        out: dict[UUID, str] = {}
        for i, e in enumerate(ordered, 1):
            out[e.id] = self.index.add(f"enc:{i}", RefEntry(
                "encounter", str(e.id), f"Encounter, {fmt_date(e.encounter_date, self.tz)}", "encounters"))
        return out

    # ---- dated and keyed refs ------------------------------------------------------------------
    def lab(self, test_code: str, name: str, collected_at: datetime, result_id: UUID) -> str:
        """lab:<TEST>:<YYYY-MM-DD in CLINIC_TZ>, with #2, #3 on a collision. The same result keeps its ref."""
        if result_id in self._lab_refs:
            return self._lab_refs[result_id]
        day = collected_at.astimezone(self.tz).date()
        base, ref, n = f"lab:{test_code}:{day.isoformat()}", "", 1
        while True:
            ref = base if n == 1 else f"{base}#{n}"
            if ref not in self._lab_taken:
                break
            n += 1
        self._lab_taken[ref] = result_id
        self._lab_refs[result_id] = ref
        label = f"{name}, {fmt_date(collected_at, self.tz)}"
        return self.index.add(ref, RefEntry("lab", str(result_id), label, "labs"))

    def trend(self, test_code: str, name: str) -> str:
        return self.index.add(f"trend:{test_code}", RefEntry("trend", None, f"{name} trend", "labs"))

    def gap(self, code: str, message: str) -> str:
        n = self._gap_count.get(code, 0) + 1
        self._gap_count[code] = n
        ref = f"gap:{code}" if n == 1 else f"gap:{code}#{n}"
        return self.index.add(ref, RefEntry("gap", None, message[:60], "ai"))


def _neg_date(value: str | None) -> int:
    try:
        return -date.fromisoformat(value[:10]).toordinal() if value else 0
    except ValueError:
        return 0
