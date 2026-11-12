"""Phase 6: refs, packet, minimizer, hashing, prompts (LLD B5, B6, B17.1)."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.clients.models import Chart, Latest, Trends
from app.context.hashing import HashInputs, canonical, context_hash
from app.context.minimize import REDACTED, TRUNCATED, clean_text, scrub, size, trim_to_budget
from app.context.packet import build_packet
from app.context.refs import RefBuilder, is_valid_ref
from app.insights.rules.adapters import from_chart
from app.insights.rules.gaps import evaluate
from app.orchestrator.facts import build_facts, build_gaps
from app.prompts.loader import ROOT, load_prompts
from app.validation.output_schema import SCHEMA_VERSION, json_schema
from tests.factories import NOW, TODAY, TZ
from tests.fixtures import seed

HI = HashInputs("cp-1", "v1", SCHEMA_VERSION, "ai-rules-1", "groq", "openai/gpt-oss-20b", True)


def case(mrn: str):
    p = next(x for x in seed.all_patients() if x["mrn"] == mrn)
    chart, latest, trends = (Chart.model_validate(p["chart"]), Latest.model_validate(p["latest"]),
                             Trends.model_validate(p["trends"]))
    facts = from_chart(chart, latest, trends, today=TODAY)
    findings = evaluate(facts, today=TODAY, now=NOW, tz=TZ)
    return p, chart, latest, trends, findings


def packet_for(mrn: str):
    p, chart, latest, trends, findings = case(mrn)
    b = RefBuilder(TZ)
    return build_packet(chart, latest, trends, findings, today=TODAY, builder=b), b, p


# ---- refs --------------------------------------------------------------------------------------
@pytest.mark.parametrize("ref", ["pt:pmh", "ckd:latest", "cond:1", "med:12", "alg:3", "enc:999", "lab:EGFR:2026-10-21",
                                 "lab:K:2026-10-21#2", "trend:EGFR", "gap:NO_LABS_FOR_TEST", "gap:ALLERGY_STATUS_UNKNOWN#2"])
def test_valid_refs(ref):
    assert is_valid_ref(ref)


@pytest.mark.parametrize("ref", ["cond:0", "cond:1000", "lab:egfr:2026-10-21", "lab:EGFR:2026-10-21#1", "pt:name",
                                 str(uuid4()), "cond:3f2a9c", "gap:X", "", "cond:1 "])
def test_invalid_refs_including_uuids(ref):
    assert not is_valid_ref(ref)


def test_refs_are_deterministic_across_runs():
    a, _, _ = packet_for("PT-000101")
    b, _, _ = packet_for("PT-000101")
    assert a == b


def test_lab_ref_collision_gets_a_suffix_and_the_same_result_keeps_its_ref():
    b = RefBuilder(TZ)
    r1, r2 = uuid4(), uuid4()
    assert b.lab("K", "Potassium", NOW, r1) == "lab:K:2026-11-12"
    assert b.lab("K", "Potassium", NOW, r2) == "lab:K:2026-11-12#2"
    assert b.lab("K", "Potassium", NOW, r1) == "lab:K:2026-11-12"          # tool results reuse refs


def test_lab_date_uses_the_clinic_time_zone():
    from datetime import UTC, datetime
    assert RefBuilder(TZ).lab("K", "Potassium", datetime(2026, 10, 20, 21, 0, tzinfo=UTC), uuid4()) == "lab:K:2026-10-21"


def test_gap_refs_number_repeated_codes():
    b = RefBuilder(TZ)
    assert [b.gap("ENCOUNTER_NO_VITALS", "x"), b.gap("ENCOUNTER_NO_VITALS", "x")] == [
        "gap:ENCOUNTER_NO_VITALS", "gap:ENCOUNTER_NO_VITALS#2"]


def test_every_ref_in_the_packet_resolves_and_matches_the_grammar():
    packet, b, _ = packet_for("PT-000110")
    refs = set(re.findall(r'"ref": "([^"]+)"', json.dumps(packet)))
    assert refs and all(is_valid_ref(r) and r in b.index for r in refs)


# ---- packet ------------------------------------------------------------------------------------
def test_packet_has_no_identifiers():
    for mrn in ("PT-000101", "PT-000106", "PT-000109"):
        packet, b, p = packet_for(mrn)
        text = json.dumps(packet)
        spec = next(s for s in seed.SPECS if s.mrn == mrn)
        assert spec.first not in text and spec.last not in text and mrn not in text
        assert spec.dob.isoformat() not in text
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", text)          # no UUID anywhere
        assert "date_of_birth" not in text and "mrn" not in text.lower()


def test_packet_shape_for_a_patient_with_labs():
    packet, _, _ = packet_for("PT-000101")
    assert packet["packet_version"] == "cp-1" and packet["as_of"] == "2026-11-12"
    assert packet["patient"]["age"] == 61 and packet["patient"]["sex"] == "M"
    assert packet["patient"]["established_ckd_stage"] == {"ref": "pt:stage", "value": "G3b"}
    egfr = packet["labs"]["trends"]["EGFR"]
    assert egfr["n"] == 8 and egfr["rapid_decline"] is True and egfr["direction"] == "worsening"
    assert egfr["ref"] == "trend:EGFR" and egfr["first_date"] == "2024-12-12"
    assert packet["labs"]["ckd"]["mismatch"] is False
    assert [x["test"] for x in packet["labs"]["latest"]] == ["CREAT", "EGFR", "UACR"]
    assert packet["encounters"]["draft_count"] == 0 and packet["encounters"]["final_count"] == 1


def test_absent_data_is_explicit_not_omitted():
    packet, _, _ = packet_for("PT-000108")
    assert packet["labs"] == {"latest": [], "ckd": None, "trends": {}}
    assert packet["patient"]["allergy_status"]["value"] == "unknown"
    assert packet["encounters"]["recent"] == [] and packet["medications"] == [] or packet["medications"] is not None
    assert {f["code"] for f in packet["rule_findings"]} >= {"NO_LABS_RECORDED", "NO_PRIMARY_DIAGNOSIS"}


def test_draft_encounters_are_counted_never_shown():
    p, chart, latest, trends, findings = case("PT-000101")
    draft = dict(chart.recent_encounters[0].model_dump(mode="json"), id=str(uuid4()), status="draft",
                 assessment="DRAFT TEXT SHOULD NEVER APPEAR")
    chart = Chart.model_validate({**p["chart"], "recent_encounters": [draft, *p["chart"]["recent_encounters"]],
                                  "counts": {"encounters": 2, "final_encounters": 1, "drafts": 1}})
    packet = build_packet(chart, latest, trends, findings, today=TODAY, builder=RefBuilder(TZ))
    assert "DRAFT TEXT" not in json.dumps(packet) and packet["encounters"]["draft_count"] == 1
    assert len(packet["encounters"]["recent"]) == 1


def test_free_text_is_scrubbed_and_unknown_upstream_fields_dropped():
    p, chart, latest, trends, findings = case("PT-000101")
    raw = dict(p["chart"])
    raw["patient"] = {**raw["patient"], "past_medical_history": "Call 98765 43210 or a@b.com, ref PT-000101.",
                      "secret_new_field": "LEAK"}
    raw["recent_encounters"] = [{**raw["recent_encounters"][0], "unexpected": "LEAK2"}]
    packet = build_packet(Chart.model_validate(raw), latest, trends, findings, today=TODAY, builder=RefBuilder(TZ))
    text = json.dumps(packet)
    assert "LEAK" not in text and "98765" not in text and "a@b.com" not in text and "PT-000101" not in text
    assert REDACTED in packet["patient"]["past_medical_history"]["text"]


def test_packet_numbers_are_canonical():
    packet, _, _ = packet_for("PT-000101")
    assert all(not isinstance(x["value"], Decimal) for x in packet["labs"]["latest"])
    egfr = next(x for x in packet["labs"]["latest"] if x["test"] == "EGFR")
    assert egfr["value"] == 38 and isinstance(egfr["value"], int)


# ---- facts and gaps blocks ---------------------------------------------------------------------
def test_facts_block_is_system_computed_and_gaps_carry_evidence_refs():
    p, chart, latest, trends, findings = case("PT-000106")
    b = RefBuilder(TZ)
    build_packet(chart, latest, trends, findings, today=TODAY, builder=b)
    facts, gaps = build_facts(chart, latest, trends, b), build_gaps(findings, chart, b)
    assert facts["provenance"] == "system_computed_from_patient_records" and facts["ckd"]["established"] == "G3a"
    assert facts["ckd"]["egfr_category"] == "G3b" and facts["ckd"]["mismatch"] is True
    assert facts["trends"]["EGFR"]["ref"] == "trend:EGFR"
    f = gaps["findings"][0]
    assert gaps["provenance"] == "rule_engine" and f["code"] == "CKD_STAGE_MISMATCH" and f["ref"] == "gap:CKD_STAGE_MISMATCH"
    assert f["evidence_refs"] and all(r in b.index for r in f["evidence_refs"])


# ---- minimizer ---------------------------------------------------------------------------------
@pytest.mark.parametrize(("raw", "kept"), [
    ("Mail jo@example.org now", "Mail"), ("Phone +91 98765 43210 today", "today"), ("Seen as PT-000123", "Seen"),
    ("BP 138/82, weight 72.9 kg, eGFR 38", "BP 138/82, weight 72.9 kg, eGFR 38"),
    ("Started 2023-02-10, dose 50 mg", "Started 2023-02-10, dose 50 mg"),
])
def test_scrub(raw, kept):
    out = scrub(raw)
    assert kept in out
    if "@" in raw or "PT-" in raw or "98765" in raw:
        assert REDACTED in out and "98765" not in out and "@" not in out and "PT-0" not in out


def test_long_text_is_truncated_with_a_marker():
    out = clean_text("x" * 5000)
    assert out is not None and out.endswith(TRUNCATED) and len(out) <= 1500 + len(TRUNCATED)
    assert clean_text("   ") is None and clean_text(None) is None


def _big(packet):
    packet = json.loads(json.dumps(packet))
    older = dict(packet["encounters"]["recent"][0], ref="enc:2", examination="e" * 3000, assessment="a" * 2000,
                 plan="p" * 2000)
    packet["encounters"]["recent"].append(older)
    for k in ("past_medical_history", "family_history", "social_history"):
        packet["patient"][k] = {"ref": "pt:pmh", "text": "h" * 1500}
    packet["medications"].append({"ref": "med:9", "name": "Old", "dose": "", "route": "oral", "frequency": "",
                                  "status": "discontinued", "start": None, "end": None})
    return packet


def test_budget_trims_in_the_documented_order_and_never_touches_facts():
    packet, _, _ = packet_for("PT-000101")
    big = _big(packet)
    start = size(big)
    out, trimmed = trim_to_budget(big, start - 3500)       # needs steps 1 and 2 only
    assert trimmed == ["older_encounter_examination", "older_encounter_assessment_plan"][:len(trimmed)] and trimmed
    assert size(out) <= start - 3500
    out, trimmed = trim_to_budget(big, 100)                # impossible budget: every step runs, in order
    assert trimmed == ["older_encounter_examination", "older_encounter_assessment_plan", "older_encounter_dropped",
                       "history_truncated", "discontinued_medications_removed"]
    assert out["labs"] == big["labs"] and out["rule_findings"] == big["rule_findings"]
    assert len(out["encounters"]["recent"]) == 1 and all(m["status"] == "active" for m in out["medications"])
    assert len(out["patient"]["past_medical_history"]["text"]) <= 500 + len(TRUNCATED)


def test_nothing_is_trimmed_when_it_fits():
    packet, _, _ = packet_for("PT-000101")
    out, trimmed = trim_to_budget(packet, 24000)
    assert trimmed == [] and out == packet


# ---- hashing -----------------------------------------------------------------------------------
def test_same_chart_same_hash_and_decimal_forms_agree():
    pid = UUID(int=1)
    assert context_hash(pid, {"v": Decimal("38.0")}, HI) == context_hash(pid, {"v": Decimal("38")}, HI)
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})
    a, _, _ = packet_for("PT-000101")
    b, _, _ = packet_for("PT-000101")
    assert context_hash(pid, a, HI) == context_hash(pid, b, HI)


def test_different_patient_with_an_identical_packet_gets_a_different_hash():
    packet = {"patient": {"age": 40, "sex": "F"}}
    assert context_hash(UUID(int=1), packet, HI) != context_hash(UUID(int=2), packet, HI)


@pytest.mark.parametrize("changed", [dict(prompt_version="v2"), dict(model="other"), dict(provider="mock"),
                                     dict(schema_version="out-2"), dict(rules_version="ai-rules-2"),
                                     dict(tools_enabled=False), dict(packet_version="cp-2")])
def test_each_key_input_changes_the_hash(changed):
    pid, packet = UUID(int=1), {"x": 1}
    assert context_hash(pid, packet, HI) != context_hash(pid, packet, HashInputs(**{**HI.__dict__, **changed}))


def test_hash_is_64_hex_chars_and_as_of_is_part_of_it():
    pid = UUID(int=1)
    h1 = context_hash(pid, {"as_of": "2026-11-12"}, HI)
    assert re.fullmatch(r"[0-9a-f]{64}", h1) and h1 != context_hash(pid, {"as_of": "2026-11-13"}, HI)


# ---- prompts -----------------------------------------------------------------------------------
def test_prompts_load_from_markdown_files_and_are_hashed():
    ps = load_prompts("v1")
    assert (ROOT / "v1" / "system.md").is_file() and not list((ROOT / "v1").glob("*.txt"))
    assert "clinical documentation assistant" in ps.system and "Not documented" in ps.system
    assert re.fullmatch(r"[0-9a-f]{64}", ps.sha256)
    out = ps.render_user('{"a": {"b": 1}}')
    assert '{"a": {"b": 1}}' in out and "{packet_json}" not in out and "OUTPUT_SCHEMA" in out
    rep = ps.render_repair(['history_summary.source_refs: "cond:9" does not exist'])
    assert '- history_summary.source_refs: "cond:9" does not exist' in rep and "{reasons}" not in rep


def test_unknown_or_malformed_version_fails_at_startup():
    with pytest.raises(FileNotFoundError):
        load_prompts("v99")
    with pytest.raises(ValueError):
        load_prompts("../etc")


def test_shipped_output_schema_matches_the_model():
    ps = load_prompts("v1")
    assert ps.output_schema == json_schema()
    assert ps.output_schema["additionalProperties"] is False
    assert set(ps.output_schema["properties"]) == {"history_summary", "comorbidity_summary", "trend_commentary",
                                                   "abnormal_commentary", "follow_up_considerations", "not_documented"}
