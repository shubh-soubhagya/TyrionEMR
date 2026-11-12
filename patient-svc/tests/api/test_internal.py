"""Internal endpoints + JSON Schema contracts (LLD §25.2 Internal, §25.5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import text

pytestmark = pytest.mark.api
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "patient"


def validate(instance, schema_file: str, ref: str | None = None) -> None:
    schema = json.loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    if ref:
        schema = {"$ref": f"#/$defs/{ref}", "$defs": schema["$defs"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


NAME, PHONE, EMAIL, ADDRESS = "Zeta", "+91 9123456780", "zeta@example.test", "12 Secret Street"


@pytest.fixture
async def chart_patient(api, make_patient) -> str:
    p = await make_patient(first_name="Zeta", last_name="Quinn", phone=PHONE, email=EMAIL, address=ADDRESS,
                           past_medical_history="T2DM")
    pid = p["id"]
    await api.post(f"/patients/{pid}/conditions", json={"description": "Diabetic nephropathy", "icd10_code": "E11.21",
                                                        "category": "nephrology", "is_primary": True})
    await api.post(f"/patients/{pid}/medications", json={"name": "Losartan", "dose": "50 mg", "frequency": "daily"})
    gone = (await api.post(f"/patients/{pid}/medications", json={
        "name": "Old", "dose": "1 mg", "frequency": "daily"})).json()
    await api.patch(f"/patients/{pid}/medications/{gone['id']}", json={"action": "discontinue"})
    await api.post(f"/patients/{pid}/allergies", json={"allergen": "Penicillin", "reaction": "Rash"})
    for day in (1, 10, 20):
        body = {"encounter_date": f"2026-10-{day:02d}T10:00:00+05:30", "chief_complaint": "cc",
                "assessment": "a" * 2000, "plan": "p", "status": "final",
                "vitals": {"systolic_bp": 130, "diastolic_bp": 80} if day != 10 else None,
                "diagnoses": [{"icd10_code": "N18.32", "description": "CKD 3b"}]}
        assert (await api.post(f"/patients/{pid}/encounters", json=body)).status_code == 201
    await api.post(f"/patients/{pid}/encounters", json={"encounter_date": "2026-11-05T10:00:00+05:30"})   # a draft
    return pid


async def test_basic_contract_and_404(api, make_patient):
    p = await make_patient()
    r = await api.get(f"/internal/patients/{p['id']}/basic")
    assert r.status_code == 200 and r.json() == {"id": p["id"], "sex": "M", "date_of_birth": "1959-04-17"}
    validate(r.json(), "basic.schema.json")
    await api.delete(f"/patients/{p['id']}")
    gone = await api.get(f"/internal/patients/{p['id']}/basic")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "NOT_FOUND"
    assert (await api.get("/internal/patients/00000000-0000-0000-0000-000000000000/basic")).status_code == 404


async def test_internal_routes_require_a_clinician_token(client, sign, make_patient=None):
    pid = "00000000-0000-0000-0000-000000000000"
    for path in (f"/internal/patients/{pid}/basic", f"/internal/patients/{pid}/chart", "/internal/patients/charts"):
        assert (await client.get(path)).status_code == 401
        r = await client.get(path, headers={"Authorization": f"Bearer {sign(role='nurse')}"})
        assert r.status_code == 403


async def test_chart_contract_and_data_minimisation(api, chart_patient):
    r = await api.get(f"/internal/patients/{chart_patient}/chart")
    assert r.status_code == 200, r.text
    body = r.json()
    validate(body, "chart.schema.json")
    blob = json.dumps(body)
    for secret in (NAME, "Quinn", PHONE, EMAIL, ADDRESS, "PT-0001"):
        assert secret not in blob, f"{secret} leaked into the internal chart (P-12)"
    assert body["patient"]["age"] == 67 and "mrn" not in body["patient"]
    assert body["counts"] == {"encounters": 4, "final_encounters": 3, "drafts": 1}
    assert len(body["recent_encounters"]) == 2                      # default encounters=2
    assert body["recent_encounters"][0]["status"] == "draft"        # newest first
    assert {m["status"] for m in body["medications"]} == {"active", "discontinued"}
    assert body["allergies"][0]["reaction"] == "Rash"


async def test_encounter_index_lists_every_encounter_with_flags(api, chart_patient):
    body = (await api.get(f"/internal/patients/{chart_patient}/chart", params={"encounters": 1})).json()
    assert len(body["recent_encounters"]) == 1 and len(body["encounter_index"]) == 4
    finals = [e for e in body["encounter_index"] if e["status"] == "final"]
    assert sorted(e["has_vitals"] for e in finals) == [False, True, True]
    assert all(e["has_assessment_and_plan"] for e in finals)
    assert (await api.get(f"/internal/patients/{chart_patient}/chart", params={"encounters": 6})).status_code == 422
    assert (await api.get(f"/internal/patients/{chart_patient}/chart", params={"encounters": 0})).status_code == 422


async def test_tool_endpoints_contract_and_truncation(api, chart_patient):
    base = f"/internal/patients/{chart_patient}"
    conds = (await api.get(f"{base}/conditions")).json()
    validate(conds, "tools.schema.json", "conditions")
    assert conds["truncated"] is False and conds["items"][0]["is_primary"] is True
    assert (await api.get(f"{base}/conditions", params={"status": "resolved"})).json()["items"] == []
    ma = (await api.get(f"{base}/medications-allergies")).json()
    validate(ma, "tools.schema.json", "medications_allergies")
    assert len(ma["medications"]) == 2 and ma["truncated"] is False
    enc = (await api.get(f"{base}/encounters", params={"limit": 3, "include_notes": "true"})).json()
    validate(enc, "tools.schema.json", "encounters")
    assert enc["truncated"] is True                                   # 2000-char assessments cut to 1500
    assert all(len(e["assessment"] or "") <= 1500 for e in enc["items"])
    no_notes = (await api.get(f"{base}/encounters", params={"limit": 3})).json()
    assert no_notes["truncated"] is False
    assert all("assessment" not in e and "plan" not in e and "examination_notes" not in e for e in no_notes["items"])
    assert (await api.get(f"{base}/encounters", params={"limit": 6})).status_code == 422


async def test_tool_endpoints_cap_rows_at_50(api, make_patient, db_engine):
    pid = (await make_patient())["id"]
    async with db_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO patient_conditions (patient_id, description, category) "
            "SELECT :p, 'Condition ' || g, 'comorbidity' FROM generate_series(1, 55) g"), {"p": pid})
    r = (await api.get(f"/internal/patients/{pid}/conditions")).json()
    assert len(r["items"]) == 50 and r["truncated"] is True


async def test_bulk_paging_covers_every_patient_exactly_once(api, make_patient):
    created = [(await make_patient(first_name=f"P{i}"))["id"] for i in range(5)]
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await api.get("/internal/patients/charts", params=params)).json()
        validate(page, "charts.schema.json")
        seen += [i["id"] for i in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and sorted(seen) == sorted(created) and len(set(seen)) == 5
    assert seen == sorted(seen)                                     # keyset order by id
    exact = (await api.get("/internal/patients/charts", params={"limit": 5})).json()
    assert len(exact["items"]) == 5 and exact["next_cursor"] is None   # the extra row decides, not the page size
    assert (await api.get("/internal/patients/charts", params={"limit": 201})).status_code == 422


async def test_bulk_rule_fields_and_deleted_patients_excluded(api, make_patient):
    a = (await make_patient(first_name="Kavita", last_name="Joshi"))["id"]
    b = (await make_patient(first_name="Gone"))["id"]
    await api.post(f"/patients/{a}/conditions", json={"description": "SLE nephritis", "category": "nephrology",
                                                      "is_primary": True})
    await api.post(f"/patients/{a}/medications", json={"name": "Hydroxychloroquine", "dose": "200 mg",
                                                       "frequency": "daily", "start_date": "2026-01-01",
                                                       "end_date": "2026-10-02"})
    await api.post(f"/patients/{a}/encounters", json={
        "encounter_date": "2026-10-05T10:00:00+05:30", "chief_complaint": "c", "assessment": "a", "plan": "  ",
        "status": "draft"})
    await api.post(f"/patients/{a}/encounters", json={
        "encounter_date": "2026-10-06T10:00:00+05:30", "chief_complaint": "c", "assessment": "a", "plan": "p",
        "status": "final", "vitals": {"heart_rate": 70}})
    await api.delete(f"/patients/{b}")
    items = (await api.get("/internal/patients/charts")).json()["items"]
    assert [i["id"] for i in items] == [a]
    row = items[0]
    assert row["has_active_primary"] is True and row["medication_count"] == 1 and row["mrn"] == "PT-000101"
    assert row["active_meds_past_end"][0]["name"] == "Hydroxychloroquine"
    assert row["final_encounters"][0]["has_vitals"] is True and len(row["final_encounters"]) == 1


async def test_internal_audit_rows(api, db_engine, chart_patient):
    base = f"/internal/patients/{chart_patient}"
    await api.get(f"{base}/basic")                                   # not audited
    await api.get(f"{base}/chart")
    await api.get(f"{base}/conditions")
    await api.get("/internal/patients/charts")
    async with db_engine.connect() as conn:
        res = await conn.execute(text("SELECT action, details FROM audit_events "
                                      "WHERE action LIKE 'chart.%' ORDER BY id"))
        got = [(r.action, r.details) for r in res]
    assert [a for a, _ in got] == ["chart.read_internal", "chart.read_internal", "chart.bulk_export"]
    assert got[0][1] == {"read": "chart"} and got[2][1] == {"count": 1}
