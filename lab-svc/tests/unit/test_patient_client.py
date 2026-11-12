"""patient-svc client resilience policy (HLD 9): retries, timeouts, failure mapping, header forwarding."""
from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest

from app.core.errors import NotFound, UpstreamUnavailable
from app.services.patient_client import PatientClient
from tests.conftest import make_settings

PID = uuid.uuid4()
OK = {"id": str(PID), "sex": "F", "date_of_birth": "1980-02-29"}


def client(handler, **kw) -> PatientClient:
    return PatientClient(make_settings(upstream_max_retries=2, **kw), transport=httpx.MockTransport(handler))


async def test_success_and_forwarded_headers() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        seen["path"] = req.url.path
        return httpx.Response(200, json=OK)

    b = await client(handler).basic(PID, "Bearer abc", "req-1")
    assert (b.sex, b.date_of_birth) == ("F", date(1980, 2, 29))
    assert seen["authorization"] == "Bearer abc" and seen["x-request-id"] == "req-1"
    assert seen["path"] == f"/internal/patients/{PID}/basic"


async def test_retries_503_then_succeeds() -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=OK)

    assert (await client(handler).basic(PID, "Bearer x", None)).sex == "F"
    assert len(calls) == 3                                     # 1 try + max 2 retries


async def test_gives_up_after_retries_with_502() -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502)

    with pytest.raises(UpstreamUnavailable) as e:
        await client(handler).basic(PID, "Bearer x", None)
    assert len(calls) == 3 and e.value.details == [{"upstream": "patient-svc"}]


async def test_connect_errors_are_retried() -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("refused")

    with pytest.raises(UpstreamUnavailable):
        await client(handler).basic(PID, "Bearer x", None)
    assert len(calls) == 3


async def test_read_timeout_is_not_retried() -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UpstreamUnavailable):
        await client(handler).basic(PID, "Bearer x", None)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_other_errors_fail_fast(status: int) -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(UpstreamUnavailable):
        await client(handler).basic(PID, "Bearer x", None)
    assert len(calls) == 1


async def test_404_is_not_found_and_not_retried() -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(NotFound):
        await client(handler).basic(PID, "Bearer x", None)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [{"sex": "M"}, {"sex": "M", "date_of_birth": "nope"}, ["x"]])
async def test_malformed_response_is_an_upstream_failure(body) -> None:
    with pytest.raises(UpstreamUnavailable):
        await client(lambda _: httpx.Response(200, json=body)).basic(PID, "Bearer x", None)
