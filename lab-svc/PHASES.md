# lab-svc — Development Phases

Source: [../docs/HLD.md](../docs/HLD.md) (§ numbers below refer to it). **No lab-svc-specific HLD/LLD exists yet** (unlike `patient-svc/docs/patient-svc-HLD-LLD.md`). Phase 1 of this plan is therefore to write `docs/lab-svc-HLD-LLD.md`; later phases should be re-checked against it once it exists.
Paths are relative to `lab-svc/` and mirror `patient-svc` (`app/api`, `app/core`, `app/domain`, `app/models`, `app/repositories`, `app/services`, `app/schemas`, `migrations`, `tests`, `seed`, `contracts`).
Each phase must be finished, tested and committed before the next starts.

| # | Phase | Main result |
|---|---|---|
| 0 | lab-svc LLD | `docs/lab-svc-HLD-LLD.md` agreed (skipped; not yet written) |
| 1 ✅ | Database provisioning | `lab_db` / `lab_db_test`, role `lab_svc` isolated |
| 2 ✅ | Service skeleton, config, auth, error envelope | `/health`, `/ready`, JWT dependency |
| 3 ✅ | Baseline migration and models | 5 tables, CHECKs, indexes, DB guards |
| 4 ✅ | Pure clinical domain | Unit conversion, flagging, CKD categories, trends (no I/O) |
| 5 ✅ | Catalog and reference ranges | `GET /labs/tests`, seeded ranges |
| 6 | Reports, results and corrections | Create report, unit conversion, snapshots, append-only corrections |
| 7 | Read model `patient_lab_status` | Same-transaction updates, rebuild script, batch summary |
| 8 | Read APIs | results, trends, latest, summary |
| 9 | Internal endpoints and contracts | ai-svc reads, bulk status, JSON Schemas |
| 10 | Observability and audit | Logs, metrics, no PHI |
| 11 | Seed, image, compose, handover | Deployable seeded service, OpenAPI, EXPLAIN plans |

---

## Phase 0 — lab-svc LLD
**Goal:** a design doc as detailed as the other services' HLD-LLD files.
**Work:** extract §4.3, §5.4, §6, §9, §11.3, §18 of the HLD into `docs/lab-svc-HLD-LLD.md`; add DDL, error catalog, config table, test plan, and the open items below.
**Open items to settle:** the supplied reference-ranges file and classification criteria (HLD ranges are placeholders); `unknown` flag in the CHECK constraint (HLD §6.2 returns `unknown` but §5.4 lists only five flags); who may correct a result; page size limits.
**Done when:** doc reviewed and committed.

## Phase 1 — Database provisioning (§5.1)
**Work:** idempotent `setup/provision-lab-db.sql` (role `lab_svc`, `lab_db`, `lab_db_test`, timeouts, connection limit, `REVOKE CONNECT FROM PUBLIC`); Makefile targets `db-provision-lab`, `psql-lab`; `.env.example` (`LAB_DB_PW`, `LAB_DATABASE_URL`, `LAB_TEST_DATABASE_URL`); backup/restore scripts.
**Done when:** `lab_svc` connects to `lab_db` and is refused on `patient_db`/`auth_db`; script re-runs cleanly.

## Phase 2 — Skeleton, config, auth, errors (§7, §9, §12)
**Work:** `pyproject.toml` (Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, Pydantic v2, httpx, pytest) with hash-locked requirements; app factory, request-id middleware; `core/config.py`, `core/db.py`, `core/clock.py` (injectable), `core/errors.py` (uniform envelope); JWT verification against cached JWKS, `current_user`, `require_role`; `/health`, `/ready`; `wait_for_db`; test scaffolding with stub JWKS.
**Done when:** `/ready` fails when DB is down; no token 401, wrong audience 401, wrong role 403.

## Phase 3 — Baseline migration and models (§5.4)
**Work:** `0001_baseline` with `lab_tests`, `lab_reference_ranges`, `lab_reports`, `lab_results`, `patient_lab_status`; plausibility CHECKs (value ≥ 0, `collected_at` not in the future); index `(patient_id, test_code, collected_at DESC)`; no cross-DB FKs; trigger blocking UPDATE/DELETE on `lab_results` (append-only, only `supersedes` links new rows); typed models; `tests/db/`.
**Done when:** upgrade/downgrade clean; DB tests prove results cannot be updated or deleted.

