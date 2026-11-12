import logging

import httpx
import pytest

from app.core.metrics import HTTP_DURATION, INFLIGHT, UPSTREAM_UP


async def probe(p):
    await p.app.state.prober.probe_once()


def health_handler(status_by_upstream):
    return lambda name: (lambda req: httpx.Response(status_by_upstream.get(name, 200), json={"status": "ok"}))


# ---- /health -------------------------------------------------------------------------------------
async def test_health_needs_nothing(make_pipe):
    p = await make_pipe()
    r = await p.client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert not any(rec.requests for rec in p.ups.values())             # no dependency is checked


# ---- /ready --------------------------------------------------------------------------------------
async def test_ready_before_the_first_probe_is_not_ready(pipe):
    r = await pipe.client.get("/ready")
    err = r.json()["error"]
    assert r.status_code == 503 and err["code"] == "NOT_READY"
    assert err["details"] == [{"check": "upstream:auth", "status": "unknown"}]


async def test_ready_when_jwks_is_loaded_and_auth_is_up(pipe):
    await probe(pipe)
    r = await pipe.client.get("/ready")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ready"
    assert body["jwks"]["keys"] == 1 and body["jwks"]["age_s"] == 0.0
    assert body["upstreams"] == {"auth": "up", "patient": "up", "lab": "up", "ai": "up"}


async def test_ready_lists_not_configured_upstreams(make_pipe):
    p = await make_pipe(lab_svc_url="", ai_svc_url="")
    await probe(p)
    assert (await p.client.get("/ready")).json()["upstreams"] == {
        "auth": "up", "patient": "up", "lab": "not_configured", "ai": "not_configured"}


async def test_ready_fails_when_auth_is_down(pipe):
    pipe.ups["auth"]._handler = lambda req: httpx.Response(503)
    await probe(pipe)
    r = await pipe.client.get("/ready")
    assert r.status_code == 503 and r.json()["error"]["details"] == [{"check": "upstream:auth", "status": "down"}]


async def test_ready_fails_when_auth_is_unreachable(pipe):
    def refuse(request):
        raise httpx.ConnectError("refused")

    pipe.ups["auth"]._handler = refuse
    await probe(pipe)
    assert (await pipe.client.get("/ready")).status_code == 503


async def test_a_down_lab_or_patient_service_does_not_make_the_gateway_not_ready(pipe):
    """ADR-G11: patient screens must keep working when lab-svc is down."""
    pipe.ups["lab"]._handler = lambda req: httpx.Response(500)
    pipe.ups["patient"]._handler = lambda req: httpx.Response(503)
    await probe(pipe)
    r = await pipe.client.get("/ready")
    assert r.status_code == 200 and r.json()["upstreams"]["lab"] == "down"


async def test_ready_requires_follows_the_setting(make_pipe):
    p = await make_pipe(ready_requires="auth,patient")
    p.ups["patient"]._handler = lambda req: httpx.Response(503)
    await probe(p)
    r = await p.client.get("/ready")
    assert r.status_code == 503 and r.json()["error"]["details"] == [{"check": "upstream:patient", "status": "down"}]


async def test_ready_fails_without_keys(make_pipe):
    p = await make_pipe()
    await probe(p)
    p.app.state.jwks._last_success = None
    r = await p.client.get("/ready")
    assert r.status_code == 503 and {"check": "jwks", "status": "failed"} in r.json()["error"]["details"]


async def test_ready_fails_when_the_keys_are_older_than_the_staleness_cap(pipe):
    await probe(pipe)
    pipe.clock.advance(86_401)
    r = await pipe.client.get("/ready")
    assert r.status_code == 503 and {"check": "jwks", "status": "failed"} in r.json()["error"]["details"]

    async def auth_svc_is_down():
        raise ConnectionError("auth-svc unreachable")

    pipe.app.state.jwks._fetch = auth_svc_is_down
    pipe.clock.advance(31)                                             # past the refetch spacing
    assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 401   # no key, no access


