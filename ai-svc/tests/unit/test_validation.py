"""Phase 8: parse, citations, schema, grounding, safety, redaction, hydration (LLD B9, B17.1)."""
from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest

from app.context.refs import RefEntry, RefIndex
from app.validation.hydrate import hydrate_sources, refs_in_blocks, refs_in_output
from app.validation.numbers import allowed_numbers, strip_dates, ungrounded
from app.validation.pipeline import NOT_DOCUMENTED, parse_lenient, validate
from app.validation.safety import REMOVED, redact, scan

REFS = ["pt:pmh", "cond:1", "cond:2", "enc:1", "trend:EGFR", "trend:CREAT", "lab:K:2026-10-21", "ckd:latest"]


def index() -> RefIndex:
    i = RefIndex()
    for r in REFS:
        i.add(r, RefEntry(r.split(":")[0], "tid-" + r, f"label {r}", "labs"))
    return i


GOOD = {
    "history_summary": {"text": "Past medical history and the latest encounter are recorded.",
                        "source_refs": ["pt:pmh", "enc:1"]},
    "comorbidity_summary": {"text": "Two conditions are recorded.", "source_refs": ["cond:1", "cond:2"]},
    "trend_commentary": {"text": "eGFR fell by about 16 over the recorded period.", "source_refs": ["trend:EGFR"]},
    "abnormal_commentary": {"text": "Not documented.", "source_refs": []},
    "follow_up_considerations": [{"consideration": "Consider reviewing the rate of eGFR decline at the next visit.",
                                  "rationale": "eGFR has fallen over time.", "source_refs": ["trend:EGFR"]}],
    "not_documented": ["medication adherence"],
}
ALLOWED = allowed_numbers({"abs_change": -16, "n": 8, "last": 38, "x": [1.898]})


def run(obj, attempt=1, text=None):
    return validate(text if text is not None else json.dumps(obj), index(), ALLOWED, attempt=attempt)


def variant(**changes):
    o = copy.deepcopy(GOOD)
    for k, v in changes.items():
        o[k] = v
    return o


# ---- stage 1: parse ----------------------------------------------------------------------------
@pytest.mark.parametrize("text", [json.dumps({"a": 1}), "```json\n" + json.dumps({"a": 1}) + "\n```",
                                  'Sure! Here you go: {"a": 1} hope it helps', 'x {"a": "}{"} y'])
def test_parse_lenient(text):
    assert parse_lenient(text) is not None


@pytest.mark.parametrize("text", [None, "", "no json here", "{broken", "[1, 2]", "{'a': 1}"])
def test_parse_failures(text):
    assert parse_lenient(text) is None


def test_unparseable_reply_asks_for_a_repair_once_then_rejects():
    v1 = run(None, 1, "not json")
    assert v1.kind == "repair" and v1.reason_codes == ["PARSE"]
    assert run(None, 2, "not json").kind == "reject"


# ---- accept ------------------------------------------------------------------------------------
def test_a_good_reply_is_accepted_unchanged():
    v = run(GOOD)
    assert v.kind == "accept" and v.output == GOOD | {"follow_up_considerations": GOOD["follow_up_considerations"]}
    assert (v.refs_total, v.refs_resolved, v.refs_stripped) == (5, 5, 0)
    assert v.safety_flags == 0 and v.grounding_warnings == []


# ---- stage 2: schema ---------------------------------------------------------------------------
def test_missing_section_and_extra_field_are_schema_errors_with_paths():
    bad = copy.deepcopy(GOOD)
    del bad["history_summary"]
    v = run(bad)
    assert v.kind == "repair" and v.reason_codes == ["SCHEMA"] and v.reasons[0].startswith("history_summary")
    extra = GOOD | {"diagnosis": "CKD"}
    v = run(extra)
    assert v.kind == "repair" and any(r.startswith("diagnosis") for r in v.reasons)


def test_follow_up_without_refs_is_rejected_by_the_schema():
    v = run(variant(follow_up_considerations=[{"consideration": "Consider a review.", "rationale": "Because.",
                                               "source_refs": []}]))
    assert v.kind == "repair" and v.reason_codes == ["SCHEMA"]


