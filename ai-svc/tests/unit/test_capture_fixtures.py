"""The capture script: logs in through the gateway, reads internal routes, writes raw bodies and leaks nothing."""
from __future__ import annotations

import json

import httpx
import respx

from app.cli import capture_fixtures as cap

GW, PAT, LAB = "http://gateway:8000", "http://patient-svc:8000", "http://lab-svc:8000"
TOKEN = "tok-secret-value"


def test_patient_ids_use_patient_svcs_seed_namespace():
    from app.cli.capture_fixtures import patient_id
    assert str(patient_id("PT-000101")) == "fc158cad-0a89-5611-9c8b-1a0b551453d0"


@respx.mock
def test_capture_writes_every_upstream_call_and_follows_cursors(tmp_path, capsys):
    login = respx.post(f"{GW}/api/auth/login").mock(return_value=httpx.Response(200, json={"access_token": TOKEN}))
    page2 = "00000000-0000-4000-8000-000000000002"
    respx.get(f"{PAT}/internal/patients/charts").mock(side_effect=[
        httpx.Response(200, json={"items": [{"n": 1}], "next_cursor": page2}),
        httpx.Response(200, json={"items": [{"n": 2}], "next_cursor": None})])
    respx.get(f"{LAB}/internal/labs/status").mock(return_value=httpx.Response(200, json={"items": [], "next_cursor": None}))
    for what in ("basic", "chart", "conditions", "medications-allergies", "encounters"):
        respx.get(url__regex=rf"{PAT}/internal/patients/[0-9a-f-]+/{what}(\?.*)?$").mock(
            return_value=httpx.Response(200, json={"what": what}))
    for what in ("latest", "trends", "results"):
        respx.get(url__regex=rf"{LAB}/internal/labs/patients/[0-9a-f-]+/{what}(\?.*)?$").mock(
            return_value=httpx.Response(200, json={"what": what}))

    cap.capture(tmp_path, ("PT-000101",), gateway=GW, patient_url=PAT, lab_url=LAB, email="dr@x", password="pw")

    assert login.called
    assert json.loads((tmp_path / "patients/charts.json").read_text(encoding="utf-8")) == [
        {"items": [{"n": 1}], "next_cursor": page2}, {"items": [{"n": 2}], "next_cursor": None}]
    for rel in ("labs/status", "PT-000101/basic", "PT-000101/chart", "PT-000101/conditions",
                "PT-000101/medications-allergies", "PT-000101/encounters", "PT-000101/latest", "PT-000101/trends",
                "PT-000101/results-EGFR", "manifest"):
        assert (tmp_path / f"{rel}.json").is_file(), rel
    for call in respx.calls:
        if "/internal/" in str(call.request.url):
            assert call.request.headers["authorization"] == f"Bearer {TOKEN}"
    printed = capsys.readouterr().out
    assert TOKEN not in printed and "pw" not in printed.split()          # nothing sensitive reaches stdout
