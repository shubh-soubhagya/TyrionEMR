"""Contract and insights tests against fixtures CAPTURED from the running stack (``make capture-fixtures``, B17.5).

The hand-built fixtures prove the rules; these prove the clients and the rules against what patient-svc and lab-svc
really send. The tests are skipped, with a message, only while ``tests/fixtures/captured/manifest.json`` does not
exist (before the first capture); once it is committed they always run.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.cli.capture_fixtures import ALL_MRNS
from app.clients.models import Chart, ChartItem, ChartsPage, Latest, StatusItem, StatusPage, Trends
from app.insights.rules.adapters import from_bulk, from_chart
from app.insights.rules.attention import attention
from app.insights.rules.gaps import evaluate
from tests.contract.test_contracts import validate
from tests.fixtures import seed

CAPTURED = Path(__file__).resolve().parents[1] / "fixtures" / "captured"
pytestmark = pytest.mark.skipif(not (CAPTURED / "manifest.json").is_file(),
                                reason="no captured fixtures yet: run `make capture-fixtures` against a running stack")

TZ = ZoneInfo("Asia/Kolkata")


def load(rel: str):
    return json.loads((CAPTURED / rel).read_text(encoding="utf-8"))


def manifest() -> dict:
    return load("manifest.json")


def asof() -> tuple[datetime, date]:
    now = datetime.fromisoformat(manifest()["captured_at"])
    return now, now.astimezone(TZ).date()


def pages(rel: str) -> list[dict]:
    return load(rel)


def captured_mrns() -> list[str]:
    return list(manifest()["patients"])


# ---- contracts -----------------------------------------------------------------------------------------
def test_bulk_pages_satisfy_the_provider_schemas_and_the_client_models():
    for page in pages("patients/charts.json"):
        validate(page, "patient/charts.schema.json")
        ChartsPage.model_validate(page)
    for page in pages("labs/status.json"):
        validate(page, "lab/status.schema.json")
        StatusPage.model_validate(page)


@pytest.mark.parametrize("mrn", ["PT-000101", "PT-000110"])
def test_single_patient_responses_satisfy_the_schemas_and_models(mrn):
    assert mrn in captured_mrns()
    chart, latest, trends = load(f"{mrn}/chart.json"), load(f"{mrn}/latest.json"), load(f"{mrn}/trends.json")
    validate(chart, "patient/chart.schema.json")
    validate(load(f"{mrn}/conditions.json"), "patient/tools.schema.json", "conditions")
    validate(load(f"{mrn}/medications-allergies.json"), "patient/tools.schema.json", "medications_allergies")
    validate(load(f"{mrn}/encounters.json"), "patient/tools.schema.json", "encounters")
    validate(latest, "lab/latest.schema.json")
    validate(trends, "lab/trends.schema.json")
    validate(load(f"{mrn}/results-EGFR.json"), "lab/results.schema.json")
    Chart.model_validate(chart), Latest.model_validate(latest), Trends.model_validate(trends)
    assert "first_result_at" in latest and "egfr_lt60_run" in latest          # B20.1: the keys exist on the real response


def codes(facts, now: datetime, today: date) -> list[tuple[str, str, str]]:
    return [(x.code, x.severity, x.message) for x in evaluate(facts, today=today, now=now, tz=TZ)
            if x.code != "IMPLAUSIBLE_VITALS"]          # chart-only rule, excluded by design (B4.3)


def test_chart_path_and_bulk_path_agree_on_the_captured_data():
    now, today = asof()
    items = {i["mrn"]: i for page in pages("patients/charts.json") for i in page["items"]}
    status = {i["patient_id"]: i for page in pages("labs/status.json") for i in page["items"]}
    for mrn in captured_mrns():
        pid = str(items[mrn]["id"])
        single = from_chart(Chart.model_validate(load(f"{mrn}/chart.json")), Latest.model_validate(load(f"{mrn}/latest.json")),
                            Trends.model_validate(load(f"{mrn}/trends.json")), today=today)
        bulk = from_bulk(ChartItem.model_validate(items[mrn]),
                         StatusItem.model_validate(status[pid]) if pid in status else None)
        assert codes(single, now, today) == codes(bulk, now, today), mrn


# ---- HLD section 18: six need attention, four are rapid declines ---------------------------------------------
NAMES = {s.mrn: f"{s.first} {s.last}" for s in seed.SPECS}      # names of the HLD, checked against the capture below
EXPECTED_ATTENTION = {"Aditya Singh", "Ramesh Kulkarni", "Fatima Sheikh", "Kavita Joshi", "Lakshmi Iyer", "Priya Nair"}


def test_the_ten_seeded_patients_give_the_worklist_of_hld_18():
    now, today = asof()
    items = {i["mrn"]: i for page in pages("patients/charts.json") for i in page["items"]}
    status = {i["patient_id"]: i for page in pages("labs/status.json") for i in page["items"]}
    assert set(ALL_MRNS) <= set(items), "the ten seeded patients must all be present"
    assert {m: f'{items[m]["first_name"]} {items[m]["last_name"]}' for m in ALL_MRNS} == NAMES
    need, per_patient, rapid = set(), {}, 0
    for mrn in ALL_MRNS:
        pid = str(items[mrn]["id"])
        facts = from_bulk(ChartItem.model_validate(items[mrn]),
                          StatusItem.model_validate(status[pid]) if pid in status else None)
        findings = evaluate(facts, today=today, now=now, tz=TZ)
        att = attention(facts, findings)
        per_patient[NAMES[mrn]] = ([f.code for f in findings], att is not None)
        if att is not None:
            need.add(NAMES[mrn])
        rapid += int(bool(facts.labs and facts.labs.rapid_decline))
    assert need == EXPECTED_ATTENTION and rapid == 4, per_patient