async def test_prober_logs_transitions_and_sets_the_gauge(pipe, caplog):
    with caplog.at_level(logging.INFO, logger="gateway.prober"):
        await probe(pipe)
        pipe.ups["lab"]._handler = lambda req: httpx.Response(500)
        await probe(pipe)
        await probe(pipe)                                              # no change, no new line
    changes = [(r.upstream, r.to) for r in caplog.records if r.getMessage() == "gateway.upstream.health_changed"]
    assert ("auth", "up") in changes and ("lab", "down") in changes and changes.count(("lab", "down")) == 1
    assert UPSTREAM_UP.labels(upstream="lab")._value.get() == 0
    assert UPSTREAM_UP.labels(upstream="auth")._value.get() == 1


async def test_prober_uses_a_short_timeout_and_recovers(pipe):
    pipe.ups["auth"]._handler = lambda req: httpx.Response(500)
    await probe(pipe)
    assert pipe.app.state.prober.state("auth") == "down"
    pipe.ups["auth"]._handler = lambda req: httpx.Response(200, json={})
    await probe(pipe)
    assert pipe.app.state.prober.state("auth") == "up"


async def test_routing_never_consults_the_prober(pipe):
    pipe.ups["patient"]._handler = lambda req: httpx.Response(503)
    await probe(pipe)                                                  # patient is marked down ...
    pipe.ups["patient"]._handler = lambda req: httpx.Response(200, json={"ok": True})
    assert (await pipe.client.get("/api/patients", headers=pipe.auth)).status_code == 200   # ... but still routed


# ---- /metrics ------------------------------------------------------------------------------------
async def test_metrics_open_without_a_token_in_development(pipe):
    await pipe.client.get("/api/patients", headers=pipe.auth)
    r = await pipe.client.get("/metrics")
    assert r.status_code == 200 and "http_request_duration_seconds" in r.text
    for name in ("gateway_upstream_duration_seconds", "gateway_rate_limited_total", "gateway_jwks_refresh_total",
                 "gateway_jwks_keys", "gateway_auth_failures_total", "gateway_upstream_errors_total",
                 "gateway_inflight_requests"):
        assert name in r.text, name


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "Basic s3cret-token", "s3cret-token", "Bearer "])
async def test_metrics_with_a_token_rejects_everything_else(make_pipe, header):
    p = await make_pipe(metrics_token="s3cret-token")
    r = await p.client.get("/metrics", headers={"Authorization": header} if header is not None else {})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


async def test_metrics_with_the_right_token(make_pipe):
    p = await make_pipe(metrics_token="s3cret-token")
    assert (await p.client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})).status_code == 200


async def test_metrics_disabled_is_a_plain_404(make_pipe):
    p = await make_pipe(metrics_enabled=False)
    assert (await p.client.get("/metrics")).status_code == 404


async def test_probes_and_metrics_stay_out_of_the_histogram_but_are_access_logged(pipe, caplog):
    def counted(route: str) -> float:
        return sum(s.value for m in HTTP_DURATION.collect() for s in m.samples
                   if s.name.endswith("_count") and s.labels["route"] == route)

    before = {r: counted(r) for r in ("/health", "/ready", "/metrics")}
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await pipe.client.get("/health")
        await pipe.client.get("/ready")
        await pipe.client.get("/metrics")
    assert {r: counted(r) for r in before} == before
    assert [r.route for r in caplog.records if r.name == "nephro.access"] == ["/health", "/ready", "/metrics"]


async def test_proxied_requests_are_in_the_histogram_under_their_template(pipe):
    def counted() -> float:
        return sum(s.value for m in HTTP_DURATION.collect() for s in m.samples
                   if s.name.endswith("_count") and s.labels["route"] == "/api/labs/patients/{id}/trends")

    before = counted()
    await pipe.client.get("/api/labs/patients/0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69/trends", headers=pipe.auth)
    assert counted() == before + 1


