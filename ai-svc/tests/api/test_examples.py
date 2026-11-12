"""Recorded responses for the UI team: the normal, progress, cache-hit, degraded and failed states, plus the insights
payloads (LLD B21 step 14). Regenerate with:  UPDATE_EXAMPLES=1 python -m pytest tests/api/test_examples.py

Synthetic patients only. Without the variable the test just checks the shapes the UI relies on."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.api.test_summary_api import P1, clock, make_client, post, run, wait_done  # noqa: F401
from tests.conftest import Upstreams

pytestmark = pytest.mark.api
OUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "examples"


def save(name: str, body: dict) -> None:
    if os.environ.get("UPDATE_EXAMPLES") == "1":
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                          newline="\n")


async def test_record_every_state(make_client, upstreams: Upstreams):  # noqa: F811
    c = await make_client()
    upstreams.delay_s = 0.2
    sid = (await post(c)).json()["summary_id"]
    running = (await c.get(f"/ai/summaries/{sid}")).json()
    assert running["status"] == "running" and running["ai"] is None
    save("summary-running", running)
    upstreams.delay_s = 0
    completed = await wait_done(c, sid)
    save("summary-completed", completed)
    hit = await run(c)
    assert hit["cached"] is True
    save("summary-cache-hit", hit)
    degraded = await run(c, scenario="invalid_twice", force=True)
    assert degraded["status"] == "degraded" and degraded["facts"]
    save("summary-degraded", degraded)
    failed = await run(c, scenario="upstream_down", force=True)
    assert failed["status"] == "failed" and failed["error_message"]
    save("summary-failed", failed)
    dash = (await c.get("/insights/dashboard")).json()
    save("insights-dashboard", dash)
    save("insights-worklist", (await c.get("/insights/worklist")).json())
    save("insights-gaps", (await c.get(f"/insights/patients/{P1}/gaps")).json())
    assert dash["kpis"]["patients"] == 10
