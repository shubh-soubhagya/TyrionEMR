"""Insights endpoints against the synthetic seed served by respx (LLD B17.3, B17.6)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.main import create_app
from tests.conftest import Upstreams, make_settings
from tests.fixtures import seed

PID = {s.mrn: str(seed.uid(s.mrn)) for s in seed.SPECS}


def client_for(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                             base_url="http://t", headers={"Authorization": f"Bearer {token}"})


async def test_gaps_for_each_seed_patient(client: httpx.AsyncClient):
    expected = {
        "PT-000103": ["ALLERGY_STATUS_UNKNOWN", "ENCOUNTER_NO_VITALS"],
        "PT-000106": ["CKD_STAGE_MISMATCH"],
        "PT-000110": ["NO_ESTABLISHED_CKD_STAGE", "ACTIVE_MED_PAST_END_DATE"],
        "PT-000102": [],
    }
    for mrn, codes in expected.items():
        r = await client.get(f"/insights/patients/{PID[mrn]}/gaps")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [f["code"] for f in body["findings"]] == codes
        assert body["provenance"] == "rule_engine" and body["rules_version"] == "ai-rules-1"
        assert body["as_of"] == "2026-11-12"
        assert r.headers["cache-control"] == "no-store"


async def test_gaps_shape_counts_attention_and_evidence(client: httpx.AsyncClient):
    body = (await client.get(f"/insights/patients/{PID['PT-000106']}/gaps")).json()
    assert body["counts"] == {"high": 1, "medium": 0, "low": 0}
    f = body["findings"][0]
    assert f["severity"] == "high" and f["kind"] == "inconsistent"
    assert f["evidence"][0]["ref"].startswith("lab:EGFR:") and f["evidence"][0]["tab"] == "labs"
    assert body["attention"]["needs_attention"] is True
    assert body["attention"]["reasons"][0]["severity"] == "warn"
    enc = (await client.get(f"/insights/patients/{PID['PT-000103']}/gaps")).json()["findings"][1]
    assert enc["evidence"][0]["ref"] == "enc:1" and enc["evidence"][0]["type"] == "encounter"


async def test_gaps_unknown_patient_is_404(client: httpx.AsyncClient):
    r = await client.get("/insights/patients/00000000-0000-4000-8000-000000000000/gaps")
    assert r.status_code == 404 and r.json()["error"]["code"] == "PATIENT_NOT_FOUND"


async def test_gaps_rejects_bad_uuid_and_unknown_params(client: httpx.AsyncClient):
    assert (await client.get("/insights/patients/not-a-uuid/gaps")).status_code == 422
    r = await client.get(f"/insights/patients/{PID['PT-000102']}/gaps?verbose=1")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "verbose"


async def test_gaps_forwards_token_and_request_id(client: httpx.AsyncClient, upstreams: Upstreams):
    await client.get(f"/insights/patients/{PID['PT-000102']}/gaps", headers={"X-Request-ID": "trace-1"})
    assert upstreams.calls
    for _, headers in upstreams.calls:
        assert headers["authorization"] == client.headers["authorization"] and headers["x-request-id"] == "trace-1"


async def test_dashboard_matches_the_design_numbers(client: httpx.AsyncClient):
    r = await client.get("/insights/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kpis"] == {"patients": 10, "need_attention": 6, "critical_results": 1, "rapid_decline": 4}
    assert d["egfr_distribution"] == {"G1": 0, "G2": 3, "G3a": 2, "G3b": 2, "G4": 1, "G5": 1, "none": 1}
    assert d["as_of"] == "2026-11-12" and d["rules_version"] == "ai-rules-1"
    first = d["attention"][0]
    assert first["mrn"] == "PT-000109" and first["name"] == "Aditya Singh"      # critical results rank first
    assert [x["text"] for x in first["reasons"]][:2] == ["Critical serum creatinine 5.62 mg/dL",
                                                          "Critical potassium 6.2 mmol/L"]
    assert first["reasons"][-1]["text"].startswith("eGFR falling")
    assert d["abnormal_results"][0]["flag"].startswith("critical")
    assert len(d["abnormal_results"]) <= 8


async def test_worklist_ids_and_order(client: httpx.AsyncClient):
    body = (await client.get("/insights/worklist?attention=true")).json()
    assert body["total"] == 6
    ids = [i["patient_id"] for i in body["items"]]
    assert ids[0] == PID["PT-000109"]
    assert set(ids) == {PID[m] for m in ("PT-000101", "PT-000104", "PT-000106", "PT-000108", "PT-000109", "PT-000110")}
    assert [i["rank"] for i in body["items"]] == sorted(i["rank"] for i in body["items"])


async def test_worklist_only_accepts_attention_true(client: httpx.AsyncClient):
    assert (await client.get("/insights/worklist?attention=false")).status_code == 422
    assert (await client.get("/insights/worklist?page=2")).status_code == 422


async def test_dashboard_and_worklist_share_one_snapshot(client: httpx.AsyncClient, upstreams: Upstreams):
    await client.get("/insights/dashboard")
    await client.get("/insights/worklist")
    assert upstreams.calls_to("/internal/patients/charts") == 1 and upstreams.calls_to("/internal/labs/status") == 1


async def test_no_cache_header_forces_recompute(client: httpx.AsyncClient, upstreams: Upstreams):
    await client.get("/insights/dashboard")
    await client.get("/insights/dashboard", headers={"Cache-Control": "no-cache"})
    assert upstreams.calls_to("/internal/patients/charts") == 2


async def test_snapshot_expires_after_ttl(client: httpx.AsyncClient, upstreams: Upstreams, app):
    t = [0.0]
    app.state.insights._cache._mono = lambda: t[0]
    await client.get("/insights/dashboard")
    t[0] = 29
    await client.get("/insights/dashboard")
    assert upstreams.calls_to("/internal/patients/charts") == 1
    t[0] = 31
    await client.get("/insights/dashboard")
    assert upstreams.calls_to("/internal/patients/charts") == 2


async def test_concurrent_dashboard_calls_compute_once(client: httpx.AsyncClient, upstreams: Upstreams):
    upstreams.delay_s = 0.05
    results = await asyncio.gather(*(client.get("/insights/dashboard") for _ in range(8)))
    assert all(r.status_code == 200 for r in results)
    assert upstreams.calls_to("/internal/patients/charts") == 1 and upstreams.calls_to("/internal/labs/status") == 1


@pytest.mark.parametrize(("prefix", "upstream"), [("/internal/labs/status", "lab-svc"),
                                                  ("/internal/patients/charts", "patient-svc")])
async def test_one_failed_bulk_read_fails_the_whole_dashboard(client: httpx.AsyncClient, upstreams: Upstreams,
                                                              prefix, upstream):
    upstreams.fail[prefix] = 503
    r = await client.get("/insights/dashboard")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert r.json()["error"]["details"] == [{"upstream": upstream}]


async def test_failed_snapshot_is_not_served_stale_afterwards(client: httpx.AsyncClient, upstreams: Upstreams):
    assert (await client.get("/insights/dashboard")).status_code == 200
    upstreams.fail["/internal/labs/status"] = 503
    assert (await client.get("/insights/dashboard", headers={"Cache-Control": "no-cache"})).status_code == 502
    assert (await client.get("/insights/dashboard")).status_code == 502      # nothing stale to serve


async def test_too_many_pages_is_503_insights_too_large(clock, jwks, upstreams, sign):
    app = create_app(make_settings(insights_bulk_page=2, insights_max_pages=2), clock=clock, jwks=jwks)
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        r = await client_for(app, sign()).get("/insights/dashboard")
        assert r.status_code == 503 and r.json()["error"]["code"] == "INSIGHTS_TOO_LARGE"


async def test_insights_keep_working_when_the_database_is_down(clock, jwks, upstreams, sign):
    app = create_app(make_settings(ai_database_url="postgresql+asyncpg://x:x@127.0.0.1:1/none"),
                     clock=clock, jwks=jwks)
    async with app.router.lifespan_context(app):
        await jwks.refresh("test")
        c = client_for(app, sign())
        assert (await c.get("/insights/dashboard")).status_code == 200
        assert (await c.get("/ready")).status_code == 503


async def test_gaps_response_carries_no_identifiers(client: httpx.AsyncClient):
    text = (await client.get(f"/insights/patients/{PID['PT-000106']}/gaps")).text
    assert "Lakshmi" not in text and "Iyer" not in text and "1958" not in text
