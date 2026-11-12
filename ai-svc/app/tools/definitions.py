"""The six read-only tools (LLD B8.1). ``patient_id`` is NEVER a tool argument: the registry binds it from the job, so
a successful prompt injection cannot read another patient. Results are whitelisted, scrubbed, given refs by the same
RefBuilder as the packet, and capped.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.clients.lab import LabClient
from app.clients.patient import PatientClient
from app.context.minimize import clean_text
from app.context.packet import num, reference_text
from app.context.refs import RefBuilder, RefEntry
from app.insights.rules.constants import TEST_NAMES

TestCode = Literal["CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"]
ROW_CAP = 50


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoArgs(Args):
    pass


class ConditionsArgs(Args):
    status: Literal["active", "resolved"] | None = None


class EncountersArgs(Args):
    limit: int = Field(default=3, ge=1, le=5)
    include_notes: bool = True


class LabHistoryArgs(Args):
    test_code: TestCode
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LabTrendArgs(Args):
    test_code: TestCode


@dataclass
class Deps:
    patients: PatientClient
    labs: LabClient


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[Any, Any, Deps], Awaitable[Any]]                        # (args, job, deps) -> raw
    shape: Callable[[Any, Any, Any, int], dict[str, Any]]                  # (raw, job, args, max_bytes) -> result

    def parameters(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema(by_alias=True)
        schema.pop("title", None)
        return schema


# ---- shaping helpers ---------------------------------------------------------------------------
def _size(d: dict[str, Any]) -> int:
    return len(json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str))


def cap_rows(data: dict[str, Any], key: str, max_bytes: int) -> dict[str, Any]:
    """Rows are dropped from the end until the result fits; ``truncated`` tells the model (and the audit) so."""
    data.setdefault("truncated", False)
    rows: list[Any] = data[key]
    if len(rows) > ROW_CAP:
        del rows[ROW_CAP:]
        data["truncated"] = True
    while rows and _size(data) > max_bytes:
        rows.pop()
        data["truncated"] = True
    return data


def _ref(refs: RefBuilder, prefix: str, kind: str, target: str, label: str, tab: str) -> str:
    """Reuses the ref the packet already gave this record; registers a new one otherwise."""
    existing = refs.index.ref_for_target(kind, target)
    if existing:
        return existing
    return refs.index.add(f"{prefix}:{refs.index.next_ordinal(prefix)}", RefEntry(kind, target, label, tab))


# ---- get_conditions ----------------------------------------------------------------------------
async def run_conditions(args: ConditionsArgs, job: Any, d: Deps) -> dict:
    params = {"status": args.status} if args.status else None
    return await d.patients.tool(job.patient_id, "conditions", job.call, params)


def shape_conditions(raw: dict, job: Any, args: Any, max_bytes: int) -> dict[str, Any]:
    items = [{"ref": _ref(job.refs, "cond", "condition", str(c["id"]), c.get("description") or "Condition",
                          "conditions"),
              "icd10": c.get("icd10_code"), "description": c.get("description"), "category": c.get("category"),
              "primary": c.get("is_primary"), "status": c.get("status"), "onset": c.get("onset_date"),
              "resolved": c.get("resolved_date")} for c in raw.get("items", [])]
    return cap_rows({"items": items, "truncated": bool(raw.get("truncated"))}, "items", max_bytes)


# ---- get_medications_and_allergies -------------------------------------------------------------
async def run_meds(args: NoArgs, job: Any, d: Deps) -> dict:
    return await d.patients.tool(job.patient_id, "medications-allergies", job.call)


def shape_meds(raw: dict, job: Any, args: Any, max_bytes: int) -> dict[str, Any]:
    meds = [{"ref": _ref(job.refs, "med", "medication", str(m["id"]),
                         f"{m.get('name', '')} {m.get('dose', '')}".strip(), "meds"),
             "name": m.get("name"), "dose": m.get("dose"), "route": m.get("route"), "frequency": m.get("frequency"),
             "status": m.get("status"), "start": m.get("start_date"), "end": m.get("end_date")}
            for m in raw.get("medications", [])]
    alg = [{"ref": _ref(job.refs, "alg", "allergy", str(a["id"]), f"Allergy: {a.get('allergen', '')}", "meds"),
            "allergen": a.get("allergen"), "reaction": a.get("reaction"), "severity": a.get("severity")}
           for a in raw.get("allergies", [])]
    data = {"medications": meds, "allergies": alg, "truncated": bool(raw.get("truncated"))}
    while _size(data) > max_bytes and (data["medications"] or data["allergies"]):
        (data["medications"] if len(data["medications"]) >= len(data["allergies"]) else data["allergies"]).pop()
        data["truncated"] = True
    return data


# ---- get_recent_encounters ---------------------------------------------------------------------
async def run_encounters(args: EncountersArgs, job: Any, d: Deps) -> dict:
    return await d.patients.tool(job.patient_id, "encounters", job.call,
                                 {"limit": args.limit, "include_notes": str(args.include_notes).lower()})


def shape_encounters(raw: dict, job: Any, args: EncountersArgs, max_bytes: int) -> dict[str, Any]:
    items = []
    for e in raw.get("items", []):
        if e.get("status") == "draft":
            continue                                           # drafts are never shown to the model (AI-ADR-10)
        day = str(e.get("encounter_date", ""))[:10]
        item: dict[str, Any] = {
            "ref": _ref(job.refs, "enc", "encounter", str(e["id"]), f"Encounter, {day}", "encounters"),
            "date": day, "type": e.get("encounter_type"), "chief_complaint": clean_text(e.get("chief_complaint")),
            "symptoms": [clean_text(s) for s in e.get("symptoms", []) if s], "follow_up": e.get("follow_up_date"),
            "vitals": e.get("vitals"),
            "diagnoses": [{"icd10": x.get("icd10_code"), "description": x.get("description")}
                          for x in e.get("diagnoses", [])]}
        if args.include_notes:
            item |= {"examination": clean_text(e.get("examination_notes")),
                     "assessment": clean_text(e.get("assessment")), "plan": clean_text(e.get("plan"))}
        items.append(item)
    return cap_rows({"items": items, "truncated": bool(raw.get("truncated"))}, "items", max_bytes)


# ---- get_lab_history ---------------------------------------------------------------------------
async def run_lab_history(args: LabHistoryArgs, job: Any, d: Deps) -> dict:
    return await d.labs.results(job.patient_id, job.call, test=args.test_code,
                                date_from=args.from_.isoformat() if args.from_ else None,
                                date_to=args.to.isoformat() if args.to else None, size=ROW_CAP)


def _lab_row(refs: RefBuilder, code: str, result_id: str | None, at: Any, value: float, unit: str, flag: str,
             low: Any, high: Any) -> dict[str, Any]:
    from datetime import datetime
    when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    ref = refs.lab(code, TEST_NAMES.get(code, code), when, UUID(str(result_id))) if result_id else None
    return {"ref": ref, "test": code, "date": when.astimezone(refs.tz).date().isoformat(), "value": num(value),
            "unit": unit, "flag": flag, "reference": reference_text(*_dec(low, high))}


def _dec(low: Any, high: Any):
    from decimal import Decimal
    return (Decimal(str(low)) if low is not None else None, Decimal(str(high)) if high is not None else None)


def shape_lab_history(raw: dict, job: Any, args: LabHistoryArgs, max_bytes: int) -> dict[str, Any]:
    rows = [_lab_row(job.refs, i.get("test_code", args.test_code), i.get("id"), i["collected_at"], i["value"],
                     i.get("unit", ""), i.get("flag", "unknown"), i.get("ref_low"), i.get("ref_high"))
            for i in raw.get("items", []) if not i.get("superseded")]
    rows = [r for r in rows if r["ref"]]
    truncated = bool(raw.get("truncated")) or int(raw.get("total", len(rows))) > len(rows)
    return cap_rows({"test": args.test_code, "items": rows, "truncated": truncated}, "items", max_bytes)


# ---- get_lab_trend -----------------------------------------------------------------------------
async def run_lab_trend(args: LabTrendArgs, job: Any, d: Deps) -> Any:
    return await d.labs.trends(job.patient_id, job.call, (args.test_code,))


def shape_lab_trend(raw: Any, job: Any, args: LabTrendArgs, max_bytes: int) -> dict[str, Any]:
    series = next((s for s in raw.series if s.test_code == args.test_code), None)
    if series is None or series.stats is None or series.stats.n == 0:
        return {"test": args.test_code, "trend": None, "points": [], "truncated": False}
    st = series.stats
    trend = {"ref": job.refs.trend(args.test_code, TEST_NAMES.get(args.test_code, args.test_code)), "n": st.n,
             "first": num(st.first), "last": num(st.last), "abs_change": num(st.abs_change),
             "pct_change": num(st.pct_change), "slope_per_year": num(st.slope_per_year), "direction": st.direction,
             "rapid_decline": st.rapid_decline, "span_days": st.span_days}
    ref = series.reference
    points = [_lab_row(job.refs, args.test_code, str(p.result_id) if p.result_id else None, p.collected_at, p.value,
                       series.unit, p.flag, ref.low if ref else None, ref.high if ref else None)
              for p in series.points]
    return cap_rows({"test": args.test_code, "trend": trend, "points": [p for p in points if p["ref"]],
                     "truncated": False}, "points", max_bytes)


# ---- get_gap_report (no I/O) -------------------------------------------------------------------
async def run_gap_report(args: NoArgs, job: Any, d: Deps) -> dict:
    return job.gaps or {"findings": []}


def shape_gap_report(raw: dict, job: Any, args: Any, max_bytes: int) -> dict[str, Any]:
    items = [{"ref": f["ref"], "code": f["code"], "severity": f["severity"], "kind": f["kind"],
              "message": f["message"]} for f in raw.get("findings", [])]
    return cap_rows({"items": items, "truncated": False}, "items", max_bytes)


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("get_conditions", "List the patient's recorded conditions, optionally only active or resolved ones.",
             ConditionsArgs, run_conditions, shape_conditions),
    ToolSpec("get_medications_and_allergies", "List the patient's recorded medications and allergies.",
             NoArgs, run_meds, shape_meds),
    ToolSpec("get_recent_encounters", "Recent finalized encounters with notes (1 to 5).",
             EncountersArgs, run_encounters, shape_encounters),
    ToolSpec("get_lab_history", "Laboratory results for one test over an optional date range (up to 50 rows).",
             LabHistoryArgs, run_lab_history, shape_lab_history),
    ToolSpec("get_lab_trend", "The computed trend statistics and data points for one test.",
             LabTrendArgs, run_lab_trend, shape_lab_trend),
    ToolSpec("get_gap_report", "The rule-engine findings for missing or inconsistent information.",
             NoArgs, run_gap_report, shape_gap_report),
)
