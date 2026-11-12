"""PHI must never reach the service's logs (LLD §17.3, §20.1), and the body-size limit (review fix, phase 4).

The log test captures the REAL JSON output of the configured handler, not just ``caplog``. The test client's own
``httpx`` logger prints request URLs (including ``q=``) into the same root handler, so only lines written by the
service's loggers are examined: those are the ones that would exist in production.
"""
from __future__ import annotations

import io
import json
import logging

import httpx
import pytest

from app.main import create_app
from tests.conftest import make_settings

pytestmark = pytest.mark.api

MARKERS = ["Zqxmarkerlast", "Zqxmarkerfirst", "+91 9000012345", "ZqxPMHmarker", "ZqxFHmarker", "ZqxSHmarker",
           "Zqxstreet", "ZqxCCmarker", "ZqxExamMarker", "ZqxAssessMarker", "ZqxPlanMarker", "ZqxDxMarker",
           "ZqxAllergenMarker", "ZqxReactionMarker", "ZqxSymptomMarker", "Zqxbadphone", "zqx.mail@example.test"]


@pytest.fixture
def log_buffer(api):
    """Redirects the root JSON handler (installed by configure_logging at app start) into a buffer."""
    buffer = io.StringIO()
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)]
    old = [(h, h.setStream(buffer)) for h in handlers]
    yield buffer
    for h, stream in old:
        h.setStream(stream)


def service_lines(buffer: io.StringIO) -> list[dict]:
    lines = []
    for raw in buffer.getvalue().splitlines():
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if not str(doc.get("logger", "")).startswith(("httpx", "httpcore", "asyncio")):
            lines.append(doc)
    return lines


async def test_no_marker_appears_anywhere_in_the_service_logs(api, log_buffer):
    created = await api.post("/patients", json={
        "first_name": "Zqxmarkerfirst", "last_name": "Zqxmarkerlast", "date_of_birth": "1970-01-01", "sex": "M",
        "phone": "+91 9000012345", "email": "zqx.mail@example.test", "address": "1 Zqxstreet",
        "past_medical_history": "ZqxPMHmarker", "family_history": "ZqxFHmarker", "social_history": "ZqxSHmarker"})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert (await api.patch(f"/patients/{pid}", json={"version": 1, "address": "2 Zqxstreet"})).status_code == 200
    assert (await api.post(f"/patients/{pid}/allergies", json={
        "allergen": "ZqxAllergenMarker", "reaction": "ZqxReactionMarker"})).status_code == 201
    enc = await api.post(f"/patients/{pid}/encounters", json={
        "encounter_date": "2026-11-11T10:00:00+05:30", "chief_complaint": "ZqxCCmarker",
        "examination_notes": "ZqxExamMarker", "assessment": "ZqxAssessMarker", "plan": "ZqxPlanMarker",
        "symptoms": ["ZqxSymptomMarker"], "status": "final",
        "diagnoses": [{"icd10_code": "N18.32", "description": "ZqxDxMarker", "add_to_problem_list": True}]})
    assert enc.status_code == 201, enc.text
    assert (await api.get("/patients", params={"q": "Zqxmarker"})).status_code == 200
    assert (await api.get(f"/internal/patients/{pid}/chart")).status_code == 200
    assert (await api.get(f"/patients/{pid}")).status_code == 200
    stale = await api.patch(f"/patients/{pid}", json={"version": 1, "phone": "+91 9000099999"})   # a 409 path
    assert stale.status_code == 409
    bad = await api.post("/patients", json={"first_name": "Zqxmarkerfirst", "last_name": "Zqxmarkerlast",
                                            "date_of_birth": "1970-01-01", "sex": "M", "phone": "Zqxbadphone"})
    assert bad.status_code == 422                                                       # a 422 that carries a marker

    lines = service_lines(log_buffer)
    assert len(lines) >= 8, "the service should have logged its requests"
    output = log_buffer.getvalue()
    own = json.dumps(lines)
    for marker in MARKERS:
        assert marker not in own, f"PHI marker {marker!r} leaked into the service logs"
    assert "Zqxmarker" not in own and "Zqxmarker" not in "\n".join(
        raw for raw in output.splitlines() if '"logger":"httpx' not in raw)
    assert any(doc.get("event") == "http.request" and doc.get("route") == "/patients/{pid}" for doc in lines)


def test_unexpected_exception_logs_do_not_carry_messages():
    """The catch-all logs the exception TYPE only: messages can echo request data."""
    from app.core.logging import JsonFormatter
    try:
        raise ValueError("Zqxmarkerlast leaked via an exception message")
    except ValueError:
        import sys
        record = logging.LogRecord("t", logging.ERROR, "", 0, "unhandled", (), sys.exc_info())
    out = JsonFormatter("patient-svc").format(record)
    assert "Zqxmarkerlast" not in out and "ValueError" in out


# ---------------------------------- request-size limit -------------------------------------------
LIMIT = 600


@pytest.fixture
async def small(clock, jwks, directory, sign, db_engine):
    app = create_app(make_settings(max_body_bytes=LIMIT), clock=clock, jwks=jwks, directory=directory)
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"Authorization": f"Bearer {sign()}"}) as c:
            yield c


def patient_json(total_bytes: int | None = None) -> bytes:
    body = {"first_name": "A", "last_name": "B", "date_of_birth": "1980-01-01", "sex": "M", "past_medical_history": ""}
    if total_bytes is not None:
        pad = total_bytes - len(json.dumps(body, separators=(",", ":")))
        body["past_medical_history"] = "x" * pad
        assert len(json.dumps(body, separators=(",", ":"))) == total_bytes
    return json.dumps(body, separators=(",", ":")).encode()


async def test_oversized_body_with_content_length_is_413(small):
    r = await small.post("/patients", content=b"x" * (LIMIT + 1), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    error = r.json()["error"]
    assert error["code"] == "PAYLOAD_TOO_LARGE" and error["request_id"] == r.headers["x-request-id"]


async def test_oversized_chunked_body_is_413(small):
    async def chunks():
        for _ in range(5):                                   # 5 x 200 = 1000 bytes > 600, no Content-Length
            yield b"x" * 200

    request = small.build_request("POST", "/patients", content=chunks(), headers={"Content-Type": "application/json"})
    assert "content-length" not in request.headers
    r = await small.send(request)
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_body_exactly_at_the_limit_is_accepted(small):
    r = await small.post("/patients", content=patient_json(LIMIT), headers={"Content-Type": "application/json"})
    assert r.status_code == 201, r.text


async def test_one_byte_over_the_limit_is_rejected(small):
    r = await small.post("/patients", content=patient_json(LIMIT + 1), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
