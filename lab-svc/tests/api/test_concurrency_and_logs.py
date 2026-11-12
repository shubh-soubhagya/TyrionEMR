"""Concurrent writers for one patient, and no lab values in logs or metrics labels."""
from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import text

from app.core.logging import JsonFormatter

pytestmark = pytest.mark.api


async def test_concurrent_reports_for_one_patient_keep_the_read_model_consistent(api, patients, db_engine) -> None:
    pid = patients.add()

    async def post(day: int, k: float):
        return await api.post(f"/labs/patients/{pid}/reports", json={
            "collected_at": f"2026-10-{day:02d}T09:00:00Z", "results": [{"test_code": "K", "value": k, "unit": "mmol/L"}]})

    resps = await asyncio.gather(*(post(d, 4.0 + d / 10) for d in range(1, 9)))
    assert all(r.status_code == 201 for r in resps)
    async with db_engine.connect() as c:
        st = (await c.execute(text("SELECT latest FROM patient_lab_status WHERE patient_id = :p"), {"p": pid})).scalar_one()
        n = (await c.execute(text("SELECT count(*) FROM lab_results WHERE patient_id = :p"), {"p": pid})).scalar_one()
    assert n == 8 and st["K"]["value"] == 4.8                  # the latest by collection date, whichever committed last


async def test_two_simultaneous_corrections_one_wins(api, patients) -> None:
    pid = patients.add()
    rid = (await api.post(f"/labs/patients/{pid}/reports", json={
        "collected_at": "2026-10-01T09:00:00Z", "results": [{"test_code": "K", "value": 6.5, "unit": "mmol/L"}]})
    ).json()["results"][0]["id"]
    body = {"value": 4.0, "unit": "mmol/L", "reason": "re-checked against report"}
    a, b = await asyncio.gather(api.post(f"/labs/results/{rid}/correct", json=body),
                                api.post(f"/labs/results/{rid}/correct", json=body))
    assert sorted([a.status_code, b.status_code]) == [201, 409]


def test_log_formatter_redacts_lab_values() -> None:
    rec = logging.LogRecord("t", logging.INFO, "", 0, "evt", (), None)
    rec.value = 6.8
    rec.payload = {"notes": "secret note", "lab_name": "Private Lab", "value_original": 176.8}
    out = JsonFormatter("lab-svc").format(rec)
    for leaked in ("6.8", "secret note", "Private Lab", "176.8"):
        assert leaked not in out
