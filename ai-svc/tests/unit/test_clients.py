"""Upstream clients: retry policy, error mapping, header forwarding, tolerant parsing (LLD B14)."""
from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from app.clients.lab import LabClient
from app.clients.models import Latest, StatusPage
from app.clients.patient import PatientClient
from app.core.context import CallContext
from app.core.errors import PatientNotFound, UpstreamTimeout, UpstreamUnavailable
from tests.conftest import LAB_URL, PATIENT_URL, make_settings
from tests.fixtures import seed

CTX = CallContext("Bearer tok", "req-1")
PID = uuid.uuid4()
BASIC = {"id": str(PID), "sex": "F", "date_of_birth": "1980-01-02"}


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as r:
        yield r


@pytest.fixture
async def patients():
    c = PatientClient(make_settings(upstream_retries=2))
    c._http._backoff_s = 0.0
    yield c
    await c.aclose()


@pytest.fixture
async def labs():
    c = LabClient(make_settings(upstream_retries=2))
    c._http._backoff_s = 0.0
    yield c
    await c.aclose()


async def test_success_forwards_token_and_request_id(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(return_value=httpx.Response(200, json=BASIC))
    out = await patients.basic(PID, CTX)
    assert out.sex == "F"
    sent = route.calls.last.request.headers
    assert sent["authorization"] == "Bearer tok" and sent["x-request-id"] == "req-1"


async def test_503_is_retried_then_succeeds(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(side_effect=[
        httpx.Response(503), httpx.Response(502), httpx.Response(200, json=BASIC)])
    assert (await patients.basic(PID, CTX)).sex == "F"
    assert route.call_count == 3


async def test_retries_exhausted_is_upstream_unavailable_naming_the_service(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(return_value=httpx.Response(503))
    with pytest.raises(UpstreamUnavailable) as e:
        await patients.basic(PID, CTX)
    assert route.call_count == 3 and e.value.details == [{"upstream": "patient-svc"}]


async def test_connect_error_is_retried_and_maps_to_502(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(UpstreamUnavailable):
        await patients.basic(PID, CTX)
    assert route.call_count == 3


async def test_connect_timeout_maps_to_504(router, patients):
    router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(side_effect=httpx.ConnectTimeout("x"))
    with pytest.raises(UpstreamTimeout):
        await patients.basic(PID, CTX)


async def test_read_timeout_is_not_retried_and_maps_to_504(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(side_effect=httpx.ReadTimeout("x"))
    with pytest.raises(UpstreamTimeout) as e:
        await patients.basic(PID, CTX)
    assert route.call_count == 1 and e.value.details == [{"upstream": "patient-svc"}]


async def test_404_is_patient_not_found_without_retry(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(return_value=httpx.Response(404))
    with pytest.raises(PatientNotFound):
        await patients.basic(PID, CTX)
    assert route.call_count == 1


async def test_other_4xx_is_a_contract_bug_answered_as_upstream_failure(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(return_value=httpx.Response(422))
    with pytest.raises(UpstreamUnavailable):
        await patients.basic(PID, CTX)
    assert route.call_count == 1


async def test_a_response_missing_a_required_field_fails_loudly(router, patients):
    router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(
        return_value=httpx.Response(200, json={"id": str(PID), "sex": "F"}))
    with pytest.raises(UpstreamUnavailable):
        await patients.basic(PID, CTX)


async def test_additive_upstream_fields_are_ignored(router, patients):
    router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(
        return_value=httpx.Response(200, json=BASIC | {"new_field": [1, 2]}))
    assert (await patients.basic(PID, CTX)).sex == "F"


async def test_non_json_body_is_an_upstream_failure(router, patients):
    router.get(f"{PATIENT_URL}/internal/patients/{PID}/basic").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(UpstreamUnavailable):
        await patients.basic(PID, CTX)


async def test_bulk_paging_sends_cursor_and_limit(router, patients):
    route = router.get(f"{PATIENT_URL}/internal/patients/charts").mock(
        return_value=httpx.Response(200, json={"items": [], "next_cursor": None}))
    cursor = uuid.uuid4()
    await patients.charts_page(cursor, 200, CTX)
    assert dict(route.calls.last.request.url.params) == {"limit": "200", "cursor": str(cursor)}


async def test_lab_latest_accepts_object_categories_and_status_accepts_bare_codes(router, labs):
    p = seed.build(seed.SPECS[0])
    latest = Latest.model_validate(p["latest"])
    assert latest.egfr_category == "G3b"                             # {"code","label"} object -> "G3b"
    page = StatusPage.model_validate({"items": [p["status"]], "next_cursor": None})
    assert page.items[0].egfr_category == "G3b"                      # bare code
    assert latest.egfr_lt60_run is not None and latest.first_result_at is not None


async def test_lab_404_means_no_results(router, labs):
    router.get(f"{LAB_URL}/internal/labs/patients/{PID}/latest").mock(return_value=httpx.Response(404))
    router.get(f"{LAB_URL}/internal/labs/patients/{PID}/trends").mock(return_value=httpx.Response(404))
    assert (await labs.latest(PID, CTX)).latest == {}
    assert (await labs.trends(PID, CTX)).series == []


async def test_trends_requests_creatinine_and_egfr(router, labs):
    route = router.get(f"{LAB_URL}/internal/labs/patients/{PID}/trends").mock(
        return_value=httpx.Response(200, json={"patient_id": str(PID), "series": []}))
    await labs.trends(PID, CTX)
    assert route.calls.last.request.url.params["tests"] == "CREAT,EGFR"


async def test_lab_svc_failure_names_lab_svc(router, labs):
    router.get(f"{LAB_URL}/internal/labs/status").mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamUnavailable) as e:
        await labs.status_page(None, 200, CTX)
    assert e.value.details == [{"upstream": "lab-svc"}]
