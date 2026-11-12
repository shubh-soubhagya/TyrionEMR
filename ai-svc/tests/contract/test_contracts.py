"""Contract tests (LLD B17.7): the fixtures ai-svc is tested with must satisfy the JSON Schemas the providers publish.

The schemas are copies of patient-svc's ``contracts/patient`` and lab-svc's ``contracts/lab``. The providers validate
their real responses against the same files, so a drift on either side fails a build. One known, documented gap:

* B20.1: lab-svc has not yet added ``first_result_at`` and ``egfr_lt60_run`` to /latest and /internal/labs/status.

They are allowed as *extra* keys only; every required field and type is still checked.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.fixtures import seed

HERE = Path(__file__).parent
PENDING_EXTRAS = {"first_result_at", "egfr_lt60_run"}


def schema(rel: str) -> dict:
    return json.loads((HERE / rel).read_text(encoding="utf-8"))


def relaxed(node):
    """Drops ``additionalProperties: false`` from a copy so extras can be checked against an explicit allow-list."""
    node = copy.deepcopy(node)

    def walk(n):
        if isinstance(n, dict):
            if n.get("additionalProperties") is False:
                del n["additionalProperties"]
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return node


def validate(doc, rel: str, ref: str | None = None):
    s = schema(rel)
    if ref:
        s = {**s, "$ref": f"#/$defs/{ref}"}
        for key in ("type", "required", "properties", "additionalProperties"):
            s.pop(key, None)
    errors = sorted(Draft202012Validator(relaxed(s)).iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, [f"{'/'.join(map(str, e.path))}: {e.message[:120]}" for e in errors[:5]]


def keys_below(node, schema_node, path=""):
    """Every key the document has that the (strict) schema does not declare."""
    extras = set()
    if isinstance(node, dict) and isinstance(schema_node, dict) and "properties" in schema_node:
        for k, v in node.items():
            if k not in schema_node["properties"]:
                if schema_node.get("additionalProperties") is False:      # an open object may carry more (stats)
                    extras.add(k)
            else:
                extras |= keys_below(v, schema_node["properties"][k])
    elif isinstance(node, list) and isinstance(schema_node, dict) and "items" in schema_node:
        for v in node:
            extras |= keys_below(v, schema_node["items"])
    elif isinstance(node, dict) and isinstance(schema_node, dict) and "anyOf" in schema_node:
        for option in schema_node["anyOf"]:
            if option.get("type") == "object":
                extras |= keys_below(node, option)
    return extras


PATIENTS = seed.all_patients()
IDS = [p["mrn"] for p in PATIENTS]


@pytest.mark.parametrize("p", PATIENTS, ids=IDS)
def test_patient_svc_shapes(p):
    c = p["chart"]["patient"]
    validate({"id": str(p["id"]), "sex": c["sex"], "date_of_birth": c["date_of_birth"]}, "patient/basic.schema.json")
    validate(p["chart"], "patient/chart.schema.json")
    validate({"items": [p["bulk"]], "next_cursor": None}, "patient/charts.schema.json")
    ch = p["chart"]
    validate({"items": ch["conditions"], "truncated": False}, "patient/tools.schema.json", "conditions")
    validate({"medications": ch["medications"], "allergies": ch["allergies"], "truncated": False},
             "patient/tools.schema.json", "medications_allergies")
    validate({"items": ch["recent_encounters"], "truncated": False}, "patient/tools.schema.json", "encounters")


@pytest.mark.parametrize("p", PATIENTS, ids=IDS)
def test_lab_svc_shapes_and_only_the_documented_extras(p):
    validate(p["latest"], "lab/latest.schema.json")
    validate(p["trends"], "lab/trends.schema.json")
    validate({"items": p["results"].get("EGFR", []), "page": 1, "size": 50, "total": len(p["results"].get("EGFR", []))},
             "lab/results.schema.json")
    extras = keys_below(p["latest"], schema("lab/latest.schema.json")) | keys_below(p["trends"], schema("lab/trends.schema.json"))
    if p["status"]:
        validate({"items": [p["status"]], "next_cursor": None}, "lab/status.schema.json")
        extras |= keys_below({"items": [p["status"]], "next_cursor": None}, schema("lab/status.schema.json"))
    assert extras <= PENDING_EXTRAS, extras - PENDING_EXTRAS


def test_the_bulk_charts_contract_forbids_extra_fields_so_identifiers_cannot_slip_in():
    s = schema("patient/chart.schema.json")
    assert s["additionalProperties"] is False and s["properties"]["patient"]["additionalProperties"] is False
    assert not {"name", "mrn", "first_name", "last_name", "phone", "email", "address"} & set(
        s["properties"]["patient"]["properties"])


def test_test_names_and_decimals_match_lab_svcs_catalog():
    """The reason text ('Critical serum creatinine 5.62 mg/dL') must not drift from the lab form (B4.5)."""
    path = HERE.parents[2] / "lab-svc" / "app" / "domain" / "catalog_data.py"
    if not path.is_file():
        pytest.skip("lab-svc source tree not present")
    src = path.read_text(encoding="utf-8")
    from app.insights.rules.constants import TEST_DECIMALS, TEST_NAMES
    found = re.findall(r'"code": "([A-Z]+)", "name": "([^"]+)".*?"decimals": (\d)', src, flags=re.S)
    catalog = {code: (name, int(dec)) for code, name, dec in found}
    assert set(TEST_NAMES) <= set(catalog)
    for code in TEST_NAMES:
        assert (TEST_NAMES[code], TEST_DECIMALS[code]) == catalog[code], code