## Phase 4 — Pure clinical domain (§6) — `app/domain/`
**Work (no I/O, fully unit-tested):**
- `units.py`: convert to canonical from `allowed_units`; unknown unit → error (422).
- `flagging.py`: range selection (test → sex specific over null → age band → latest `effective_from`), flag order critical_low/low/high/critical_high/normal, no match → `unknown`, never silent normal.
- `ckd.py`: eGFR G1–G5 and UACR A1–A3, lower-inclusive (60 → G2, 59.9 → G3a); test every boundary.
- `trends.py`: OLS slope per year, stats (n, first, last, abs/pct change, span_days), `<3` points → `insufficient_data` and null slope, rapid decline < −5/yr (configurable), per-test direction thresholds.
- Shared test vectors for the browser preview (ADR-019).
**Done when:** all boundary and vector tests pass; layering test shows domain imports no I/O.

## Phase 5 — Catalog and reference ranges (§11.3)
**Work:** seed all 8 tests (CREAT, EGFR, BUN, K, HB, CA, PHOS, UACR) with canonical units, allowed-unit factors, decimals; seed ranges from the supplied file; `GET /labs/tests?sex=` returning range for that sex and critical limits.
**Done when:** catalog tests pass for each sex; CREAT in mg/dL and µmol/L both listed.

## Phase 6 — Reports, results, corrections (§4.3, §9, ADR-009)
**Work:** `POST /labs/patients/{id}/reports` (one or more results); one call to `GET /internal/patients/{id}/basic` for existence, sex, DOB (resilience policy: timeouts, ≤2 GET retries, JWT and request-id forwarding, upstream failure → `502 UPSTREAM_UNAVAILABLE`); convert, store canonical plus `value_original`/`unit_original`, snapshot `ref_low`/`ref_high`/`flag`; whole report in one transaction; `POST /labs/results/{rid}/correct` inserts a row with `supersedes_id`.
**Done when:** API tests cover unit conversion (µmol/L example), snapshot stays after ranges change, unknown unit 422, future date 422, missing patient 404, patient-svc down 502, correction hides the superseded row by default.

## Phase 7 — `patient_lab_status` read model (§5.4, ADR-015)
**Work:** recompute latest per test, G/A categories, `egfr_stats`, `creat_stats`, `egfr_spark` (last 12), `has_critical` (latest per test only), `rapid_decline`, `last_result_at` **in the same transaction** as every report or correction; `scripts/rebuild_status.py` from `lab_results`.
**Done when:** a failed write leaves the model untouched; rebuild output equals incrementally maintained state.

## Phase 8 — Read APIs (§6.3, §11.3)
**Work:** `GET /labs/patients/{id}/results` (filters `test`, `from`, `to`, `flag=abnormal`, paging); `/trends?tests=&from=&to=` (stats recomputed for the window); `/latest` (latest per test plus eGFR and UACR category); `GET /labs/summary?patient_ids=` (max 50, one indexed read, missing patients returned as "no data").
**Done when:** `>50` ids → 422; trend and filter tests pass; EXPLAIN shows index use.

## Phase 9 — Internal endpoints and contracts (§9)
**Work:** `/internal/labs/patients/{id}/…` equivalents; `GET /internal/labs/status?cursor=&limit=` (bulk, cursor paging, default 200); still require a valid token; JSON Schemas under `contracts/lab/`, validated in tests.
**Done when:** bulk paging returns every patient exactly once; contract tests pass.

## Phase 10 — Observability and audit
**Work:** JSON logs with `request_id`, `/metrics`, DB pool and query-duration metrics; audit of result writes and chart reads consistent with the patient-svc approach; no PHI or values in logs.
**Done when:** each write is observable once, failed writes leave no trace.

## Phase 11 — Seed, image, compose, handover (§18)
**Work:** idempotent seed using deterministic UUIDv5 patient ids shared with patient-svc; up to ~60 results per patient over 1–2 years for all 8 tests, creatinine derived from eGFR via CKD-EPI 2021 except intended discordance; scenarios: PT-000101 rapid decline plus µmol/L report, PT-000105 improving, PT-000106 G3b latest vs established G4, PT-000107 no labs for 180+ days and eGFR/creatinine discordance, PT-000108 no labs, PT-000109 critical K and creatinine; seed test asserts each; multi-stage non-root `Dockerfile`, entrypoint (wait → migrate → seed → uvicorn), compose wiring on `nephro-pgnet`; gateway route for `/api/labs`; full test suite; OpenAPI export to `docs/api/lab-svc.json`; EXPLAIN plans in `docs/db/explain/`; README.
**Done when:** `docker compose up lab-svc` is ready and seeded, the list summary and trends return expected scenarios, and artifacts are committed.
