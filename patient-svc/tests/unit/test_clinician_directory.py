"""ClinicianDirectory against a mocked auth-svc /auth/me (httpx.MockTransport)."""
from __future__ import annotations

import logging
import uuid

import httpx
import pytest

from app.services.clinician_directory import ClinicianDirectory
from tests.conftest import make_settings

UID = uuid.UUID("5b1e0000-0000-4000-8000-000000000001")
TOKEN = "Bearer SECRET.TOKEN.VALUE"
NAME = "Dr. Zq Marker-Name"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def me_body(uid: uuid.UUID = UID, full_name: object = NAME) -> dict:
    return {"id": str(uid), "email": "a@b.test", "full_name": full_name, "role": "clinician", "last_login_at": None}


def make(handler, clock: Clock | None = None, **settings) -> tuple[ClinicianDirectory, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    d = ClinicianDirectory(make_settings(**settings), transport=httpx.MockTransport(wrapped),
                           mono=clock or Clock())
    return d, seen


async def test_success_forwards_the_callers_token_and_request_id():
    d, seen = make(lambda r: httpx.Response(200, json=me_body()))
    assert await d.name_for(UID, TOKEN, "req-abc") == NAME
    assert seen[0].headers["authorization"] == TOKEN and seen[0].headers["x-request-id"] == "req-abc"
    assert str(seen[0].url) == "http://auth-svc:8000/auth/me"


async def test_cache_hit_and_miss():
    d, seen = make(lambda r: httpx.Response(200, json=me_body()))
    await d.name_for(UID, TOKEN, None)
    await d.name_for(UID, TOKEN, None)
    assert len(seen) == 1                                  # second call served from the cache
    await d.name_for(uuid.uuid4(), TOKEN, None)            # different user: miss (and an id mismatch -> None)
    assert len(seen) == 2


async def test_positive_ttl_expiry_refetches():
    clock = Clock()
    d, seen = make(lambda r: httpx.Response(200, json=me_body()), clock, clinician_name_cache_ttl_s=600)
    await d.name_for(UID, TOKEN, None)
    clock.t += 599
    await d.name_for(UID, TOKEN, None)
    assert len(seen) == 1
    clock.t += 2
    await d.name_for(UID, TOKEN, None)
    assert len(seen) == 2


async def test_negative_entries_expire_much_sooner_than_positive_ones():
    clock = Clock()
    d, seen = make(lambda r: httpx.Response(503), clock, clinician_name_negative_ttl_s=30)
    assert await d.name_for(UID, TOKEN, None) is None
    clock.t += 29
    assert await d.name_for(UID, TOKEN, None) is None
    assert len(seen) == 1                                  # outage: auth-svc is not hammered
    clock.t += 2
    await d.name_for(UID, TOKEN, None)
    assert len(seen) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_http_errors_return_none_without_retry(status):
    d, seen = make(lambda r: httpx.Response(status))
    assert await d.name_for(UID, TOKEN, None) is None
    assert len(seen) == 1


async def test_read_timeout_returns_none_without_retry():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    d, seen = make(boom)
    assert await d.name_for(UID, TOKEN, None) is None
    assert len(seen) == 1


async def test_connect_error_is_retried_exactly_once():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    d, seen = make(refuse)
    assert await d.name_for(UID, TOKEN, None) is None
    assert len(seen) == 2


async def test_connect_error_then_success_recovers():
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=me_body())

    d, _ = make(flaky)
    assert await d.name_for(UID, TOKEN, None) == NAME


@pytest.mark.parametrize("body", [
    "not json", [], {"id": "garbage", "full_name": NAME}, me_body(uuid.uuid4()),      # id mismatch
    me_body(full_name=None), me_body(full_name=""), me_body(full_name="   "), me_body(full_name=42),
    me_body(full_name="x" * 121),
])
async def test_malformed_body_or_id_mismatch_returns_none(body):
    def respond(request):
        return httpx.Response(200, content=body.encode()) if isinstance(body, str) else httpx.Response(200, json=body)

    d, _ = make(respond)
    assert await d.name_for(UID, TOKEN, None) is None


async def test_name_is_stripped_and_length_bounds():
    d, _ = make(lambda r: httpx.Response(200, json=me_body(full_name="  " + "x" * 120 + "  ")))
    assert await d.name_for(UID, TOKEN, None) == "x" * 120


async def test_cache_size_cap_evicts_the_oldest():
    d, seen = make(lambda r: httpx.Response(200, json=me_body(uuid.UUID(r.headers["x-request-id"]))),
                   clinician_name_cache_max=3)
    ids = [uuid.uuid4() for _ in range(4)]
    for i in ids:
        await d.name_for(i, TOKEN, str(i))
    assert len(d._cache) == 3 and ids[0] not in d._cache and ids[3] in d._cache
    n = len(seen)
    await d.name_for(ids[3], TOKEN, str(ids[3]))
    assert len(seen) == n                                   # newest still cached
    await d.name_for(ids[0], TOKEN, str(ids[0]))
    assert len(seen) == n + 1                               # evicted one is fetched again


async def test_logs_never_contain_the_name_or_the_token(caplog):
    caplog.set_level(logging.DEBUG)
    for handler in (lambda r: httpx.Response(401), lambda r: httpx.Response(200, json=me_body(uuid.uuid4()))):
        d, _ = make(handler)
        await d.name_for(UID, TOKEN, "req-1")
    d, _ = make(lambda r: httpx.Response(200, json=me_body()))
    await d.name_for(UID, TOKEN, "req-1")                   # a success is logged too (nothing here)
    output = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "clinician_name_unavailable" in output
    for secret in (NAME, "SECRET.TOKEN.VALUE", "a@b.test"):
        assert secret not in output


async def test_never_raises():
    class Broken(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise RuntimeError("unexpected")

    d = ClinicianDirectory(make_settings(), transport=Broken())
    assert await d.name_for(UID, TOKEN, None) is None
