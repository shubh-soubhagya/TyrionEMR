# lab-svc — Development Phases

Source of truth: [docs/lab-svc-HLD-LLD.md](docs/lab-svc-HLD-LLD.md) (§ numbers below are its sections: A = HLD part, B = LLD part). System context: [../docs/HLD.md](../docs/HLD.md).
Layout mirrors `patient-svc` (`app/api`, `app/core`, `app/domain`, `app/models`, `app/repositories`, `app/services`, `app/schemas`, `migrations`, `tests`, `contracts`). Database objects live in `nephro_lab_db` / `nephro_lab_db_test` on the shared `graphgpt-postgres` container (the LLD calls them `lab_db`; the `nephro_` prefix follows the other services).
Each phase is finished, tested and committed before the next starts. Tests run against the real Postgres test database.

## Where things stand

The first build (commits `38014f4`, `e8bae55`, `7a19ace`) was made from the system HLD **before** the LLD existed. It works and its 182 tests pass, but the LLD fixes many details differently. Phases 1–2 below are done; phases 3–12 are the **alignment** work: each lists what exists and what the LLD still requires.

| # | Phase | LLD | State |
|---|---|---|---|
| 1 | Database provisioning | B14 | ✅ done |
| 2 | Service skeleton, config, auth, error envelope | B2, B8, B14 | ✅ done; config and error codes aligned in phase 6 |
| 3 | Schema alignment migration (`0003`) | B3 | ☐ |
| 4 | Domain alignment (units, trends, status, rules version, shared vectors) | B4, B13.1, B13.3 | ☐ |
| 5 | Catalog service and `GET /labs/tests` | B3.2, B6.9, B7.1 | ☐ |
| 6 | Reports and corrections | B6.1–B6.3, B7.2, B7.7, B8, B9, B10 | ☐ |
| 7 | Read model and rebuild script | B3.6, B6.3, B11.3 | ☐ |
| 8 | Public read APIs | B6.4–B6.7, B7.3–B7.6 | ☐ |
| 9 | Internal endpoints and contracts | B7.8, B7.9, B13.4 | ☐ |
| 10 | Observability and audit | B12 | ☐ |
| 11 | Seed profiles, image, handover | B11, B14 | ☐ |
| 12 | Test-plan closure | B13 | ☐ |

Out of scope here (LLD B17 step 10): the Angular lab form, Labs tab and patient-list wiring, and the browser side of the shared vectors.

---

## Phase 1 — Database provisioning (B14.1–B14.4) ✅
Role `lab_svc`, `nephro_lab_db`, `nephro_lab_db_test`, `CONNECT` revoked from `PUBLIC`, `timezone=UTC`, connection limit, idempotent scripts in `setup/`, backup and restore scripts, `.env.example`. Refusal on other services' databases is tested.

## Phase 2 — Skeleton, config, auth, error envelope (B2, B8) ✅
App factory, request-id middleware, JWT verification against cached JWKS, `Clinician` dependency, `/health`, `/ready`, `/metrics`, JSON logging with redaction, DB error mapping, Dockerfile, compose on `nephro-net`.
**Remaining for the LLD:** settings named as in B2, and error codes named as in B8. Both are done in phase 6 together with the endpoints that use them.

## Phase 3 — Schema alignment migration `0003` (B3)
**Goal:** the database enforces everything B3 lists, without losing the data already stored.

**Differences to close**
- `lab_tests`: `max_value` → `plausible_max numeric(12,4)`, `sort_order` → `display_order` unique, `created_at`, `updated_at`.
- `lab_reference_ranges`: `source text NOT NULL`, `created_at`, `range_has_a_limit`, strict `low < high`, `age_max <= 130`, unique key using `-1` for missing ages.
- `lab_reports`: `lab_name NOT NULL` (1–120), `notes <= 500`, `request_id`, `UNIQUE (id, patient_id, collected_at)`, `collected_at >= 1900` (the future-date rule becomes a service rule; the `created_at` CHECK goes).
- `lab_results`: snapshot columns `range_id` (FK), `crit_low`, `crit_high`; `correction_reason` (3–300) with `correction_needs_reason`; `entered_by`; `not_self_superseding`; `unknown_iff_no_range`; composite FKs `(report_id, patient_id, collected_at)` and `(supersedes_id, report_id, test_code)`; `UNIQUE (id, report_id, test_code)`; `ux_results_report_test_original`; indexes `ix_results_trend`, `ix_results_patient_collected`.
- View `lab_results_current` (B3.5).
- `patient_lab_status`: `result_count`, `version`, `rules_version`, attention partial index.
- Append-only triggers keep their `HINT = LAB_APPEND_ONLY` (used by metrics).

**Data handling:** the migration disables the append-only triggers only inside its own transaction, backfills (`range_id` and critical limits by matching the stored snapshot to the range in force on the collection date, `entered_by` from the report, `lab_name` default, a placeholder reason for legacy corrections), then adds the constraints. Downgrade is for local use.

**Done when:** `alembic upgrade head` is clean on a database holding phase-11 data and on an empty one; models mirror the DDL; DB tests cover every row of the B3.3 constraint table.

## Phase 4 — Domain alignment (B4, B13.1, B13.3)
**Goal:** pure functions exactly as specified, with the shared vectors.

