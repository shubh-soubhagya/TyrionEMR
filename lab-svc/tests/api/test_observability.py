"""Phase 10: metrics, domain events and log hygiene (LLD B12)."""
from __future__ import annotations

import logging
import re

import httpx
import pytest
from prometheus_client import REGISTRY

from app.core.logging import JsonFormatter

pytestmark = pytest.mark.api
WHEN = "2026-10-01T09:00:00Z"


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def report(api: httpx.AsyncClient, pid, results: list[dict], when: str = WHEN) -> httpx.Response:
    return await api.post(f"/labs/patients/{pid}/reports", json={"collected_at": when, "results": results})


def k(value: float, unit: str = "mmol/L") -> dict:
    return {"test_code": "K", "value": value, "unit": unit}


async def test_results_counter_is_labelled_by_test_and_flag(api, patients) -> None:
    before = sample("lab_results_created_total", test_code="K", flag="critical_high")
    await report(api, patients.add(), [k(7.77), {"test_code": "CREAT", "value": 1.0, "unit": "mg/dL"}])
    assert sample("lab_results_created_total", test_code="K", flag="critical_high") == before + 1


async def test_corrections_are_counted_per_test_and_also_as_results(api, patients) -> None:
    res = (await report(api, patients.add(), [k(6.5)])).json()["results"][0]
    before = sample("lab_corrections_total", test_code="K")
    created = sample("lab_results_created_total", test_code="K", flag="normal")
    await api.post(f"/labs/results/{res['id']}/correct", json={"value": 4.0, "unit": "mmol/L", "reason": "re-keyed"})
    assert sample("lab_corrections_total", test_code="K") == before + 1
    assert sample("lab_results_created_total", test_code="K", flag="normal") == created + 1


async def test_recompute_and_lock_wait_histograms_move_on_every_write(api, patients) -> None:
    recompute = sample("lab_status_recompute_seconds_count")
    lock = sample("lab_advisory_lock_wait_seconds_count")
    await report(api, patients.add(), [k(4.0)])
    assert sample("lab_status_recompute_seconds_count") == recompute + 1
    assert sample("lab_advisory_lock_wait_seconds_count") == lock + 1


async def test_patient_client_outcomes(api, patients) -> None:
    from app.core.errors import UpstreamTimeout, UpstreamUnavailable
    assert patients.people == {}                                    # the fake does not count; use the real client below
    import uuid

    from app.services.patient_client import PatientClient
    from tests.conftest import make_settings

    ok = sample("lab_patient_client_requests_total", outcome="ok")
    nf = sample("lab_patient_client_requests_total", outcome="not_found")
    retry = sample("lab_patient_client_requests_total", outcome="retry")
    to = sample("lab_patient_client_requests_total", outcome="timeout")
    err = sample("lab_patient_client_requests_total", outcome="error")
    pid = uuid.uuid4()
    body = {"id": str(pid), "sex": "M", "date_of_birth": "1970-01-01"}
    seq = iter([503, 200])
    c = PatientClient(make_settings(), httpx.MockTransport(
        lambda _: httpx.Response(next(seq), json=body)))
    await c.basic(pid, "Bearer x", None)
    assert sample("lab_patient_client_requests_total", outcome="retry") == retry + 1
    assert sample("lab_patient_client_requests_total", outcome="ok") == ok + 1

    def read_timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UpstreamTimeout):
        await PatientClient(make_settings(), httpx.MockTransport(read_timeout)).basic(pid, "Bearer x", None)
    assert sample("lab_patient_client_requests_total", outcome="timeout") == to + 1
    with pytest.raises(UpstreamUnavailable):
        await PatientClient(make_settings(), httpx.MockTransport(lambda _: httpx.Response(500))).basic(pid, "B", None)
    assert sample("lab_patient_client_requests_total", outcome="error") == err + 1
    from app.core.errors import PatientNotFound
    with pytest.raises(PatientNotFound):
        await PatientClient(make_settings(), httpx.MockTransport(lambda _: httpx.Response(404))).basic(pid, "B", None)
    assert sample("lab_patient_client_requests_total", outcome="not_found") == nf + 1


async def test_http_metrics_use_route_templates_not_raw_paths(api, patients) -> None:
    pid = patients.add()
    await api.get(f"/labs/patients/{pid}/latest")
    text = (await api.get("/metrics")).text
    assert 'route="/labs/patients/{patient_id}/latest"' in text and str(pid) not in text
    assert sample("http_requests_total", route="/labs/patients/{patient_id}/latest", method="GET", status="200") >= 1


async def test_catalog_reload_counter_exists(api) -> None:
    assert "lab_catalog_reload_total" in (await api.get("/metrics")).text
    assert sample("lab_catalog_reload_total", result="ok") >= 1


async def test_scrape_has_every_b12_metric_name_and_no_values(api, patients) -> None:
    await report(api, patients.add(), [k(7.77)])
    text = (await api.get("/metrics")).text
    for name in ("http_requests_total", "http_request_duration_seconds", "lab_results_created_total",
                 "lab_corrections_total", "lab_status_recompute_seconds", "lab_patient_client_requests_total",
                 "lab_advisory_lock_wait_seconds", "lab_catalog_reload_total"):
        assert name in text, name
    assert "7.77" not in text
    assert not re.search(r"lab_(reports|results)_(stored|created)_total\{[^}]*patient", text)


async def test_report_created_event_carries_ids_counts_and_flags_only(api, patients, caplog) -> None:
    pid = patients.add("M")
    with caplog.at_level(logging.INFO, logger="lab.reports"):
        resp = await report(api, pid, [
            {"test_code": "CREAT", "value": 168, "unit": "µmol/L"}, k(7.77), k(4.0) | {"test_code": "HB", "unit": "g/dL"}])
    rec = next(r for r in caplog.records if r.getMessage() == "lab_report_created")
    assert rec.report_id == resp.json()["report"]["id"] and rec.patient_id == str(pid)
    assert (rec.n, rec.abnormal, rec.critical, rec.units_converted) == (3, 3, 2, 1)   # K 7.77 and HB 4.0 are critical
    line = JsonFormatter("lab-svc").format(rec)
    for secret in ("7.77", "168", "1.898"):
        assert secret not in line
    assert '"event":"lab_report_created"' in line


async def test_correction_event_has_no_values_or_reason(api, patients, caplog) -> None:
    res = (await report(api, patients.add(), [k(6.5)])).json()["results"][0]
    with caplog.at_level(logging.INFO, logger="lab.reports"):
        await api.post(f"/labs/results/{res['id']}/correct",
                       json={"value": 4.4, "unit": "mmol/L", "reason": "confidential reason text"})
    rec = next(r for r in caplog.records if r.getMessage() == "lab_result_corrected")
    line = JsonFormatter("lab-svc").format(rec)
    assert "4.4" not in line and "confidential" not in line and rec.test_code == "K"


async def test_access_log_has_route_and_user_but_no_values(api, patients, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await report(api, patients.add(), [k(7.77)])
    rec = next(r for r in caplog.records if getattr(r, "route", "").endswith("/reports"))
    assert rec.route == "/labs/patients/{patient_id}/reports" and rec.status == 201 and rec.user_id
    assert "7.77" not in JsonFormatter("lab-svc").format(rec)
