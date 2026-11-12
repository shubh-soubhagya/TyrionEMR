# patient-svc — Development Phases

Source: [docs/patient-svc-HLD-LLD.md](docs/patient-svc-HLD-LLD.md) (§ numbers below refer to it).
Paths are relative to `patient-svc/` and follow the code layout in §22.
Build order follows the checklist in §28, grouped into 10 phases. Each phase must be finished, tested and committed before the next starts.

| # | Phase | Checklist steps | Main result |
|---|---|---|---|
| 1 | Database environment and provisioning | 1, 2 | `patient_db` / `patient_db_test` ready on the existing Postgres container |
| 2 | Service skeleton, config, auth and error envelope | 3 | `/health`, `/ready`, JWT dependency, error catalog |
| 3 | Baseline migration, models and DB guards | 4 | Full schema, triggers, ORM, DB tests |
| 4 | Patients module | 5 | Register, edit, delete, list, search, sort |
| 5 | Conditions, medications and allergies | 6 | Problem list and sub-resources |
| 6 | Encounters: draft, edit, finalize, delete | 7 | State machine, immutability, problem-list linkage |
| 7 | Encounter dashboard queries | 8 | Drafts and upcoming follow-ups |
| 8 | Internal endpoints and contracts | 9 | lab-svc / ai-svc reads, JSON Schema contracts |
| 9 | Audit trail and observability | 10 | Audit on every route, metrics, logs |
| 10 | Seed data, container image, compose and handover | 11, 12, 13 | Deployable service, seeded demo, OpenAPI and EXPLAIN plans |

---

## Phase 1 — Database environment and provisioning (§8)

**Goal:** the service has its own isolated database on the existing Postgres container.

**Work**
- Run the §8.2 discovery commands; record container name, port and major version (must be ≥ 13).
- Create `infra/postgres/provision-patient-db.sql` (idempotent: role `patient_svc`, `patient_db`, `patient_db_test`, `pg_trgm`, timeouts, `CONNECTION LIMIT 25`). Keep the infra script inside this service folder if the repo has no shared `infra/`: `setup/provision-patient-db.sql`.
- Add `setup/` helpers for `db-network` (external network `nephro-pgnet`, alias `nephro-pg`) and `db-provision-patient`.
- `.env.example` with `PG_CONTAINER`, `PG_HOST`, `PATIENT_DB_PW`, `PATIENT_DATABASE_URL`, `PATIENT_TEST_DATABASE_URL`.
- Backup and restore scripts (§8.8).

**Files:** `setup/provision-patient-db.sql`, `setup/*.sh`, `.env.example`, `Makefile` (targets `db-network`, `db-provision-patient`, `psql-patient`).

**Done when**
- `patient_svc` connects to `patient_db` and is refused on `lab_db` (§8.7).
- Provisioning script can be re-run with no errors.

---

## Phase 2 — Service skeleton, config, auth and error envelope (§17, §18, §20, §21, §22)

**Goal:** a running FastAPI app that authenticates and fails in a uniform way, with no business routes yet.

**Work**
- `pyproject.toml` (Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, Pydantic v2, pytest) and hash-locked requirements if the other services do this.
- `app/main.py` app factory, middleware (request id), exception handlers.
- `app/core/config.py` (Settings, §21), `core/db.py` (engine and session, §8.6), `core/clock.py` (`now()`, `today()` in `CLINIC_TZ`, injectable), `core/errors.py` (domain exceptions, error envelope, DB error mapping).
- `app/api/deps.py` — JWT verification against cached JWKS, `current_user`, `require_role`, pagination params.
- `app/api/routers/health.py` — `/health`, `/ready` (DB check).
- `app/scripts/wait_for_db.py`.
- Test scaffolding: `tests/conftest.py`, stub JWKS and test-key JWT helper.

