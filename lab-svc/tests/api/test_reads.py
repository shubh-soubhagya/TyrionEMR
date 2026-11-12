"""Phase 8: results history, trends, latest and batch summary (LLD B6.4-B6.7, B7.3-B7.6, B13.2)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytestmark = pytest.mark.api
BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
UNITS = {"CREAT": "mg/dL", "EGFR": "mL/min/1.73m²", "K": "mmol/L", "UACR": "mg/g", "HB": "g/dL", "BUN": "mg/dL"}


def stamp(days: int) -> str:
    return (BASE + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def add(api: httpx.AsyncClient, pid, day: int, **vals: float) -> dict:
    resp = await api.post(f"/labs/patients/{pid}/reports", json={
        "collected_at": stamp(day), "lab_name": "Metro Lab",
        "results": [{"test_code": k, "value": v, "unit": UNITS[k]} for k, v in vals.items()]})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def decline(api, patients, sex: str = "M"):
    """Five eGFR/creatinine points over 120 days: a rapid decline."""
    pid = patients.add(sex)
    for i, (e, c) in enumerate([(60, 1.3), (56, 1.5), (52, 1.7), (48, 1.9), (44, 2.1)]):
        await add(api, pid, i * 30, EGFR=e, CREAT=c)
    return pid


async def correct(api, rid, value, unit="mmol/L"):
    return await api.post(f"/labs/results/{rid}/correct", json={"value": value, "unit": unit, "reason": "re-keyed"})


# ---- results (B7.3) -------------------------------------------------------------------------------------
async def test_history_item_shape(api, patients) -> None:
    pid = patients.add("M")
    await api.post(f"/labs/patients/{pid}/reports", json={"collected_at": stamp(0), "lab_name": "Metro Lab", "results": [
        {"test_code": "CREAT", "value": 168, "unit": "µmol/L"}]})
    page = (await api.get(f"/labs/patients/{pid}/results")).json()
    assert (page["page"], page["size"], page["total"]) == (1, 10, 1)
    item = page["items"][0]
    assert item["test_name"] == "Serum creatinine" and item["lab_name"] == "Metro Lab"
    assert (item["value"], item["unit"], item["value_original"], item["unit_original"]) == (1.898, "mg/dL", 168, "µmol/L")
    assert (item["ref_low"], item["ref_high"], item["flag"]) == (0.7, 1.3, "high")
    assert item["is_correction"] is False and item["superseded"] is False


async def test_history_filters_and_ordering(api, patients) -> None:
    pid = patients.add("M")
    await add(api, pid, 0, K=4.0, CREAT=1.0)
    await add(api, pid, 30, K=5.6, CREAT=1.1)
    await add(api, pid, 60, K=4.1, CREAT=1.6, EGFR=8)
    get = lambda **p: api.get(f"/labs/patients/{pid}/results", params=p)    # noqa: E731
    assert (await get(size=100)).json()["total"] == 7
    ab = (await get(flag="abnormal")).json()
    assert ab["total"] == 3 and {x["flag"] for x in ab["items"]} == {"high", "critical_low"}
    assert [x["flag"] for x in (await get(flag="critical")).json()["items"]] == ["critical_low"]
    assert (await get(flag="normal")).json()["total"] == 4
    assert (await get(test="K")).json()["total"] == 3
    page1 = (await get(size=4, page=1)).json()
    assert [len(page1["items"]), (await get(size=4, page=2)).json()["total"]] == [4, 7]
    stamps = [x["collected_at"] for x in page1["items"]]
    assert stamps == sorted(stamps, reverse=True)                              # newest first


async def test_abnormal_excludes_unknown_but_unknown_has_its_own_filter(api, patients) -> None:
    pid = patients.add("O")                                                    # creatinine has no range for sex O
    await add(api, pid, 0, CREAT=9.0, K=6.5)
    ab = (await api.get(f"/labs/patients/{pid}/results", params={"flag": "abnormal"})).json()
    assert [x["test_code"] for x in ab["items"]] == ["K"]
    unk = (await api.get(f"/labs/patients/{pid}/results", params={"flag": "unknown"})).json()
    assert [x["test_code"] for x in unk["items"]] == ["CREAT"]


async def test_date_window_is_half_open(api, patients) -> None:
    pid = patients.add()
    for d in (0, 30, 60):
        await add(api, pid, d, K=4.0)
    get = lambda **p: api.get(f"/labs/patients/{pid}/results", params=p)    # noqa: E731
    both = (await get(**{"from": stamp(0), "to": stamp(30)})).json()
    assert [x["collected_at"][:10] for x in both["items"]] == [stamp(0)[:10]]    # 'to' is exclusive
    nxt = (await get(**{"from": stamp(30), "to": stamp(60)})).json()
    assert [x["collected_at"][:10] for x in nxt["items"]] == [stamp(30)[:10]]    # adjacent windows share nothing


async def test_report_id_filter(api, patients) -> None:
    pid = patients.add()
    first = await add(api, pid, 0, K=4.0, CREAT=1.0)
    await add(api, pid, 10, K=4.2)
    page = (await api.get(f"/labs/patients/{pid}/results", params={"report_id": first["report"]["id"]})).json()
    assert page["total"] == 2 and {x["report_id"] for x in page["items"]} == {first["report"]["id"]}


async def test_superseded_rows_are_hidden_unless_asked_for(api, patients) -> None:
    pid = patients.add()
    res = (await add(api, pid, 0, K=6.8))["results"][0]
    cur = (await correct(api, res["id"], 4.2)).json()["current"]
    default = (await api.get(f"/labs/patients/{pid}/results")).json()
    assert [x["id"] for x in default["items"]] == [cur["id"]] and default["items"][0]["is_correction"] is True
    full = (await api.get(f"/labs/patients/{pid}/results", params={"include_superseded": True})).json()
    by = {x["id"]: x for x in full["items"]}
    assert by[res["id"]]["superseded"] is True and by[cur["id"]]["superseded"] is False
    assert full["items"][0]["id"] == cur["id"]                                  # same collected_at: the correction first


async def test_history_validation_and_paging_bounds(api, patients) -> None:
    pid = patients.add()
    url = f"/labs/patients/{pid}/results"
    assert (await api.get(url, params={"flag": "scary"})).status_code == 422
    assert (await api.get(url, params={"flag": "high"})).status_code == 422       # only the four groups
    r = await api.get(url, params={"test": "NOPE"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_TEST"
    assert (await api.get(url, params={"size": 101})).status_code == 422
    assert (await api.get(url, params={"size": 100})).status_code == 200
    assert (await api.get(url, params={"size": 0})).status_code == 422
    assert (await api.get(url, params={"page": 0})).status_code == 422
    assert (await api.get(url, params={"report_id": "nope"})).status_code == 422


async def test_unknown_patient_gets_an_empty_page_not_a_404(api) -> None:
    page = (await api.get(f"/labs/patients/{uuid.uuid4()}/results")).json()
    assert page["items"] == [] and page["total"] == 0


# ---- trends (B7.4) --------------------------------------------------------------------------------------
async def test_trends_series_points_and_stats(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "CREAT,EGFR"})).json()
    assert [s["test_code"] for s in body["series"]] == ["CREAT", "EGFR"] and body["from"] is None and body["to"] is None
    egfr = body["series"][1]
    assert egfr["unit"] == "mL/min/1.73m²" and [p["value"] for p in egfr["points"]] == [60, 56, 52, 48, 44]
    assert set(egfr["points"][0]) == {"result_id", "collected_at", "value", "flag"}
    assert egfr["stats"]["direction"] == "worsening" and egfr["stats"]["rapid_decline"] is True
    assert egfr["stats"]["first_at"] < egfr["stats"]["last_at"] and egfr["stats"]["n"] == 5
    assert body["series"][0]["stats"]["direction"] == "worsening"              # creatinine rising


async def test_trend_reference_comes_from_the_latest_points_snapshot(api, patients) -> None:
    f, m = patients.add("F"), patients.add("M")
    for pid in (f, m):
        await add(api, pid, 0, CREAT=1.0)
    ref = lambda pid: api.get(f"/labs/patients/{pid}/trends", params={"tests": "CREAT"})   # noqa: E731
    assert (await ref(f)).json()["series"][0]["reference"] == {"low": 0.6, "high": 1.1}
    assert (await ref(m)).json()["series"][0]["reference"] == {"low": 0.7, "high": 1.3}


async def test_stage_bands_only_on_egfr(api, patients) -> None:
    pid = await decline(api, patients)
    s = {x["test_code"]: x for x in (await api.get(f"/labs/patients/{pid}/trends")).json()["series"]}
    assert [b["code"] for b in s["EGFR"]["stage_bands"]] == ["G1", "G2", "G3a", "G3b", "G4", "G5"]
    assert s["EGFR"]["stage_bands"][-1] == {"code": "G5", "lower": 0} and s["CREAT"]["stage_bands"] is None


async def test_trend_stats_describe_the_selected_window(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR", "from": stamp(55)})).json()
    s = body["series"][0]
    assert s["stats"]["n"] == 3 and s["stats"]["first"] == 52 and body["from"] is not None   # recomputed for the window
    narrow = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR", "from": stamp(55),
                                                                    "to": stamp(100)})).json()["series"][0]
    assert [p["value"] for p in narrow["points"]] == [52, 48]


async def test_two_points_are_insufficient_data(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 0, EGFR=60)
    await add(api, pid, 30, EGFR=40)
    s = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR"})).json()["series"][0]
    assert s["stats"]["direction"] == "insufficient_data" and s["stats"]["slope_per_year"] is None


async def test_empty_window_has_no_data_and_no_reference(api) -> None:
    s = (await api.get(f"/labs/patients/{uuid.uuid4()}/trends", params={"tests": "EGFR"})).json()["series"][0]
    assert s["points"] == [] and s["stats"] == {"n": 0, "direction": "no_data"} and s["reference"] is None


async def test_trends_validation(api) -> None:
    pid = uuid.uuid4()
    r = await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR,NOPE"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_TEST"
    assert (await api.get(f"/labs/patients/{pid}/trends", params={"tests": ","})).status_code == 422
    other = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "K"})).json()["series"][0]
    assert other["stage_bands"] is None


async def test_trend_only_uses_current_results(api, patients) -> None:
    pid = patients.add()
    res = [(await add(api, pid, d * 30, EGFR=60 - d))["results"][0] for d in range(3)]
    await api.post(f"/labs/results/{res[2]['id']}/correct", json={"value": 70, "unit": "mL/min/1.73m²", "reason": "typo"})
    pts = (await api.get(f"/labs/patients/{pid}/trends", params={"tests": "EGFR"})).json()["series"][0]["points"]
    assert [p["value"] for p in pts] == [60, 59, 70]


# ---- latest (B7.5) --------------------------------------------------------------------------------------
async def test_latest_tiles_follow_display_order_with_null_tiles(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/latest")).json()
    assert [t["test_code"] for t in body["tests"]] == ["CREAT", "EGFR", "BUN", "K", "HB", "CA", "PHOS", "UACR"]
    tiles = {t["test_code"]: t for t in body["tests"]}
    assert tiles["BUN"]["result"] is None and tiles["BUN"]["canonical_unit"] == "mg/dL"
    assert tiles["EGFR"]["result"]["value"] == 44 and tiles["CREAT"]["result"]["flag"] == "high"
    assert set(tiles["EGFR"]["result"]) == {"result_id", "report_id", "value", "flag", "collected_at", "ref_low", "ref_high"}


async def test_latest_ckd_block(api, patients) -> None:
    pid = await decline(api, patients)
    await add(api, pid, 130, UACR=450)
    ckd = (await api.get(f"/labs/patients/{pid}/latest")).json()["ckd"]
    assert (ckd["egfr_category"], ckd["egfr_label"], ckd["egfr_value"]) == ("G3b", "Moderately to severely decreased", 44)
    assert (ckd["uacr_category"], ckd["uacr_label"], ckd["uacr_value"]) == ("A3", "Severely increased", 450)
    assert ckd["egfr_collected_at"] and ckd["uacr_collected_at"]


async def test_latest_for_a_patient_without_labs_is_all_null_and_200(api) -> None:
    resp = await api.get(f"/labs/patients/{uuid.uuid4()}/latest")
    body = resp.json()
    assert resp.status_code == 200 and all(t["result"] is None for t in body["tests"]) and len(body["tests"]) == 8
    assert body["ckd"]["egfr_category"] is None and body["last_result_at"] is None and body["status_version"] == 0
    assert (body["has_critical"], body["rapid_decline"]) == (False, False)


async def test_latest_flags_and_critical_only_from_the_latest(api, patients) -> None:
    pid = await decline(api, patients)
    body = (await api.get(f"/labs/patients/{pid}/latest")).json()
    assert body["rapid_decline"] is True and body["has_critical"] is False
    k = patients.add()
    await add(api, k, 0, K=6.8)
    assert (await api.get(f"/labs/patients/{k}/latest")).json()["has_critical"] is True
    await add(api, k, 10, K=4.4)
    assert (await api.get(f"/labs/patients/{k}/latest")).json()["has_critical"] is False


async def test_latest_etag_and_304(api, patients) -> None:
    pid = patients.add()
    await add(api, pid, 0, K=4.0)
    first = await api.get(f"/labs/patients/{pid}/latest")
    etag = first.headers["etag"]
    assert etag == 'W/"status-1"' and first.json()["status_version"] == 1
    again = await api.get(f"/labs/patients/{pid}/latest", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    await add(api, pid, 5, K=4.1)                                            # the status moves on
    changed = await api.get(f"/labs/patients/{pid}/latest", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] == 'W/"status-2"'


# ---- summary (B7.6) -------------------------------------------------------------------------------------
async def test_summary_returns_one_entry_per_id_in_request_order(api, patients) -> None:
    sick, none = await decline(api, patients), uuid.uuid4()
    body = (await api.get("/labs/summary", params={"patient_ids": f"{none},{sick},{none}"})).json()
    assert [i["patient_id"] for i in body["items"]] == [str(none), str(sick)]       # de-duplicated, order kept
    empty, full = body["items"]
    assert empty == {"patient_id": str(none), "has_results": False, "latest_egfr": None, "egfr_category": None,
                     "egfr_direction": None, "spark": [], "has_critical": False, "rapid_decline": False,
                     "last_result_at": None}
    assert full["has_results"] and full["egfr_category"] == "G3b" and full["rapid_decline"] is True
    assert full["egfr_direction"] == "worsening" and full["latest_egfr"]["value"] == 44
    assert set(full["latest_egfr"]) == {"value", "flag", "collected_at"} and len(full["spark"]) == 5


async def test_summary_spark_keeps_the_last_twelve_points(api, patients) -> None:
    pid = patients.add()
    for i in range(15):
        await add(api, pid, i * 7, EGFR=70 - i)
    sp = (await api.get("/labs/summary", params={"patient_ids": str(pid)})).json()["items"][0]["spark"]
    assert len(sp) == 12 and sp[-1]["v"] == 56 and sp[0]["v"] == 67


async def test_summary_limits_and_validation(api) -> None:
    ids = ",".join(str(uuid.uuid4()) for _ in range(51))
    r = await api.get("/labs/summary", params={"patient_ids": ids})
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_IDS"
    assert r.json()["error"]["details"] == [{"max": 50}]
    assert (await api.get("/labs/summary", params={"patient_ids": ",".join(str(uuid.uuid4()) for _ in range(50))})
            ).status_code == 200
    assert (await api.get("/labs/summary", params={"patient_ids": "not-a-uuid"})).status_code == 422
    assert (await api.get("/labs/summary", params={"patient_ids": ""})).status_code == 422
    assert (await api.get("/labs/summary")).status_code == 422