def test_too_many_refs_or_follow_ups():
    many = [f"cond:{i}" for i in range(1, 14)]
    idx = index()
    for r in many:
        idx.add(r, RefEntry("condition", None, "c", "conditions"))
    v = validate(json.dumps(variant(comorbidity_summary={"text": "x", "source_refs": many})), idx, ALLOWED, attempt=1)
    assert v.kind == "repair" and v.reason_codes == ["SCHEMA"]


# ---- stage 3: citations ------------------------------------------------------------------------
def test_unknown_refs_are_stripped_and_counted_not_trusted():
    o = variant(comorbidity_summary={"text": "Two conditions are recorded.", "source_refs": ["cond:1", "cond:99",
                                                                                              "3f2a9c-uuid"]})
    v = run(o)
    assert v.kind == "accept" and v.output["comorbidity_summary"]["source_refs"] == ["cond:1"]
    assert v.refs_stripped == 2


def test_a_section_left_without_refs_after_stripping_triggers_a_repair():
    o = variant(comorbidity_summary={"text": "Two conditions are recorded.", "source_refs": ["cond:98", "cond:99"]})
    v = run(o)
    assert v.kind == "repair" and v.reason_codes == ["REFS"] and "comorbidity_summary" in v.reasons[0]
    assert run(o, 2).kind == "reject"


# ---- stage 5: missing-information rule ---------------------------------------------------------
def test_section_without_refs_must_say_exactly_not_documented():
    v = run(variant(abnormal_commentary={"text": "There are abnormal results.", "source_refs": []}))
    assert v.kind == "repair" and v.reason_codes == ["NOT_DOCUMENTED"]
    assert run(variant(abnormal_commentary={"text": NOT_DOCUMENTED, "source_refs": []})).kind == "accept"


# ---- stage 4: numeric grounding ----------------------------------------------------------------
def test_rounding_is_accepted_and_invented_numbers_warn():
    assert ungrounded("creatinine 1.9 mg/dL", ALLOWED) == [] and ungrounded("creatinine 1.898", ALLOWED) == []
    # 2.0 would be a miss for 1.898 but 0-10 are always allowed (small counts), so use values outside that range
    assert ungrounded("potassium 39", allowed_numbers({"v": 38.4})) == ["39"]
    assert ungrounded("potassium 38", allowed_numbers({"v": 38.4})) == []
    assert ungrounded("eGFR 41", ALLOWED) == ["41"]


def test_dates_years_refs_and_small_counts_are_ignored():
    text = "On 21 Oct 2026 and 2026-10-21, in 2019, see lab:K:2026-10-21 and cond:3; 2 visits, 10 results, G3b"
    assert ungrounded(text, ALLOWED) == []
    assert "2026" not in strip_dates("21 Oct 2026 and 1999")


def test_numbers_inside_packet_strings_count_as_grounded():
    allowed = allowed_numbers({"examination": "BP 138/82. Mild pallor.", "ref": "lab:K:2026-10-21"})
    assert ungrounded("BP was 138/82", allowed) == [] or ungrounded("blood pressure 138", allowed) == []
    assert Decimal(138) in allowed and Decimal(82) in allowed


def test_grounding_warnings_never_block():
    v = run(variant(trend_commentary={"text": "eGFR was 41 at the last visit.", "source_refs": ["trend:EGFR"]}))
    assert v.kind == "accept" and v.grounding_warnings == [{"field": "trend_commentary", "number": "41"}]


# ---- stage 6: safety ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Increase losartan dose", "Start amlodipine 5 mg daily", "Consider stopping the diuretic",
                                  "Switch to a different medication", "Initiate insulin therapy", "Reduce the dose"])
def test_s1_directive_treatment_hits(text):
    assert [h.rule for h in scan(text, in_follow_up=False) if h.level == "block"] == ["S1"] or \
        "S1" in [h.rule for h in scan(text, in_follow_up=False)]


@pytest.mark.parametrize("text", ["Losartan was started in 2023", "Losartan 50 mg once daily was started in 2023",
                                  "Consider reviewing medication adherence", "The dose was increased last year",
                                  "eGFR and creatinine trends are as calculated"])
def test_s1_history_statements_pass(text):
    assert not [h for h in scan(text, in_follow_up=False) if h.level == "block"]


