"""Phase 11: the synthetic profiles of LLD B11.2 and the outcomes the later insights rely on."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.seed_labs import PROFILES, generate, load_patients, seed
from app.domain.egfr import creatinine_for_egfr, egfr_ckd_epi_2021
from app.domain.flagging import age_on
from app.domain.seed_ids import patient_id
from tests.conftest import make_settings

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


# ---- the generator itself (no database) -----------------------------------------------------------------
def by_mrn(mrn: str):
    return next(p for p in PROFILES if p.mrn == mrn)


def egfr_of(report) -> float:
    return float(next(r.value for r in report.results if r.test_code == "EGFR"))


@pytest.mark.parametrize("p", [p for p in PROFILES if p.reports], ids=lambda p: p.mrn)
def test_profile_shape_matches_the_table(p) -> None:
    reports = generate(p, load_patients()[p.mrn], NOW)
    assert len(reports) == p.reports
    assert egfr_of(reports[0]) == p.egfr_first and egfr_of(reports[-1]) == p.egfr_last      # exact at both ends
    days = [(NOW.date() - r.collected_at.date()).days for r in reports]
    assert days == sorted(days, reverse=True)                                                 # oldest first
    assert days[-1] == p.last_days_ago and abs(days[0] - (p.last_days_ago + p.span_days)) <= 1
    assert all(r.collected_at <= NOW for r in reports)                                        # never in the future
    uacr = ["UACR" in {x.test_code for x in r.results} for r in reports]
    assert uacr[-1] and (len(reports) < 2 or not uacr[-2])                                    # every other report


def test_generation_is_deterministic() -> None:
    p, basic = by_mrn("PT-000101"), load_patients()["PT-000101"]
    assert generate(p, basic, NOW) == generate(p, basic, NOW)
    assert generate(p, basic, NOW) != generate(by_mrn("PT-000102"), load_patients()["PT-000102"], NOW)


def test_the_anchor_moves_every_date_together() -> None:
    p, basic = by_mrn("PT-000102"), load_patients()["PT-000102"]
    a, b = generate(p, basic, NOW), generate(p, basic, NOW + timedelta(days=30))
    assert [y.collected_at - x.collected_at for x, y in zip(a, b, strict=True)] == [timedelta(days=30)] * len(a)


def test_creatinine_agrees_with_egfr_except_where_a_discordance_is_intended() -> None:
    for p in (q for q in PROFILES if q.reports):
        basic = load_patients()[p.mrn]
        for i, r in enumerate(generate(p, basic, NOW)):
            vals = {x.test_code: x for x in r.results}
            creat = float(vals["CREAT"].value) * (0.0113 if vals["CREAT"].unit == "µmol/L" else 1)
            age = age_on(basic.date_of_birth, r.collected_at.date())
            back = egfr_ckd_epi_2021(creat, age, basic.sex)
            gap = float(vals["EGFR"].value) - back
            intended = p.discordance_last if i == p.reports - 1 else 0
            assert abs(gap - intended) < max(1.0, 0.03 * back), (p.mrn, i, gap)


def test_special_cases_are_present() -> None:
    umol = [x for r in generate(by_mrn("PT-000101"), load_patients()["PT-000101"], NOW)
            for x in r.results if x.unit == "µmol/L"]
    assert len(umol) == 1                                                                     # report 4 only
    last = generate(by_mrn("PT-000109"), load_patients()["PT-000109"], NOW)[-1]
    assert float(next(x.value for x in last.results if x.test_code == "K")) == 6.2
    assert generate(by_mrn("PT-000108"), load_patients()["PT-000108"], NOW) == []


def test_fixture_matches_patient_svcs_seed_when_both_are_checked_out() -> None:
    other = Path(__file__).resolve().parents[3] / "patient-svc" / "app" / "domain" / "data" / "seed_patients.json"
    if not other.exists():
        pytest.skip("patient-svc seed not present in this checkout")
    theirs = {p["mrn"]: (p["sex"], p["dob"]) for p in json.loads(other.read_text(encoding="utf-8"))["patients"]}
    ours = {m: (b.sex, b.date_of_birth.isoformat()) for m, b in load_patients().items()}
    assert ours == theirs                                                                     # same people, same ids


def test_ids_come_from_the_shared_namespace() -> None:
    ns = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")
    assert patient_id("PT-000101") == uuid.uuid5(ns, "patient:PT-000101")


def test_ckd_epi_inverse_round_trip() -> None:
    for sex in ("M", "F"):
        for egfr in (8, 30, 59, 90, 110):
            for age in (25, 60, 80):
                assert egfr_ckd_epi_2021(creatinine_for_egfr(egfr, age, sex), age, sex) == pytest.approx(egfr, rel=1e-9)


def test_ckd_epi_known_value() -> None:
    # hand calculation of the 2021 formula: 142 * (1/0.7)^-1.2 * 0.9938^60 * 1.012 = 64.5
    assert egfr_ckd_epi_2021(1.0, 60, "F") == pytest.approx(64.5, abs=0.1)


# ---- through the real write path ------------------------------------------------------------------------
@pytest.fixture
async def seeded(db_engine) -> dict:
    sm = async_sessionmaker(db_engine, expire_on_commit=False)
    settings = make_settings(seed_anchor_date=NOW.date())
    return {"first": await seed(settings, sm), "sm": sm, "settings": settings}


async def latest(api: httpx.AsyncClient, mrn: str) -> dict:
    return (await api.get(f"/internal/labs/patients/{patient_id(mrn)}/latest")).json()


def tile(body: dict, code: str) -> dict | None:
    return next(t for t in body["tests"] if t["test_code"] == code)["result"]


async def egfr_stats(api: httpx.AsyncClient, mrn: str) -> dict:
    r = await api.get(f"/internal/labs/patients/{patient_id(mrn)}/trends", params={"tests": "EGFR"})
    return r.json()["series"][0]["stats"]


@pytest.mark.api
async def test_seed_creates_the_expected_reports_and_is_idempotent(api, seeded) -> None:
    assert seeded["first"] == {p.mrn: p.reports for p in PROFILES if p.reports}
    assert await seed(seeded["settings"], seeded["sm"]) == {}


@pytest.mark.api
async def test_101_rapid_decline_a3_and_one_umol_creatinine(api, seeded, db_engine) -> None:
    body = await latest(api, "PT-000101")
    assert body["rapid_decline"] is True and body["ckd"]["egfr_category"] == "G3b"
    assert body["ckd"]["uacr_category"] == "A3"
    async with db_engine.connect() as c:
        n = (await c.execute(text("SELECT count(*) FROM lab_results WHERE patient_id = :p AND "
                                  "unit_original = 'µmol/L'"), {"p": patient_id("PT-000101")})).scalar_one()
    assert n == 1


@pytest.mark.api
async def test_104_rapid_decline_and_g4(api, seeded) -> None:
    body = await latest(api, "PT-000104")
    assert body["rapid_decline"] is True and body["ckd"]["egfr_category"] == "G4"


@pytest.mark.api
async def test_105_improving(api, seeded) -> None:
    assert (await egfr_stats(api, "PT-000105"))["direction"] == "improving"


@pytest.mark.api
async def test_106_latest_is_g3b(api, seeded) -> None:
    assert (await latest(api, "PT-000106"))["ckd"]["egfr_category"] == "G3b"          # patient-svc holds G4


@pytest.mark.api
async def test_107_last_result_is_about_230_days_old_and_egfr_disagrees(api, seeded) -> None:
    body = await latest(api, "PT-000107")
    age = (NOW - datetime.fromisoformat(body["last_result_at"])).days
    assert 229 <= age <= 231
    egfr, creat = tile(body, "EGFR")["value"], tile(body, "CREAT")["value"]
    assert egfr - egfr_ckd_epi_2021(creat, 59, "M") > 10                              # the reported eGFR is too high


@pytest.mark.api
async def test_108_has_no_status_row_and_the_summary_says_so(api, seeded, db_engine) -> None:
    async with db_engine.connect() as c:
        assert (await c.execute(text("SELECT count(*) FROM patient_lab_status WHERE patient_id = :p"),
                                {"p": patient_id("PT-000108")})).scalar_one() == 0
    item = (await api.get("/labs/summary", params={"patient_ids": str(patient_id("PT-000108"))})).json()["items"][0]
    assert item["has_results"] is False and item["latest_egfr"] is None


@pytest.mark.api
async def test_109_critical_values_g5_and_rapid_decline(api, seeded) -> None:
    body = await latest(api, "PT-000109")
    assert body["has_critical"] is True and body["ckd"]["egfr_category"] == "G5" and body["rapid_decline"] is True
    assert tile(body, "K")["flag"] == "critical_high" and tile(body, "CREAT")["flag"] == "critical_high"
    assert tile(body, "K")["value"] == 6.2


@pytest.mark.api
async def test_stable_and_mostly_normal_patients(api, seeded) -> None:
    assert (await egfr_stats(api, "PT-000102"))["direction"] == "stable"
    assert (await latest(api, "PT-000102"))["rapid_decline"] is False
    assert (await latest(api, "PT-000110"))["ckd"]["egfr_category"] == "G3a"


@pytest.mark.api
async def test_lab_level_attention_set(api, seeded) -> None:
    items = (await api.get("/internal/labs/status", params={"limit": 200})).json()["items"]
    assert len(items) == 9
    attention = {i["patient_id"] for i in items if i["has_critical"] or i["rapid_decline"]}
    assert attention == {str(patient_id(m)) for m in ("PT-000101", "PT-000104", "PT-000109")}


@pytest.mark.api
async def test_seeded_state_passes_the_rebuild_check(api, seeded) -> None:
    from app.services import status_rebuild
    assert await status_rebuild.check(seeded["sm"], seeded["settings"]) == []


@pytest.mark.api
async def test_reset_is_refused_unless_explicitly_allowed(api, seeded) -> None:
    with pytest.raises(SystemExit):
        await seed(make_settings(seed_allow_reset=False), seeded["sm"], reset=True)
    with pytest.raises(SystemExit):
        await seed(make_settings(seed_allow_reset=True, environment="production"), seeded["sm"], reset=True)
    again = await seed(make_settings(seed_allow_reset=True, seed_anchor_date=NOW.date()), seeded["sm"], reset=True)
    assert again == seeded["first"]
