"""Opt-in smoke test against the REAL Groq API (synthetic patient only). Skipped unless RUN_LIVE_LLM=1.

    RUN_LIVE_LLM=1 .venv/Scripts/python -m pytest tests/live -q -s

patient-svc and lab-svc are still the fakes; only the Groq call goes out. Nothing here prints the key or the output.
"""
from __future__ import annotations

import os

import pytest

from tests.api.test_summary_api import P1, clock, make_client, run  # noqa: F401

pytestmark = [pytest.mark.api, pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="live LLM test")]


async def test_real_groq_summary_for_pt_000101(make_client, upstream_router):  # noqa: F811
    upstream_router.route(host="api.groq.com").pass_through()
    c = await make_client(llm_provider="groq", llm_job_deadline_s=90)
    d = await run(c, P1)
    print("\nstatus:", d["status"], "| error:", d["error_code"], "| validation:",
          {k: d["validation"][k] for k in ("refs_total", "refs_stripped", "safety_flags", "repaired", "attempts",
                                          "tool_calls")} if d["validation"] else None)
    assert d["status"] in ("completed", "degraded")