**Done when**
- `/health` 200, `/ready` 200 with DB up and failing when DB is down.
- No token → 401, wrong audience → 401, wrong role → 403.
- Unit tests for clock and error mapping pass.

---

## Phase 3 — Baseline migration, models and DB guards (§9, §10, §23.1)

**Goal:** the complete schema exists and the database itself protects the medical-record invariants.

**Work**
- `alembic.ini`, `alembic/env.py` (async, advisory lock `patient_db.migrations`).
- `alembic/versions/0001_baseline.py` — DDL of §9.2 verbatim (tables, CHECKs, indexes, MRN sequence, triggers: `set_updated_at`, `encounters_guard`, `encounter_children_guard`, `audit_append_only`, `no_hard_delete`).
- `app/models/` — typed SQLAlchemy models mirroring the DDL (patient, condition, medication, allergy, encounter, vitals, diagnosis, audit event).
- `tests/db/` — §25.3 cases (final encounter immutable, no hard delete, audit append-only, one primary condition).

**Done when**
- `alembic upgrade head` is clean on `patient_db_test`; downgrade works locally.
- All §25.3 database tests pass.

---

## Phase 4 — Patients module (§11.2–11.4, §13.1–13.3, §15, §16.2)

**Goal:** full patient lifecycle plus list, search, filters and sorting.

**Work**
- `app/domain/patient_rules.py` (DOB rules, age, allergy-status transitions), `app/domain/search.py` (`parse_query`, `escape_like`, sort map).
- `app/schemas/patient*.py`, `app/models/patient.py`, `app/repositories/patients.py`, `app/services/patients.py`, `app/api/routers/patients.py`.
- Endpoints: `GET/POST /patients`, `GET/PATCH/DELETE /patients/{id}`.
- MRN from sequence, optimistic locking (`version` → `409 VERSION_CONFLICT`), soft delete, `FOR UPDATE` aggregate lock (P-01).
- List: filters `sex`, `stage` (incl. `none`), `ids`; sorts name/ID/age/diagnosis/visit; `count(*) OVER ()` with lateral joins for primary dx and last final visit.
- Layering test `tests/unit/test_layers.py`.

**Done when**
- Unit tests for patient rules and search pass.
- API tests for patients and optimistic lock (§25.2) pass, including 20 concurrent registrations giving 20 distinct MRNs.

---

## Phase 5 — Conditions, medications and allergies (§11.5–11.7, §13.4–13.7)

**Goal:** the rest of the chart sub-resources, each with its invariants.

**Work**
- `app/domain/problem_list.py` (`infer_category`, link resolution order).
- Conditions: `GET/POST /patients/{id}/conditions`, `PATCH/DELETE .../{cid}`; one active primary (second primary clears first; resolving a primary reports `primary_cleared`; resolved cannot be primary); ICD-10 uppercased.
- Medications: `GET/POST`, `PATCH .../{mid}` with discontinue (end date = today in `CLINIC_TZ`), `status` filter incl. `all`.
- Allergies: `GET/POST`, `DELETE .../{aid}`; `has_allergies` derived; `nka`/`unknown` only with zero allergies; last removal → `unknown`; duplicate allergen → `409 DUPLICATE_ALLERGY`.
- Repositories, services, routers and schemas for each module.

**Done when**
- Conditions, medications and allergies cases in §25.2 pass.
- Concurrent set-primary test leaves exactly one primary.

---

## Phase 6 — Encounters: draft, edit, finalize, delete (§11.8, §13.8–13.9, §14, §16)

**Goal:** the encounter state machine with immutability and problem-list linkage in one transaction.

**Work**
- `app/domain/encounter_rules.py` (common validation, finalizable validation, follow-up vs visit date, future-visit tolerance).
- Vitals schema (ranges, systolic > diastolic, round half-up to 1 decimal, empty vitals → no row).
- Endpoints under `/patients/{id}/encounters/**`: create (draft or final), get, list history, `PATCH` (including `status: final`), delete draft.
- Finalize: write `encounter_diagnoses.condition_id` before flipping to `final`; link / reactivate / insert via `ConditionService.link_or_create`; response includes `problem_list_changes`.
- `clinician_id` and `clinician_name` snapshot from JWT claims (P-05).
- Edit or delete of a final encounter → `409`.

