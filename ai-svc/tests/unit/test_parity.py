"""Parity test (LLD B17.5, AI-ADR-5): the single-patient path and the bulk path must yield identical findings."""
from __future__ import annotations

import pytest

from app.clients.models import Chart, ChartItem, Latest, StatusItem, Trends
from app.insights.rules.adapters import from_bulk, from_chart
from app.insights.rules.attention import attention
from app.insights.rules.gaps import evaluate
from tests.factories import TODAY, TZ
from tests.fixtures import seed

NOW = seed.NOW


def findings(facts):
    return [(f.code, f.severity, f.message) for f in evaluate(facts, today=TODAY, now=NOW, tz=TZ)
            if f.code != "IMPLAUSIBLE_VITALS"]           # chart-only rule, excluded by design (B4.3)


def both(p):
    chart = from_chart(Chart.model_validate(p["chart"]), Latest.model_validate(p["latest"]),
                       Trends.model_validate(p["trends"]), today=TODAY)
    status = StatusItem.model_validate(p["status"]) if p["status"] else None
    bulk = from_bulk(ChartItem.model_validate(p["bulk"]), status)
    return chart, bulk


@pytest.mark.parametrize("patient", seed.all_patients(), ids=lambda p: p["mrn"])
def test_chart_and_bulk_paths_agree(patient):
    chart, bulk = both(patient)
    assert findings(chart) == findings(bulk)
    a, b = attention(chart, evaluate(chart, today=TODAY, now=NOW, tz=TZ)), attention(bulk, evaluate(bulk, today=TODAY, now=NOW, tz=TZ))
    assert (a.rank, a.reasons) == (b.rank, b.reasons) if a and b else a is b


EXPECTED = {   # B17.6 (with the Kavita Joshi seed fix)
    "PT-000101": ([], True), "PT-000102": ([], False),
    "PT-000103": (["ALLERGY_STATUS_UNKNOWN", "ENCOUNTER_NO_VITALS"], False),
    "PT-000104": ([], True), "PT-000105": (["NO_MEDICATIONS_DOCUMENTED"], False),
    "PT-000106": (["CKD_STAGE_MISMATCH"], True),
    "PT-000107": (["NO_RECENT_LABS", "EGFR_CREATININE_DISCORDANT"], False),
    "PT-000108": (["ALLERGY_STATUS_UNKNOWN", "NO_PRIMARY_DIAGNOSIS", "NO_MEDICATIONS_DOCUMENTED", "NO_LABS_RECORDED"],
                  True),
    "PT-000109": ([], True),
    "PT-000110": (["NO_ESTABLISHED_CKD_STAGE", "ACTIVE_MED_PAST_END_DATE"], True),
}


@pytest.mark.parametrize("patient", seed.all_patients(), ids=lambda p: p["mrn"])
def test_seed_expectations(patient):
    chart, _ = both(patient)
    found = evaluate(chart, today=TODAY, now=NOW, tz=TZ)
    codes, needs = EXPECTED[patient["mrn"]]
    assert [f.code for f in found] == codes
    assert (attention(chart, found) is not None) is needs


def test_rules_degrade_gracefully_when_lab_svc_lacks_the_b20_fields():
    """Until lab-svc sends first_result_at and egfr_lt60_run, rules 10 and 12 stay quiet instead of failing."""
    p = next(x for x in seed.all_patients(b20_fields=False) if x["mrn"] == "PT-000110")
    chart, bulk = both(p)
    assert "NO_ESTABLISHED_CKD_STAGE" not in [f.code for f in evaluate(chart, today=TODAY, now=NOW, tz=TZ)]
    assert findings(chart) == findings(bulk)
