import pytest

from tests.asgi_raw import call

UUID = "0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69"


def nothing_reached_a_service(pipe) -> bool:
    return all(not rec.requests for rec in pipe.ups.values())


@pytest.mark.parametrize(
    "path",
    ["/api/internal/patients/x/basic", "/api/internal", "/api/internal/", f"/api/internal/patients/{UUID}/chart",
     "/api/INTERNAL/x", "/api/unknown", "/api", "/api/", "/api/encountersX", "/api/patientsX",
     "/api/docs", "/api/openapi.json", "/api/health", "/api/ready", "/api/metrics",
     "/api/.well-known/jwks.json"],
)
async def test_internal_and_unknown_prefixes_are_404(pipe, path):
    r = await call(pipe.app, "GET", path, headers=list(pipe.auth.items()))
    assert r.status == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert nothing_reached_a_service(pipe)


async def test_internal_is_404_even_without_a_token_so_nothing_is_confirmed(pipe):
    r = await call(pipe.app, "GET", "/api/internal/patients/x/basic")
    assert r.status == 404


@pytest.mark.parametrize(
    "path",
    ["/api/labs/../internal/labs/status", "/api/labs/%2e%2e/internal", "/api/labs/%2E%2E/internal",
     "/api/labs/%252e%252e/internal", "/api//patients", "/api/labs/a%2fb", "/api/labs/a%2Fb",
     "/api/x%00", "/api/labs/%5c..", "/api/labs/<script>", "/api/patients/abc%20def", "/api/patients/./x",
     "/api/patients/..", "/api/auth/../internal"],
)
async def test_traversal_and_odd_encodings_are_400_invalid_path(pipe, path):
    r = await call(pipe.app, "GET", path, headers=list(pipe.auth.items()))
    assert r.status == 400 and r.json()["error"]["code"] == "INVALID_PATH"
    assert nothing_reached_a_service(pipe)


async def test_a_backslash_path_is_never_forwarded(pipe):
    """The router may 404 it before the pipeline; if it gets in, safe_segments answers 400. Never a proxy call."""
    bad = "/api" + chr(92) + "labs"
    r = await call(pipe.app, "GET", bad, headers=list(pipe.auth.items()))
    assert r.status in (400, 404) and nothing_reached_a_service(pipe)


async def test_service_documentation_and_health_are_not_addressable(pipe):
    for path in ("/api/docs", "/api/redoc", "/api/openapi.json", "/api/health", "/api/metrics"):
        assert (await call(pipe.app, "GET", path, headers=list(pipe.auth.items()))).status == 404
    assert nothing_reached_a_service(pipe)


async def test_every_upstream_path_starts_with_an_allow_listed_prefix(pipe):
    for path in ("/api/auth/me", "/api/patients", "/api/encounters", "/api/labs/x", "/api/ai/x", "/api/insights/x"):
        await pipe.client.get(path, headers=pipe.auth)
    seen = [r.url.path for rec in pipe.ups.values() for r in rec.requests]
    assert len(seen) == 6
    assert all(p.split("/")[1] in {"auth", "patients", "encounters", "labs", "ai", "insights"} for p in seen)
    assert not any("internal" in p for p in seen)


async def test_url_too_long_is_414(make_pipe):
    p = await make_pipe(max_url_bytes=200)
    r = await call(p.app, "GET", "/api/patients", query=b"q=" + b"a" * 300, headers=list(p.auth.items()))
    assert r.status == 414 and r.json()["error"]["code"] == "URI_TOO_LONG"
    assert nothing_reached_a_service(p)


async def test_500_uuids_fit_in_the_url_limit(pipe):
    ids = ",".join(f"{i:08x}-0000-4000-8000-{i:012x}" for i in range(500))
    r = await call(pipe.app, "GET", "/api/patients", query=f"ids={ids}".encode(), headers=list(pipe.auth.items()))
    assert r.status == 200


@pytest.mark.parametrize("method", ["HEAD", "TRACE", "CONNECT"])
async def test_unrouted_methods_are_405_in_the_envelope(pipe, method):
    r = await call(pipe.app, method, "/api/patients", headers=list(pipe.auth.items()))
    assert r.status == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert nothing_reached_a_service(pipe)


async def test_plain_options_is_answered_by_the_gateway_and_never_forwarded(pipe):
    r = await pipe.client.options("/api/patients")
    assert r.status_code == 204 and "GET" in r.headers["allow"]
    assert nothing_reached_a_service(pipe)


async def test_prefix_of_a_service_that_is_not_deployed_is_503(make_pipe):
    p = await make_pipe(lab_svc_url="", ai_svc_url="")
    for path in ("/api/labs/patients/x/results", "/api/ai/summaries/1", "/api/insights/x"):
        r = await p.client.get(path, headers=p.auth)
        err = r.json()["error"]
        assert r.status_code == 503 and err["code"] == "UPSTREAM_NOT_DEPLOYED"
    assert (await p.client.get("/api/patients", headers=p.auth)).status_code == 200      # the rest works
    assert (await p.client.get("/api/labs/x", headers=p.auth)).json()["error"]["details"] == [{"upstream": "lab"}]
