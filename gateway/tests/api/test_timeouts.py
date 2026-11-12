import asyncio

import httpx
import pytest

from tests.proxy_harness import Recorder, build_app, client_for


def failing(exc: Exception):
    def handler(request):
        raise exc

    return handler


@pytest.fixture
def make_gw(proxy_settings):
    async def build(handler, **settings):
        rec = Recorder(handler)
        app, registry = build_app(proxy_settings(**settings), {"patient": rec, "auth": Recorder(), "lab": Recorder(),
                                                                "ai": Recorder()})
        return rec, client_for(app), registry

    return build


async def test_slow_upstream_is_504_in_the_envelope(make_gw):
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    rec, client, reg = await make_gw(slow, upstream_default_timeout_s=0.05)
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 504
    err = r.json()["error"]
    assert err["code"] == "UPSTREAM_TIMEOUT" and err["details"] == [{"upstream": "patient"}]
    assert err["request_id"] == r.headers["x-request-id"]
    await reg.aclose()


async def test_read_timeout_is_504_and_not_retried(make_gw):
    rec, client, reg = await make_gw(failing(httpx.ReadTimeout("slow")))
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 504 and len(rec.requests) == 1                 # no retry after a read timeout
    await reg.aclose()


async def test_connect_error_is_502_after_exactly_one_get_retry(make_gw):
    rec, client, reg = await make_gw(failing(httpx.ConnectError("refused")))
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert len(rec.requests) == 2
    await reg.aclose()


async def test_connect_timeout_is_retried_once_for_get(make_gw):
    rec, client, reg = await make_gw(failing(httpx.ConnectTimeout("no route")))
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 502 and len(rec.requests) == 2
    await reg.aclose()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_writes_are_never_retried(make_gw, method):
    rec, client, reg = await make_gw(failing(httpx.ConnectError("refused")))
    async with client:
        r = await client.request(method, "/api/patients", content=b"{}")
    assert r.status_code == 502 and len(rec.requests) == 1
    await reg.aclose()


async def test_get_retry_succeeds_when_the_second_connect_works(make_gw):
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("blip")
        return httpx.Response(200, json={"ok": True})

    rec, client, reg = await make_gw(flaky)
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 200 and calls["n"] == 2
    await reg.aclose()


async def test_pool_exhaustion_is_503_gateway_busy(make_gw):
    rec, client, reg = await make_gw(failing(httpx.PoolTimeout("no connection")))
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 503 and r.json()["error"]["code"] == "GATEWAY_BUSY"
    assert r.json()["error"]["details"] == [{"upstream": "patient"}] and len(rec.requests) == 1
    await reg.aclose()


@pytest.mark.parametrize("exc", [httpx.ReadError("reset"), httpx.RemoteProtocolError("bad"), httpx.WriteError("x")])
async def test_other_transport_errors_are_502(make_gw, exc):
    rec, client, reg = await make_gw(failing(exc))
    async with client:
        r = await client.get("/api/patients")
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    await reg.aclose()


async def test_insights_gets_the_longer_timeout(proxy_settings):
    from app.routing.table import build_routes

    routes = build_routes(proxy_settings())
    assert routes["insights"].timeout_s == 10.0 and routes["labs"].timeout_s == 5.0


async def test_upstream_down_does_not_affect_another_upstream(make_gw):
    rec, client, reg = await make_gw(failing(httpx.ConnectError("refused")))
    async with client:
        assert (await client.get("/api/patients")).status_code == 502
        assert (await client.get("/api/labs/x")).status_code == 200          # lab has its own client
    await reg.aclose()
