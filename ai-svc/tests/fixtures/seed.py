"""Synthetic seed for the insights tests: the ten patients of HLD section 18 (LLD B17.6), expressed once and rendered
into BOTH upstream shapes (single-patient chart/latest/trends and the bulk charts/status pages).

These fixtures are hand-built from the upstream contracts, not captured from running services (B17.5 plans a capture
script for later). Names and MRNs are the synthetic ones of the design documents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid5

from app.insights.rules.ckd_epi import age_on, ckd_epi_2021

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
NS = UUID("6f0c2d3e-0000-4000-8000-00000000a1c0")
EGFR_LABELS = {"G1": "Normal or high", "G2": "Mildly decreased", "G3a": "Mild to moderately decreased",
               "G3b": "Moderately to severely decreased", "G4": "Severely decreased", "G5": "Kidney failure"}

# (low, high, critical_low, critical_high): approximate adult ranges, enough to flag the fixtures
RANGES = {"CREAT": (0.6, 1.3, None, 5.0), "EGFR": (60, None, None, None), "BUN": (7, 20, None, None),
          "K": (3.5, 5.1, 2.5, 6.0), "UACR": (None, 30, None, None)}
TILE_ORDER = ("CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR")
UNITS_PER_REPORT = ("CREAT", "EGFR", "UACR")
NAMES = {"CREAT": "Serum creatinine", "EGFR": "eGFR", "BUN": "Blood urea nitrogen", "K": "Potassium",
         "HB": "Hemoglobin", "CA": "Calcium", "PHOS": "Phosphorus", "UACR": "Urine albumin-creatinine ratio"}
UNITS = {"CREAT": "mg/dL", "EGFR": "mL/min/1.73 m²", "BUN": "mg/dL", "K": "mmol/L", "UACR": "mg/g", "HB": "g/dL",
         "CA": "mg/dL", "PHOS": "mg/dL"}


def uid(*parts: str) -> UUID:
    return uuid5(NS, "/".join(parts))


def flag_for(code: str, v: float) -> str:
    lo, hi, clo, chi = RANGES.get(code, (None, None, None, None))
    if clo is not None and v < clo:
        return "critical_low"
    if chi is not None and v > chi:
        return "critical_high"
    if lo is not None and v < lo:
        return "low"
    if hi is not None and v > hi:
        return "high"
    return "normal"


def category(egfr: float) -> str:
    for code, lower in (("G1", 90), ("G2", 60), ("G3a", 45), ("G3b", 30), ("G4", 15)):
        if egfr >= lower:
            return code
    return "G5"


def creat_for_egfr(target: float, age: int, sex: str) -> float:
    """Creatinine that makes CKD-EPI 2021 produce ``target`` (bisection), so derived eGFR and creatinine agree."""
    lo, hi = 0.2, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ckd_epi_2021(mid, age, sex) > target:  # type: ignore[arg-type]
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def stats(code: str, pts: list[tuple[datetime, float]]) -> dict | None:
    if not pts:
        return None
    n = len(pts)
    first, last = pts[0], pts[-1]
    out = {"n": n, "first": first[1], "last": last[1], "abs_change": round(last[1] - first[1], 4),
           "first_at": first[0].isoformat(), "last_at": last[0].isoformat(),
           "span_days": (last[0] - first[0]).days}
    if n < 3:
        return out | {"direction": "insufficient_data", "slope_per_year": None, "rapid_decline": False,
                      "pct_change": None}
    xs = [(t - first[0]).total_seconds() / 86400 / 365.25 for t, _ in pts]
    ys = [v for _, v in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
    if code == "EGFR":
        direction = "worsening" if slope <= -2 else "improving" if slope >= 2 else "stable"
    else:
        direction = "worsening" if slope > 0.1 else "improving" if slope < -0.1 else "stable"
    return out | {"direction": direction, "slope_per_year": round(slope, 2),
                  "rapid_decline": code == "EGFR" and slope <= -5,
                  "pct_change": round((last[1] - first[1]) / first[1] * 100, 1)}


@dataclass
class Spec:
    mrn: str
    first: str
    last: str
    sex: str
    dob: date
    allergy: str = "nka"
    stage: str | None = None
    primary: bool = True
    meds: int = 2
    past_end_med: str | None = None
    egfr: list[tuple[int, float]] = field(default_factory=list)        # (days ago, eGFR) one report each
    egfr_override: dict[int, float] = field(default_factory=dict)      # days ago -> stored eGFR (breaks agreement)
    extra_latest: dict[str, float] = field(default_factory=dict)       # latest-report overrides, e.g. K, CREAT
    final_without_vitals: bool = False
    with_encounter: bool = True


SPECS = [
    Spec("PT-000101", "Ramesh", "Kulkarni", "M", date(1965, 5, 2), stage="G3b",
         egfr=[(700, 54), (600, 52), (500, 49), (400, 46), (300, 44), (200, 42), (100, 40), (10, 38)]),
    Spec("PT-000102", "Sunita", "Verma", "F", date(1970, 8, 21), stage="G2",
         egfr=[(500, 72), (350, 71), (200, 72), (10, 72)]),
    Spec("PT-000103", "Arjun", "Mehta", "M", date(1975, 1, 9), allergy="unknown", stage="G2",
         egfr=[(400, 68), (200, 68), (10, 68)], final_without_vitals=True),
    Spec("PT-000104", "Fatima", "Sheikh", "F", date(1962, 3, 30), stage="G4",
         egfr=[(700, 36), (550, 33), (400, 30), (250, 27), (120, 24), (10, 22)]),
    Spec("PT-000105", "Vikram", "Rao", "M", date(1980, 11, 5), meds=0,
         egfr=[(500, 50), (350, 56), (200, 60), (10, 64)]),
    Spec("PT-000106", "Lakshmi", "Iyer", "F", date(1958, 7, 14), stage="G3a",
         egfr=[(400, 36), (200, 36), (10, 35)]),
    Spec("PT-000107", "Mohan", "Das", "M", date(1967, 2, 18), stage="G3a",
         egfr=[(260, 45), (230, 45), (200, 45)],
         extra_latest={"CREAT": 1.0}),
    Spec("PT-000108", "Priya", "Nair", "F", date(1990, 9, 3), allergy="unknown", primary=False, meds=0,
         with_encounter=False),
    Spec("PT-000109", "Aditya", "Singh", "M", date(1965, 6, 25), stage="G5",
         egfr=[(600, 24), (480, 20), (360, 17), (240, 14), (120, 12), (10, 9)],
         extra_latest={"CREAT": 5.62, "K": 6.2}),
    Spec("PT-000110", "Kavita", "Joshi", "F", date(1963, 12, 1), past_end_med="Pantoprazole",
         egfr=[(500, 59), (400, 57), (300, 55), (200, 53), (100, 51), (10, 49)]),
]


def build(spec: Spec, *, b20_fields: bool = True) -> dict:
    """One patient rendered into every upstream shape: chart, bulk item, latest, trends, status."""
    pid = uid(spec.mrn)
    today = NOW.date()
    age_now = age_on(spec.dob, today)
    reports: list[tuple[datetime, dict[str, float]]] = []
    for days, egfr in sorted(spec.egfr, reverse=True):
        at = NOW - timedelta(days=days)
        age = age_on(spec.dob, at.date())
        values = {"CREAT": creat_for_egfr(egfr, age, spec.sex), "EGFR": spec.egfr_override.get(days, egfr),
                  "UACR": 40.0}
        reports.append((at, values))
    if reports and spec.extra_latest:
        reports[-1][1].update(spec.extra_latest)
    series: dict[str, list[tuple[datetime, float]]] = {}
    latest: dict[str, dict] = {}
    for at, values in reports:
        report_id = uid(spec.mrn, "report", at.isoformat())
        for code, v in values.items():
            series.setdefault(code, []).append((at, v))
            latest[code] = {"result_id": str(uid(spec.mrn, code, at.isoformat())), "report_id": str(report_id),
                            "value": v, "unit": UNITS[code], "flag": flag_for(code, v),
                            "collected_at": at.isoformat(), "ref_low": None, "ref_high": None}
    egfr_pts = series.get("EGFR", [])
    egfr_stats, creat_stats = stats("EGFR", egfr_pts), stats("CREAT", series.get("CREAT", []))
    cat = category(egfr_pts[-1][1]) if egfr_pts else None
    run = None
    if egfr_pts and egfr_pts[-1][1] < 60:
        i = len(egfr_pts)
        while i > 0 and egfr_pts[i - 1][1] < 60:
            i -= 1
        run = {"since": egfr_pts[i][0].isoformat(), "n": len(egfr_pts) - i}
    has_labs = bool(reports)
    lab = {
        "latest": latest, "has_critical": any(e["flag"].startswith("critical") for e in latest.values()),
        "rapid_decline": bool(egfr_stats and egfr_stats["rapid_decline"]),
        "last_result_at": reports[-1][0].isoformat() if has_labs else None,
    }
    if b20_fields and has_labs:
        lab |= {"first_result_at": reports[0][0].isoformat(), "egfr_lt60_run": run}

    enc_id = uid(spec.mrn, "enc")
    enc_at = NOW - timedelta(days=20)
    encounters = []
    if spec.with_encounter:
        encounters = [{"id": str(enc_id), "encounter_date": enc_at.isoformat(), "status": "final",
                       "has_vitals": not spec.final_without_vitals, "has_assessment_and_plan": True}]
    meds = [{"id": str(uid(spec.mrn, "med", str(i))), "name": f"Medication {i}", "dose": "10 mg", "route": "oral",
             "frequency": "daily", "start_date": "2025-01-01", "end_date": None, "status": "active"}
            for i in range(spec.meds)]
    past_end = []
    if spec.past_end_med:
        mid = str(uid(spec.mrn, "med", "past"))
        meds.append({"id": mid, "name": spec.past_end_med, "dose": "40 mg", "route": "oral", "frequency": "daily",
                     "start_date": "2025-01-01", "end_date": "2026-06-30", "status": "active"})
        past_end = [{"id": mid, "name": spec.past_end_med, "end_date": "2026-06-30"}]
    conditions = [{"id": str(uid(spec.mrn, "cond")), "icd10_code": "N18.3", "description": "Chronic kidney disease",
                   "category": "nephrology", "is_primary": spec.primary, "status": "active", "onset_date": None,
                   "resolved_date": None}]
    vitals = None if spec.final_without_vitals else {"systolic_bp": 128, "diastolic_bp": 82, "heart_rate": 74,
                                                      "temperature_c": 36.8, "weight_kg": 70.0}
    chart = {
        "patient": {"id": str(pid), "age": age_now, "sex": spec.sex, "date_of_birth": spec.dob.isoformat(),
                    "allergy_status": spec.allergy, "established_ckd_stage": spec.stage,
                    "past_medical_history": None, "family_history": None, "social_history": None},
        "conditions": conditions, "medications": meds, "allergies": [],
        "recent_encounters": [dict(e, encounter_type="follow_up", chief_complaint=None, symptoms=[],
                                   examination_notes=None, assessment="x", plan="y", follow_up_date=None,
                                   vitals=vitals, diagnoses=[]) for e in encounters],
        "encounter_index": encounters,
        "counts": {"encounters": len(encounters), "final_encounters": len(encounters), "drafts": 0},
    }
    bulk = {
        "id": str(pid), "mrn": spec.mrn, "first_name": spec.first, "last_name": spec.last,
        "date_of_birth": spec.dob.isoformat(), "age": age_now, "sex": spec.sex, "allergy_status": spec.allergy,
        "established_ckd_stage": spec.stage, "has_active_primary": spec.primary, "medication_count": len(meds),
        "active_meds_past_end": past_end,
        "final_encounters": [{k: e[k] for k in ("id", "encounter_date", "has_vitals", "has_assessment_and_plan")}
                             for e in encounters],
    }
    categories = {"egfr_category": cat, "uacr_category": "A2" if has_labs else None}

    def point(code: str, at: datetime, v: float) -> dict:
        return {"result_id": str(uid(spec.mrn, code, at.isoformat())), "collected_at": at.isoformat(), "value": v,
                "flag": flag_for(code, v)}

    # lab-svc's current /latest contract: eight tiles in display order plus a ckd block (contracts/lab/latest)
    tiles = []
    for code in TILE_ORDER:
        entry = latest.get(code)
        result = None
        if entry:
            result = {k: entry[k] for k in ("result_id", "report_id", "value", "flag", "collected_at", "ref_low",
                                            "ref_high")}
        tiles.append({"test_code": code, "name": NAMES[code], "canonical_unit": UNITS.get(code, ""), "result": result})
    egfr_e, uacr_e = latest.get("EGFR"), latest.get("UACR")
    ckd = {"egfr_category": cat, "egfr_label": EGFR_LABELS.get(cat) if cat else None,
           "egfr_value": egfr_e["value"] if egfr_e else None, "egfr_collected_at": egfr_e["collected_at"] if egfr_e else None,
           "uacr_category": categories["uacr_category"], "uacr_label": "Moderately increased" if uacr_e else None,
           "uacr_value": uacr_e["value"] if uacr_e else None,
           "uacr_collected_at": uacr_e["collected_at"] if uacr_e else None}
    latest_doc = {"patient_id": str(pid), "tests": tiles, "ckd": ckd, "has_critical": lab["has_critical"],
                  "rapid_decline": lab["rapid_decline"], "last_result_at": lab["last_result_at"],
                  "status_version": len(reports)}
    latest_doc |= {k: lab[k] for k in ("first_result_at", "egfr_lt60_run") if k in lab}

    def empty(c: str) -> dict:
        return stats(c, series.get(c, [])) or {"n": 0, "direction": "no_data"}

    trends = {"patient_id": str(pid), "from": None, "to": None, "series": [
        {"test_code": c, "unit": UNITS[c], "points": [point(c, at, v) for at, v in series.get(c, [])],
         "stats": empty(c), "reference": None} for c in ("CREAT", "EGFR")]}
    results = {c: [{"id": point(c, at, v)["result_id"], "report_id": str(uid(spec.mrn, "report", at.isoformat())),
                    "test_code": c, "test_name": c, "collected_at": at.isoformat(), "value": v, "unit": UNITS[c],
                    "value_original": v, "unit_original": UNITS[c], "ref_low": None, "ref_high": None,
                    "flag": flag_for(c, v), "lab_name": "Synthetic Lab", "is_correction": False, "superseded": False}
                   for at, v in pts] for c, pts in series.items()}
    status = None
    if has_labs:
        status = {"patient_id": str(pid), **lab, **categories, "egfr_stats": egfr_stats, "creat_stats": creat_stats,
                  "result_count": len(reports) * len(UNITS_PER_REPORT)}
    return {"mrn": spec.mrn, "id": pid, "chart": chart, "bulk": bulk, "latest": latest_doc, "trends": trends,
            "status": status, "results": results}


def all_patients(*, b20_fields: bool = True) -> list[dict]:
    return sorted((build(s, b20_fields=b20_fields) for s in SPECS), key=lambda p: str(p["id"]))