async def test_inflight_gauge_returns_to_its_starting_value(pipe):
    before = INFLIGHT._value.get()
    await pipe.client.get("/api/patients", headers=pipe.auth)
    assert INFLIGHT._value.get() == before


# ---- /docs ---------------------------------------------------------------------------------------
async def test_docs_are_off_by_default(pipe):
    assert (await pipe.client.get("/docs")).status_code == 404
    assert (await pipe.client.get("/docs/patient/openapi.json")).status_code == 404


SPEC = {"openapi": "3.1.0", "info": {"title": "svc", "version": "1"}, "paths": {"/patients": {"get": {}}},
        "servers": [{"url": "http://patient-svc:8000"}]}


async def test_docs_page_lists_every_configured_service(make_pipe):
    p = await make_pipe(docs_enabled=True, ai_svc_url="")
    r = await p.client.get("/docs")
    assert r.status_code == 200 and "swagger-ui" in r.text
    for name in ("auth", "patient", "lab"):
        assert f"/docs/{name}/openapi.json" in r.text
    assert "/docs/ai/openapi.json" not in r.text


async def test_spec_is_rewritten_to_go_through_the_gateway(make_pipe):
    p = await make_pipe(docs_enabled=True)
    p.ups["patient"]._handler = lambda req: httpx.Response(200, json=SPEC)
    r = await p.client.get("/docs/patient/openapi.json")
    spec = r.json()
    assert r.status_code == 200 and spec["servers"] == [{"url": "/api"}]
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert spec["security"] == [{"bearerAuth": []}] and spec["paths"] == SPEC["paths"]
    assert p.ups["patient"].last.url.path == "/openapi.json"


async def test_spec_is_cached_for_60_seconds(make_pipe):
    p = await make_pipe(docs_enabled=True)
    p.ups["lab"]._handler = lambda req: httpx.Response(200, json=SPEC)
    await p.client.get("/docs/lab/openapi.json")
    await p.client.get("/docs/lab/openapi.json")
    assert len(p.ups["lab"].requests) == 1


async def test_one_service_failing_does_not_break_the_others(make_pipe):
    p = await make_pipe(docs_enabled=True)
    p.ups["ai"]._handler = lambda req: httpx.Response(404)
    p.ups["auth"]._handler = lambda req: httpx.Response(200, json=SPEC)
    bad = await p.client.get("/docs/ai/openapi.json")
    assert bad.status_code == 502 and bad.json()["error"]["details"] == [{"upstream": "ai"}]
    assert (await p.client.get("/docs/auth/openapi.json")).status_code == 200


async def test_unknown_or_undeployed_service(make_pipe):
    p = await make_pipe(docs_enabled=True, lab_svc_url="")
    assert (await p.client.get("/docs/nope/openapi.json")).status_code == 404
    r = await p.client.get("/docs/lab/openapi.json")
    assert r.status_code == 503 and r.json()["error"]["code"] == "UPSTREAM_NOT_DEPLOYED"


async def test_docs_route_labels_are_literal(make_pipe, caplog):
    p = await make_pipe(docs_enabled=True)
    logging.getLogger().addHandler(caplog.handler)       # create_app() replaced the root handlers (configure_logging)
    p.ups["auth"]._handler = lambda req: httpx.Response(200, json=SPEC)
    with caplog.at_level(logging.INFO, logger="nephro.access"):
        await p.client.get("/docs")
        await p.client.get("/docs/auth/openapi.json")
    assert [r.route for r in caplog.records if r.name == "nephro.access"] == ["/docs", "/docs/{upstream}/openapi.json"]


async def test_docs_cannot_be_enabled_in_production():
    from app.core.config import Settings
    from app.core.guard import ConfigurationError
    from app.main import create_app

    s = Settings(_env_file=None, environment="production", docs_enabled=True, cors_allowed_origins="https://x.example",
                 metrics_token="t", hsts_enabled=True)
    with pytest.raises(ConfigurationError):
        create_app(s)