**Differences to close**
- `units.py`: `unit_key` (NFKC, `µ`/`μ`/`u`, whitespace, case), `resolve_unit` returns the catalog spelling, accepts `umol/L` and `mL/min/1.73m2`; ambiguity check at load; `TestDef`/`RangeDef` value objects.
- `trends.py`: years-based OLS (B4.5), `TrendConfig` (`min_points`, stable bands, rapid decline), `first_at`/`last_at`, `no_data` for an empty series, `not_assessed` for other tests, inclusive `≤ −2`, `≥ +2`, `≤ −5`, creatinine strict `> +0.1`.
- `status.py`: `StatusSnapshot` with `result_count`, `rules_version`, latest entries carrying `ref_low`/`ref_high`.
- `constants.py`: `RULES_VERSION = "lab-rules-1"`; stage bands exported for the trends response.
- `tests/vectors/lab_cases.json` (the 13 cases of B13.3) run by pytest; table-driven tests for every row of B13.1.

**Done when:** all B13.1 cases pass; `domain/` still imports no I/O library.

## Phase 5 — Catalog service and `GET /labs/tests` (B3.2, B6.9, B7.1)
- `CatalogService` loads tests and ranges into immutable objects, rebuilds the unit index, reloads after `CATALOG_CACHE_TTL_S`; `/ready` fails until the first load.
- `GET /labs/tests?sex=&age=`: sex `M|F|O`, age 0–130; with `sex` the one range in force today, without it all ranges; `rules_version`; string factors; `ETag` and `Cache-Control: private, max-age=300`; `304` on match.
- Seed values per B3.2 with `source` filled; the seed stays idempotent.

**Done when:** sex `O` gives `range: null` for creatinine and hemoglobin; ETag round trip tested.

## Phase 6 — Reports and corrections (B6.1–B6.3, B7.2, B7.7, B8, B9, B10)
- Settings named as in B2 (`RESULTS_PAGE_MAX`, `STATUS_BULK_MAX`, `SPARK_POINTS`, `CLOCK_SKEW_S`, retries, timeouts, statement timeout 5000 ms).
- Error catalog of B8 with its codes and the PostgreSQL mapping table.
- `POST …/reports`: step order of B6.1; all validation errors collected with `results[i].field` paths; numeric-string values; `lab_name` default; `request_id` stored; snapshot with `range_id` and `crit_*`; response `{report, results, summary}`; `Location …?report_id=`.
- `POST …/correct`: mandatory `reason`; no patient-svc call (target's snapshot); `NO_CHANGE`; response `{corrected, current, status_version}`.
- patient client: bulkhead of 10, read timeout → 504.

**Done when:** every B13.2 "Create report" and "Correction" case passes, including patient down → 502 with no rows written and two concurrent corrections → one 201 and one 409.

## Phase 7 — Read model and rebuild script (B3.6, B6.3, B11.3)
- `patient_lab_status` gets `result_count`, `version` (+1 per recompute), `rules_version`; recompute reads `lab_results_current`.
- `python -m app.cli.rebuild_status [--patient-id] [--stale-only] [--check]`; `--check` writes nothing and exits 1 listing ids that differ (ignoring `version`, `updated_at`).

**Done when:** after the API suite `--check` passes; a changed `RULES_VERSION` is found by `--stale-only`; concurrent reports for one patient keep both results in the status.

## Phase 8 — Public read APIs (B6.4–B6.7, B7.3–B7.6)
- `results`: `flag` groups (`abnormal` excludes `unknown`; `critical`, `unknown`, `normal`), `report_id`, half-open `[from,to)`, `size` 1–100 default 10, items with `test_name`, `lab_name`, `is_correction`, `superseded`.
- `trends`: `reference` from the latest point's snapshot, `stage_bands` for eGFR only, `first_at`/`last_at`, unknown test → 422.
- `latest`: tiles in `display_order` with null tiles, `ckd` block, `status_version`, `ETag`/`304`.
- `summary`: `has_results`, `egfr_direction`, `spark`, `TOO_MANY_IDS`, request order.

**Done when:** every B13.2 results, trends, latest and summary case passes.

## Phase 9 — Internal endpoints and contracts (B7.8, B7.9, B13.4)
- Mirrors accept `limit` (≤ 50) and add `truncated`; `status` returns the B7.9 shape (no spark, with `result_count`), default and max limit 200, malformed cursor → `INVALID_CURSOR` 400.
- JSON Schemas in `contracts/lab/` updated to the new shapes; consumer stub test for patient-svc `…/basic`.

**Done when:** keyset paging returns every row exactly once; contract tests pass.

## Phase 10 — Observability and audit (B12)
- Metrics named as in B12 (`lab_results_created_total{test_code,flag}`, `lab_corrections_total{test_code}`, `lab_status_recompute_seconds`, `lab_patient_client_requests_total{outcome}`, `lab_advisory_lock_wait_seconds`, `lab_catalog_reload_total{result}`); domain event log `lab_report_created`.
- The audit trail from the first build stays (not in the LLD; kept for parity with patient-svc). **Decision to confirm.**
- No lab value, name or note in logs or metric labels (tested).

**Done when:** a scrape shows the names above after a sample request; log redaction test passes.

## Phase 11 — Seed profiles, image, handover (B11, B14)
- Seed regenerated to the B11.2 table (report counts, eGFR first → last, spans, base values, RNG seed 42, `SEED_ANCHOR_DATE`, `SEED_ALLOW_RESET`; creatinine from CKD-EPI 2021; written through the report service).
- Seed test asserts the B11.2 outcome table.
- Container, compose, gateway URL verified; OpenAPI and EXPLAIN artifacts regenerated.

**Done when:** `docker compose up` is healthy and seeded; seed test, OpenAPI export and EXPLAIN plans are committed.

## Phase 12 — Test-plan closure (B13) and README
Walk the B13.2 table row by row against the suite and add what is missing; update the README with the final contract, settings and the decision list (sex `O`, `flag=abnormal` excluding `unknown`, creatinine factor 0.0113, eGFR critical low 10, audit trail).
