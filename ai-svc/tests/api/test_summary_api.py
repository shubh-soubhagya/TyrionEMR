"""Summary pipeline end to end: MockProvider, real database, faked patient-svc and lab-svc (LLD B17.2, B17.3)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.core.clock import FakeClock
from app.jobs.reaper import reap_once
from app.llm.base import Capabilities, LLMResponse
from app.main import create_app
from tests.conftest import Upstreams, make_settings
from tests.fixtures import seed

pytestmark = pytest.mark.api
PID = {s.mrn: str(seed.uid(s.mrn)) for s in seed.SPECS}
P1, P2 = PID["PT-000101"], PID["PT-000102"]
STEPS = ["open_chart", "gather", "rules", "prepare", "write", "check", "save"]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime.now(UTC))          # rows get the database's real now(): quota day must match


@pytest.fixture
async def make_client(clock, jwks, upstreams: Upstreams, sign, db_engine):
    opened = []

    async def _make(provider=None, **overrides) -> httpx.AsyncClient:
        app = create_app(make_settings(**({"app_env": "dev"} | overrides)), clock=clock, jwks=jwks, provider=provider)
        cm = app.router.lifespan_context(app)
        await cm.__aenter__()
        await jwks.refresh("test")
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                              base_url="http://t", headers={"Authorization": f"Bearer {sign(sub=USER)}"})
        c.app = app                                                       # type: ignore[attr-defined]
        opened.append((cm, c))
        return c

    yield _make
    for cm, c in opened:
        await c.aclose()
        await cm.__aexit__(None, None, None)


USER = str(uuid.uuid4())


@pytest.fixture
async def api(make_client):
    return await make_client()


async def post(c, pid=P1, *, force=False, scenario=None, expect=202):
    r = await c.post(f"/ai/patients/{pid}/summary{'?force=true' if force else ''}",
                     headers={"X-Mock-Scenario": scenario} if scenario else {})
    assert r.status_code == expect, r.text
    return r


async def wait_done(c, sid, limit_s=15.0):  # noqa: ASYNC109
    deadline = asyncio.get_running_loop().time() + limit_s
    while True:
        r = await c.get(f"/ai/summaries/{sid}")
        assert r.status_code == 200, r.text
        if r.json()["status"] != "running":
            return r.json()
        assert asyncio.get_running_loop().time() < deadline, "job did not finish"
        await asyncio.sleep(0.02)


async def run(c, pid=P1, **kw):
    sid = (await post(c, pid, **kw)).json()["summary_id"]
    return await wait_done(c, sid)


# ---- success -----------------------------------------------------------------------------------
async def test_post_returns_202_with_the_seven_steps_and_a_location(api):
    r = await post(api)
    body = r.json()
    assert r.headers["location"] == f"/ai/summaries/{body['summary_id']}"
    assert body["status"] == "running" and body["deduplicated"] is False and body["poll_after_ms"] == 1000
    assert [s["key"] for s in body["progress"]] == STEPS and body["progress"][0]["state"] == "running"
    assert all(s["state"] == "pending" for s in body["progress"][1:])
    await wait_done(api, body["summary_id"])


async def test_success_scenario_completes_with_every_part_of_the_contract(api):
    d = await run(api)
    assert d["status"] == "completed" and d["cached"] is False and d["error_code"] is None
    assert [s["state"] for s in d["progress"]] == ["done"] * 7
    assert d["progress"][5]["note"].endswith("sources found in the record")
    assert d["facts"]["provenance"] == "system_computed_from_patient_records"
    assert d["gaps"]["provenance"] == "rule_engine"
    assert d["ai"]["provenance"] == "ai_generated" and d["ai"]["provider"] == "mock"
    content = d["ai"]["content"]
    assert set(content) == {"history_summary", "comorbidity_summary", "trend_commentary", "abnormal_commentary",
                            "follow_up_considerations", "not_documented"}
    assert content["follow_up_considerations"][0]["consideration"].startswith("Consider")
    assert d["validation"]["schema_valid"] is True and d["validation"]["repaired"] is False
    assert d["validation"]["refs_stripped"] == 0 and d["validation"]["safety_flags"] == 0
    assert d["disclaimer"].startswith("AI-generated summary for clinician review only.")
    assert d["as_of"] and d["generated_at"]
    for ref in d["sources"]:
        assert d["sources"][ref]["label"] and d["sources"][ref]["tab"]
    cited = {r for k in ("history_summary", "comorbidity_summary", "trend_commentary", "abnormal_commentary")
             for r in content[k]["source_refs"]}
    assert cited <= set(d["sources"])                       # every chip resolves


async def test_terminal_rows_are_cacheable_and_running_rows_are_not(api, upstreams):
    upstreams.delay_s = 0.2
    sid = (await post(api)).json()["summary_id"]
    running = await api.get(f"/ai/summaries/{sid}")
    assert running.json()["status"] == "running" and running.headers["cache-control"] == "no-store"
    assert running.json()["facts"] is None and running.json()["ai"] is None and running.json()["disclaimer"]
    await wait_done(api, sid)
    done = await api.get(f"/ai/summaries/{sid}")
    assert done.headers["cache-control"] == "private, max-age=3600, immutable"
    again = await api.get(f"/ai/summaries/{sid}", headers={"If-None-Match": done.headers["etag"]})
    assert again.status_code == 304


async def test_context_view_holds_the_packet_but_never_the_ref_index_or_identifiers(api):
    d = await run(api)
    r = (await api.get(f"/ai/summaries/{d['summary_id']}?include=context")).json()
    text_ = json.dumps(r["context"])
    assert "packet_version" in text_ and "ref_index" not in text_ and "Kulkarni" not in text_
    import re
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", text_)
    assert (await api.get(f"/ai/summaries/{d['summary_id']}?include=nope")).status_code == 422


async def test_unknown_summary_is_404(api):
    r = await api.get(f"/ai/summaries/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SUMMARY_NOT_FOUND"


# ---- cache -------------------------------------------------------------------------------------
async def test_unchanged_data_is_a_cache_hit_with_no_second_llm_call_and_no_new_history(api):
    first = await run(api)
    second = await run(api)
    assert second["cached"] is True and second["cached_from"] == first["summary_id"]
    assert second["summary_id"] != first["summary_id"]
    assert second["ai"] == first["ai"] and second["facts"] == first["facts"] and second["sources"] == first["sources"]
    states = {s["key"]: s["state"] for s in second["progress"]}
    assert states["write"] == states["check"] == states["save"] == "skipped"
    assert second["progress"][3]["note"] == "Same data as an earlier summary"
    assert second["progress"][4]["note"] == "Not needed, reusing the saved summary"
    h = (await api.get(f"/ai/patients/{P1}/summaries")).json()
    assert h["total"] == 1 and h["items"][0]["summary_id"] == first["summary_id"]


async def test_force_bypasses_the_cache(api):
    first = await run(api)
    forced = await run(api, force=True)
    assert forced["cached"] is False and forced["summary_id"] != first["summary_id"]
    assert (await api.get(f"/ai/patients/{P1}/summaries")).json()["total"] == 2


async def test_changed_data_gives_a_new_hash_and_a_fresh_summary(api, upstreams):
    first = await run(api)
    p = upstreams.by_id[P1]
    p["chart"]["medications"].append({"id": str(uuid.uuid4()), "name": "New drug", "dose": "10 mg", "route": "oral",
                                      "frequency": "daily", "start_date": "2026-11-01", "end_date": None,
                                      "status": "active"})
    second = await run(api)
    assert second["cached"] is False and second["summary_id"] != first["summary_id"]


async def test_two_patients_never_share_a_cached_summary(api):
    a, b = await run(api, P1), await run(api, P2)
    assert b["cached"] is False and b["patient_id"] != a["patient_id"]


# ---- repair, safety, degraded ------------------------------------------------------------------
async def test_invalid_then_valid_is_repaired_once(api):
    d = await run(api, scenario="invalid_then_valid")
    assert d["status"] == "completed" and d["validation"]["repaired"] is True
    # with tools on, a non-JSON reply on a tool turn first forces a final turn (no tools), then the repair turn
    assert d["validation"]["repair_reasons"] == ["PARSE"] and d["validation"]["attempts"] == 3


async def test_invalid_twice_is_degraded_with_facts_and_rule_findings(api):
    d = await run(api, scenario="invalid_twice")
    assert d["status"] == "degraded" and d["error_code"] == "LLM_INVALID_OUTPUT"
    assert d["ai"] == {"provenance": "ai_generated", "content": None, "unavailable": True}
    assert d["facts"]["trends"]["EGFR"] and d["gaps"]["findings"] is not None
    assert "could not be verified" in d["error_message"] and d["disclaimer"]
    steps = {s["key"]: s["state"] for s in d["progress"]}
    assert steps["check"] == "failed" and steps["save"] == "skipped"


async def test_bad_refs_are_stripped_and_counted(api):
    d = await run(api, scenario="bad_refs")
    assert d["status"] == "completed" and d["validation"]["refs_stripped"] == 1
    assert "cond:99" not in json.dumps(d["ai"]) and "cond:99" not in d["sources"]


async def test_unsafe_then_safe_is_repaired(api):
    d = await run(api, scenario="unsafe_then_safe")
    assert d["status"] == "completed" and d["validation"]["repaired"] is True
    assert "mg" not in json.dumps(d["ai"]["content"]["follow_up_considerations"])


async def test_unsafe_twice_is_redacted_and_still_completes(api):
    d = await run(api, scenario="unsafe_twice")
    assert d["status"] == "completed" and d["validation"]["safety_flags"] >= 1
    assert d["validation"]["safety_redactions"] and d["ai"]["content"]["follow_up_considerations"] == []
    assert "amlodipine" not in json.dumps(d["ai"])


async def test_timeout_degrades_without_losing_the_facts(make_client):
    c = await make_client(llm_retries=0)
    d = await run(c, scenario="timeout")
    assert d["status"] == "degraded" and d["error_code"] == "LLM_TIMEOUT" and d["facts"] and d["gaps"]


async def test_rate_limit_beyond_the_cap_degrades_immediately(api):
    d = await run(api, scenario="rate_limited")
    assert d["status"] == "degraded" and d["error_code"] == "LLM_RATE_LIMITED"
    assert "usage limit" in d["error_message"]


async def test_demo_scenario_header_is_ignored_outside_dev(make_client):
    c = await make_client(app_env="test")
    d = await run(c, scenario="invalid_twice")
    assert d["status"] == "completed"


async def test_unknown_scenario_is_ignored(api):
    assert (await run(api, scenario="nonsense"))["status"] == "completed"


# ---- failures ----------------------------------------------------------------------------------
async def test_upstream_down_fails_the_job_and_hides_it_from_history(api):
    d = await run(api, scenario="upstream_down")
    assert d["status"] == "failed" and d["error_code"] == "UPSTREAM_UNAVAILABLE"
    assert d["facts"] is None and d["ai"] is None and "could not be loaded" in d["error_message"]
    assert (await api.get(f"/ai/patients/{P1}/summaries")).json()["total"] == 0


async def test_real_upstream_failure_during_gather_fails_the_job(api, upstreams):
    sid = (await post(api)).json()["summary_id"]
    upstreams.fail["/internal/labs/patients"] = 503
    d = await wait_done(api, sid)
    if d["status"] == "completed":                       # raced ahead of the failure being installed
        upstreams.fail["/internal/labs/patients"] = 503
        d = await run(api, force=True)
    assert d["status"] == "failed" and d["error_code"] == "UPSTREAM_UNAVAILABLE"
    assert {s["key"]: s["state"] for s in d["progress"]}["gather"] == "failed"


async def test_unknown_patient_is_404_and_creates_no_row(api, db_engine):
    r = await post(api, "00000000-0000-4000-8000-000000000000", expect=404)
    assert r.json()["error"]["code"] == "PATIENT_NOT_FOUND"
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM ai_summaries"))).scalar() == 0


async def test_patient_svc_down_is_502_and_creates_no_row(api, upstreams, db_engine):
    upstreams.fail["/internal/patients"] = 503
    r = await post(api, expect=502)
    assert r.json()["error"]["details"] == [{"upstream": "patient-svc"}]
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM ai_summaries"))).scalar() == 0


# ---- single-flight, quota, auth ----------------------------------------------------------------
async def test_double_post_returns_the_same_job(api, upstreams):
    upstreams.delay_s = 0.3
    first = (await post(api)).json()
    second = (await post(api)).json()
    assert second["summary_id"] == first["summary_id"] and second["deduplicated"] is True
    await wait_done(api, first["summary_id"])
    assert upstreams.calls_to("/chart") == 1                      # one job, one set of upstream reads


async def test_different_clinicians_run_in_parallel(make_client, sign, upstreams):
    upstreams.delay_s = 0.2
    a = await make_client()
    b = await make_client()
    b.headers["Authorization"] = f"Bearer {sign(sub=str(uuid.uuid4()))}"
    ra, rb = await post(a), await post(b)
    assert ra.json()["summary_id"] != rb.json()["summary_id"] and rb.json()["deduplicated"] is False


async def test_quota_counts_llm_jobs_not_cache_hits_and_answers_429_with_retry_after(make_client):
    c = await make_client(ai_daily_quota_per_user=2)
    await run(c)                                   # original: 1 used
    await run(c)                                   # cache hit: still 1
    await run(c)                                   # cache hit: still 1
    await run(c, force=True)                       # second LLM job: 2 used
    r = await post(c, force=True, expect=429)
    assert r.json()["error"]["code"] == "AI_QUOTA_EXCEEDED"
    assert int(r.headers["retry-after"]) > 0
    assert r.json()["error"]["details"][0]["limit"] == 2


async def test_failed_before_the_llm_does_not_consume_quota(make_client):
    c = await make_client(ai_daily_quota_per_user=1)
    for _ in range(3):
        assert (await run(c, scenario="upstream_down"))["status"] == "failed"
    assert (await run(c))["status"] == "completed"


async def test_token_about_to_expire_is_401_on_post_but_fine_on_get(make_client, sign):
    c = await make_client()
    sid = (await post(c)).json()["summary_id"]
    c.headers["Authorization"] = f"Bearer {sign(sub=USER, ttl=20)}"
    r = await post(c, expect=401)
    assert r.json()["error"]["code"] == "TOKEN_EXPIRED"
    assert (await c.get(f"/ai/summaries/{sid}")).status_code == 200


async def test_auth_on_every_route(api, sign):
    bare = httpx.AsyncClient(transport=api._transport, base_url="http://t")
    sid = uuid.uuid4()
    for method, url in (("POST", f"/ai/patients/{P1}/summary"), ("GET", f"/ai/summaries/{sid}"),
                        ("GET", f"/ai/patients/{P1}/summaries")):
        assert (await bare.request(method, url)).status_code == 401
        r = await bare.request(method, url, headers={"Authorization": f"Bearer {sign(role='admin')}"})
        assert r.status_code == 403


async def test_bad_query_values_are_422(api):
    assert (await api.post(f"/ai/patients/{P1}/summary?force=maybe")).status_code == 422
    assert (await api.post(f"/ai/patients/{P1}/summary?x=1")).status_code == 422
    assert (await api.get(f"/ai/patients/{P1}/summaries?size=0")).status_code == 422
    assert (await api.get(f"/ai/patients/{P1}/summaries?size=51")).status_code == 422


# ---- history -----------------------------------------------------------------------------------
async def test_history_lists_originals_newest_first_and_pages(api):
    ids = [(await run(api, force=True))["summary_id"] for _ in range(3)]
    await run(api)                                                   # cache hit: hidden
    page1 = (await api.get(f"/ai/patients/{P1}/summaries?size=2")).json()
    assert page1["total"] == 3 and [i["summary_id"] for i in page1["items"]] == [ids[2], ids[1]]
    assert page1["items"][0]["progress"] is None and page1["items"][0]["ai"]["content"]
    page2 = (await api.get(f"/ai/patients/{P1}/summaries?size=2&page=2")).json()
    assert [i["summary_id"] for i in page2["items"]] == [ids[0]]
    assert (await api.get(f"/ai/patients/{uuid.uuid4()}/summaries")).json()["total"] == 0


async def test_degraded_originals_appear_in_history_failed_do_not(api):
    await run(api, scenario="invalid_twice")
    await run(api, scenario="upstream_down")
    h = (await api.get(f"/ai/patients/{P1}/summaries")).json()
    assert [i["status"] for i in h["items"]] == ["degraded"]


# ---- reaper, shutdown, deadline ----------------------------------------------------------------
async def test_reaper_fails_a_stale_job_and_the_job_stops_writing(api, upstreams, db_engine):
    upstreams.delay_s = 0.4
    sid = (await post(api)).json()["summary_id"]
    await asyncio.sleep(0.1)
    async with db_engine.begin() as c:
        await c.execute(text("UPDATE ai_summaries SET heartbeat_at = now() - interval '600 seconds'"))
    assert [str(i) for i in await reap_once(api.app.state.sessionmaker, 120)] == [sid]
    await api.app.state.runner.wait_idle()
    d = (await api.get(f"/ai/summaries/{sid}")).json()
    assert d["status"] == "failed" and d["error_code"] == "JOB_TIMEOUT" and d["ai"] is None
    assert d["progress"][1]["state"] == "failed"               # the running step renders as failed (B10.7)
    assert "interrupted" in d["error_message"]


async def test_shutdown_marks_running_jobs_job_aborted(api, upstreams):
    upstreams.delay_s = 1.0
    sid = (await post(api)).json()["summary_id"]
    await asyncio.sleep(0.1)
    await api.app.state.runner.shutdown()
    d = (await api.get(f"/ai/summaries/{sid}")).json()
    assert d["status"] == "failed" and d["error_code"] == "JOB_ABORTED"


class SlowProvider:
    name, model = "mock", "slow-1"
    capabilities = Capabilities(False, True, False, False, 1000)

    async def generate(self, req):
        await asyncio.sleep(30)
        return LLMResponse("{}", [], "stop", 1, 1, 1)


async def test_deadline_exceeded_after_facts_degrades_with_llm_timeout(make_client):
    c = await make_client(provider=SlowProvider(), llm_job_deadline_s=3, llm_provider="mock")
    started = asyncio.get_running_loop().time()
    d = await run(c)
    assert d["status"] == "degraded" and d["error_code"] == "LLM_TIMEOUT" and d["facts"]
    assert asyncio.get_running_loop().time() - started < 8


async def test_deadline_exceeded_before_facts_fails_with_upstream_timeout(make_client, upstreams):
    upstreams.delay_s = 5
    c = await make_client(llm_job_deadline_s=1)
    d = await run(c)
    assert d["status"] == "failed" and d["error_code"] == "UPSTREAM_TIMEOUT"


async def test_progress_is_persisted_step_by_step(api, upstreams):
    upstreams.delay_s = 0.3
    sid = (await post(api)).json()["summary_id"]
    seen = set()
    for _ in range(40):
        d = (await api.get(f"/ai/summaries/{sid}")).json()
        seen.add(tuple(s["state"] for s in d["progress"])[:3])
        if d["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert ("done", "running", "pending") in seen            # gather in progress, visible to the poller
    assert ("done", "done", "done") in seen


async def test_heartbeat_advances_while_a_job_runs(api, upstreams, db_engine):
    upstreams.delay_s = 0.5
    sid = (await post(api)).json()["summary_id"]
    async with db_engine.connect() as c:
        t0 = (await c.execute(text("SELECT heartbeat_at FROM ai_summaries"))).scalar()
    await wait_done(api, sid)
    async with db_engine.connect() as c:
        t1 = (await c.execute(text("SELECT heartbeat_at FROM ai_summaries"))).scalar()
    assert t1 > t0 and t1 - t0 < timedelta(minutes=1)