def test_s2_doses_only_in_follow_ups():
    assert "S2" in [h.rule for h in scan("Consider amlodipine 5 mg", in_follow_up=True)]
    assert not [h for h in scan("On losartan 50 mg once daily", in_follow_up=False) if h.rule == "S2"]
    assert not [h for h in scan("Creatinine 1.8 mg/dL and hemoglobin 9 g/dL", in_follow_up=True) if h.rule == "S2"]


@pytest.mark.parametrize("text", ["This confirms a diagnosis of CKD G4", "He was diagnosed with lupus nephritis",
                                  "This is a new diagnosis", "you have kidney disease"])
def test_s3_diagnostic_assertions_hit(text):
    assert "S3" in [h.rule for h in scan(text, in_follow_up=False)]


def test_s3_recorded_stage_passes():
    assert not scan("CKD stage 3b is recorded as the established stage", in_follow_up=False)


@pytest.mark.parametrize("text", ["Initiate dialysis planning", "Admit to hospital", "Hospitalise the patient"])
def test_s4_dispositions_hit(text):
    assert "S4" in [h.rule for h in scan(text, in_follow_up=False)]


def test_s4_recorded_education_passes():
    assert not scan("Dialysis education class was discussed", in_follow_up=False)


def test_s5_warns_but_never_blocks():
    hits = scan("Anemia due to CKD", in_follow_up=False)
    assert [(h.rule, h.level) for h in hits] == [("S5", "warn")]
    v = run(variant(trend_commentary={"text": "Decline definitely continues.", "source_refs": ["trend:EGFR"]}))
    assert v.kind == "accept" and v.safety_warnings == 1


def unsafe():
    return variant(follow_up_considerations=[
        {"consideration": "Start amlodipine 5 mg daily.", "rationale": "Blood pressure was recorded.",
         "source_refs": ["enc:1"]}])


def test_first_blocking_hit_asks_for_a_repair_naming_the_field_and_rule():
    v = run(unsafe())
    assert v.kind == "repair" and v.reason_codes == ["SAFETY"]
    assert v.reasons[0].startswith("follow_up_considerations[0].consideration: rule S1")
    assert all(len(r) < 160 for r in v.reasons)               # model text is only echoed as a short excerpt


def test_second_blocking_hit_redacts_the_sentence_and_still_completes():
    o = unsafe()
    o["history_summary"]["text"] = "Past history is recorded. Increase losartan dose. Encounter is recorded."
    v = run(o, 2)
    assert v.kind == "accept" and v.safety_flags >= 2
    assert v.output["history_summary"]["text"] == f"Past history is recorded. {REMOVED} Encounter is recorded."
    assert {"field": "history_summary", "rule": "S1"} in v.safety_redactions


def test_a_fully_redacted_follow_up_is_dropped():
    v = run(unsafe(), 2)
    assert v.kind == "accept" and v.output["follow_up_considerations"] == [] and v.safety_flags >= 1


def test_redact_replaces_only_the_offending_sentence():
    text, fired = redact("Fine sentence. Start insulin therapy now. Another fine one.", in_follow_up=False)
    assert text == f"Fine sentence. {REMOVED} Another fine one." and fired == ["S1"]


# ---- hydration ---------------------------------------------------------------------------------
def test_sources_cover_output_and_block_refs_and_leave_nothing_unresolved():
    v = run(GOOD)
    facts = {"ckd": {"ref": "ckd:latest"}, "abnormal_results": [{"ref": "lab:K:2026-10-21"}],
             "trends": {"EGFR": {"ref": "trend:EGFR"}}}
    gaps = {"findings": [{"ref": "gap:X_Y_Z", "evidence_refs": ["cond:1"]}]}
    refs = refs_in_output(v.output) | refs_in_blocks(facts, gaps)
    sources = hydrate_sources(refs, index())
    assert set(sources) == {"pt:pmh", "enc:1", "cond:1", "cond:2", "trend:EGFR", "ckd:latest", "lab:K:2026-10-21"}
    assert sources["cond:1"] == {"type": "cond", "label": "label cond:1", "tab": "labs", "target_id": "tid-cond:1"}
