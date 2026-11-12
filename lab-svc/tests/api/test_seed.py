"""Phase 11: every scenario fact the demo and the later insights rely on (HLD 18)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.seed_labs import seed
from app.domain.egfr import creatinine_for_egfr, egfr_ckd_epi_2021
from app.domain.seed_ids import patient_id
from tests.conftest import make_settings

pytestmark = pytest.mark.api


@pytest.fixture
async def seeded(db_engine, clock) -> dict:
    sm = async_sessionmaker(db_engine, expire_on_commit=False)
    first = await seed(make_settings(), sm, clock)
    return {"first": first, "sm": sm}


async def status(api: httpx.AsyncClient, mrn: str) -> dict:
    return (await api.get(f"/internal/labs/patients/{patient_id(mrn)}/latest")).json()


async def test_seed_is_idempotent(api, seeded, clock) -> None:
    assert sum(seeded["first"].values()) > 30
    assert await seed(make_settings(), seeded["sm"], clock) == {}


async def test_rapid_decline_patient_has_a3_and_a_umol_report(api, seeded, db_engine) -> None:
    s = await status(api, "PT-000101")
    assert s["rapid_decline"] is True and s["egfr_category"]["code"] == "G3b" and s["uacr_category"]["code"] == "A3"
    async with db_engine.connect() as c:
        n = (await c.execute(text("SELECT count(*) FROM lab_results WHERE patient_id = :p AND unit_original = 'µmol/L'"),
                             {"p": patient_id("PT-000101")})).scalar_one()
    assert n == 1


async def test_stable_and_improving_trends(api, seeded) -> None:
    async def direction(mrn: str) -> str:
        r = await api.get(f"/internal/labs/patients/{patient_id(mrn)}/trends", params={"tests": "EGFR"})
        return r.json()["series"][0]["stats"]["direction"]

    assert await direction("PT-000102") == "stable"
    assert await direction("PT-000105") == "improving"
    assert await direction("PT-000104") == "worsening"
    assert (await status(api, "PT-000104"))["rapid_decline"] is False        # steady, not rapid


async def test_stage_mismatch_patient_is_g3b(api, seeded) -> None:
    assert (await status(api, "PT-000106"))["egfr_category"]["code"] == "G3b"       # established G4 in patient-svc


async def test_stale_labs_and_discordance(api, seeded, clock) -> None:
    s = await status(api, "PT-000107")
    age_days = (clock() - __import__("datetime").datetime.fromisoformat(s["last_result_at"])).days
    assert age_days > 180
    assert s["latest"]["EGFR"]["value"] == 85 and s["latest"]["CREAT"]["value"] >= 2.4      # eGFR says mild, creatinine high
    expected = egfr_ckd_epi_2021(s["latest"]["CREAT"]["value"], 59, "M")
    assert expected < 60                                                                    # the two do not agree


async def test_empty_chart_has_no_labs(api, seeded) -> None:
    s = await status(api, "PT-000108")
    assert s["latest"] == {} and s["last_result_at"] is None


async def test_critical_values(api, seeded) -> None:
    s = await status(api, "PT-000109")
    assert s["has_critical"] is True and s["egfr_category"]["code"] == "G5"
    assert s["latest"]["K"]["flag"] == "critical_high" and s["latest"]["CREAT"]["flag"] == "critical_high"


async def test_low_egfr_without_established_stage_is_still_classified(api, seeded) -> None:
    assert (await status(api, "PT-000110"))["egfr_category"]["code"] == "G3a"


async def test_attention_flags_overall(api, seeded) -> None:
    pages = (await api.get("/internal/labs/status", params={"limit": 200})).json()["items"]
    attention = {i["patient_id"] for i in pages if i["has_critical"] or i["rapid_decline"]}
    assert attention == {str(patient_id("PT-000101")), str(patient_id("PT-000109"))}
    assert len(pages) == 9                                                    # PT-000108 has no labs


async def test_seeded_creatinine_agrees_with_egfr(api, seeded) -> None:
    """Derived creatinine round-trips through CKD-EPI 2021 within rounding (rows not overridden)."""
    s = await status(api, "PT-000102")
    egfr, creat = s["latest"]["EGFR"]["value"], s["latest"]["CREAT"]["value"]
    assert abs(egfr_ckd_epi_2021(creat, 54, "F") - egfr) < 1.5


def test_ckd_epi_inverse_round_trip() -> None:
    for sex in ("M", "F"):
        for egfr in (8, 30, 59, 90, 110):
            for age in (25, 60, 80):
                assert egfr_ckd_epi_2021(creatinine_for_egfr(egfr, age, sex), age, sex) == pytest.approx(egfr, rel=1e-9)


def test_ckd_epi_known_value() -> None:
    # 60 y female, creatinine 1.0 mg/dL: hand calculation of the 2021 formula: 142 * (1/0.7)^-1.2 * 0.9938^60 * 1.012 = 64.5
    assert egfr_ckd_epi_2021(1.0, 60, "F") == pytest.approx(64.5, abs=0.1)
