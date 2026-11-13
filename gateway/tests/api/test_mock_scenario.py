"""X-Mock-Scenario (G7): forwarded only outside production and only to ai-svc; CORS lists it only outside production."""
import pytest
from starlette.datastructures import Headers

from app.services.headers import upstream_request_headers

ORIGIN = "http://localhost:4200"
PROD = dict(environment="production", cors_allowed_origins="https://emr.example.org", docs_enabled=False,
            metrics_enabled=True, metrics_token="not-a-real-token", rate_limit_enabled=True, hsts_enabled=True)
SCENARIO = {"X-Mock-Scenario": "invalid_then_valid"}


def sent(pipe, name: str) -> dict[str, str]:
    return dict(pipe.ups[name].last.headers)


@pytest.mark.parametrize("environment", ["development", "test"])
async def test_ai_requests_carry_the_header_outside_production(make_pipe, environment):
    pipe = await make_pipe(environment=environment)
    r = await pipe.client.post("/api/ai/patients/abc/summary", headers={**pipe.auth, **SCENARIO})
    assert r.status_code == 200
    assert sent(pipe, "ai")["x-mock-scenario"] == "invalid_then_valid"


async def test_insights_is_also_the_ai_upstream(make_pipe):
    pipe = await make_pipe()
    await pipe.client.get("/api/insights/dashboard", headers={**pipe.auth, **SCENARIO})
    assert sent(pipe, "ai")["x-mock-scenario"] == "invalid_then_valid"


@pytest.mark.parametrize(("path", "upstream"), [("/api/patients", "patient"), ("/api/labs/tests", "lab"),
                                                ("/api/encounters", "patient")])
async def test_other_routes_never_get_the_header(make_pipe, path, upstream):
    pipe = await make_pipe()
    await pipe.client.get(path, headers={**pipe.auth, **SCENARIO})
    assert "x-mock-scenario" not in sent(pipe, upstream)


async def test_auth_route_never_gets_the_header(make_pipe):
    pipe = await make_pipe()
    await pipe.client.post("/api/auth/login", headers=SCENARIO, json={})
    assert "x-mock-scenario" not in sent(pipe, "auth")


async def test_in_production_the_header_is_dropped_even_for_ai(make_pipe):
    pipe = await make_pipe(**PROD)
    r = await pipe.client.post("/api/ai/patients/abc/summary", headers={**pipe.auth, **SCENARIO})
    assert r.status_code == 200
    assert "x-mock-scenario" not in sent(pipe, "ai")


async def test_preflight_allows_the_header_only_outside_production(make_pipe):
    ask = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "authorization,x-mock-scenario"}
    dev = await make_pipe()
    assert "X-Mock-Scenario" in (await dev.client.options("/api/ai/x", headers=ask)).headers[
        "access-control-allow-headers"]
    prod = await make_pipe(**PROD)
    r = await prod.client.options("/api/ai/x", headers={**ask, "Origin": "https://emr.example.org"})
    assert r.status_code == 204 and "X-Mock-Scenario" not in r.headers["access-control-allow-headers"]


def test_header_function_default_is_to_drop_it():
    out = dict(upstream_request_headers(Headers({"X-Mock-Scenario": "success"}), client_ip="1.1.1.1",
                                        request_id="req-1", scheme="http", forward_cookies=False))
    assert "x-mock-scenario" not in out