**Done when**
- Unit tests for encounter rules and vitals pass.
- Encounter cases in §25.2 pass, including atomic finalize on forced failure.
- Concurrency test: finalize plus edit gives one `409`.

---

## Phase 7 — Encounter dashboard queries (§12.1, §15)

**Goal:** cross-patient encounter queries the dashboard needs.

**Work**
- `app/api/routers/encounter_queries.py`: `GET /encounters?status=draft` and `GET /encounters?upcoming_followups=true`.
- Follow-ups use `DISTINCT ON` over each patient's latest final encounter; past follow-ups excluded; passing both modes → `422`.
- Pagination and ordering rules from §15; supporting indexes already in the baseline.

**Done when**
- Dashboard cases in §25.2 pass.
- Query timing for follow-ups noted for Phase 10 (first query to watch).

---

## Phase 8 — Internal endpoints and contracts (§12.2–12.5, §25.5, P-12)

**Goal:** data other services consume, with a stable and tested contract.

**Work**
- `app/api/routers/internal.py`, `app/services/internal.py`, `app/repositories/internal.py`.
- `GET /internal/patients/{id}/basic` (404 for missing or soft-deleted), `/chart` (no name, MRN or contact fields), `/conditions`, `/medications-allergies`, `/encounters` (with truncation flag), and bulk `GET /internal/patients/charts` with cursor paging.
- Internal routes still require a valid token.
- JSON Schemas committed under `contracts/patient/`; patient-svc tests validate responses against them.

**Done when**
- Internal and contract cases in §25.2 and §25.5 pass.
- Bulk paging covers every patient exactly once.

---

## Phase 9 — Audit trail and observability (§19, §20)

**Goal:** every chart read and mutation is recorded; the service can be operated.

**Work**
- `app/core/audit.py` (`AuditWriter.record`) and `app/repositories/audit.py`; wire into every route listed in §19.1, in the same transaction as the change (P-07).
- Audit details hold field names, never values; no PHI in logs.
- JSON logs with `request_id`, `/metrics`, DB pool and query-duration metrics (§20).
- Review error catalog (§18) for completeness against implemented routes.

**Done when**
- Each write yields exactly one audit row, a failed write yields none (§25.2 Audit).
- Logs and metrics verified manually for a sample request.

---

## Phase 10 — Seed data, container image, compose and handover (§23.2–23.4, §24, §26, §28 steps 11–13)

**Goal:** a deployable, seeded service with documentation artifacts.

**Work**
- `seed/seed.py` (idempotent, `--reset` only in dev, day offsets resolved at load time, encounters finalized through the real repository calls, `setval` on the MRN sequence) and `seed/patients.json` with the ten scenario patients (§23.4); deterministic UUIDv5 ids shared with other services.
- Seed test asserting every bold scenario fact (§25.6).
- `Dockerfile` (multi-stage, non-root), `docker-entrypoint.sh` (wait → migrate → optional seed → uvicorn), compose service wiring with `nephro-pgnet`, remaining Make targets (`migrate-patient`, `seed-patient`, `test-patient`).
- Run the full suite: unit, API, DB, concurrency, contract.
- Performance: seed 10k patients / 200k encounters in `patient_db_test`, save `EXPLAIN (ANALYZE, BUFFERS)` to `docs/db/explain/`.
- Export OpenAPI to `docs/api/patient-svc.json`; update README with run instructions.

**Done when**
- `docker compose up patient-svc` reaches ready against the existing container, and the seeded dashboard shows drafts and follow-ups.
- Seed test, full test suite, OpenAPI export and EXPLAIN plans are committed.
