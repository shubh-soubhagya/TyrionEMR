# lab-svc

Laboratory data and everything derived from it. lab-svc stores lab reports and results for the eight kidney tests, converts
units exactly, flags values against reference ranges, classifies CKD categories, computes trends, and keeps a per-patient
read model (`patient_lab_status`) that the patient list, the dashboard and the AI service read.

It owns: the test catalog and reference ranges, lab reports and results (with corrections), CKD categories, trend statistics,
abnormal and critical flags, the read model, an audit trail.
It does not own: patients (patient-svc), accounts (auth-svc), AI output (ai-svc). It calls patient-svc once per new report to
check the patient exists.

Synthetic data only.

## Endpoints

Full reference: [docs/API.md](../docs/API.md#lab-svc). Paths are reached through the gateway under `/api`.

| Method | Gateway path | Purpose |
|---|---|---|
| GET | `/api/labs/tests?sex=&age=` | The catalog: units with exact string factors, plausibility limit, display order, and the range in force today. With `sex`, one `range` (null when none applies, never a guess). `ETag` and `304` |
| POST | `/api/labs/patients/{id}/reports` | 1 to 8 results. Returns `{report, results, summary}`. Calls patient-svc once (`404 PATIENT_NOT_FOUND`, `502` or `504` if it is down, nothing written) |
| POST | `/api/labs/results/{id}/correct` | `{value, unit, reason}`. Supersedes the result, judged against its own range snapshot, no patient-svc call. `409 RESULT_ALREADY_SUPERSEDED` carries `current_id` |
| GET | `/api/labs/patients/{id}/results` | History with filters `test`, `from` (inclusive), `to` (exclusive), `flag` (`abnormal`, `critical`, `unknown`, `normal`), `report_id`, `include_superseded`, `page`, `size` (1 to 100) |
| GET | `/api/labs/patients/{id}/trends?tests=` | Points and stats per test for the window, the `reference` from the latest point's snapshot, and `stage_bands` on eGFR |
| GET | `/api/labs/patients/{id}/latest` | One tile per test (null when none), the `ckd` block, attention flags, `first_result_at`, `egfr_lt60_run`, `status_version`, `result_count`. `ETag: W/"status-<n>"` and `304` |
| GET | `/api/labs/summary?patient_ids=` | 1 to 50 ids, one indexed read, one entry per id in request order. `TOO_MANY_IDS` beyond 50 |

Not routed by the gateway:

| Path | Caller |
|---|---|
| `GET /internal/labs/patients/{id}/results`, `/trends`, `/latest` | ai-svc. `results` takes `limit` (at most 50) and adds `truncated`; the others match the public routes |
| `GET /internal/labs/status?cursor=&limit=` | ai-svc. Bulk read model, keyset by patient id, limit at most 200, `INVALID_CURSOR` on a bad cursor |
| `GET /health`, `/ready`, `/metrics` | Docker health checks and the gateway. `/ready` checks the database, the migration head, the catalog and the JWKS |

Reads never ask patient-svc whether a patient exists, so results for an unknown patient are an empty list. Validation errors
carry `{field, issue}` and, for rule failures, a `code`, with paths such as `results[1].unit`; the submitted value is never echoed.

### The eight tests

| Code | Test | Canonical unit | Other accepted units | Decimals shown |
|---|---|---|---|---|
| `CREAT` | Serum creatinine | mg/dL | µmol/L | 2 |
| `EGFR` | eGFR | mL/min/1.73m² | none | 0 |
| `BUN` | Blood urea nitrogen | mg/dL | mmol/L (urea) | 1 |
| `K` | Potassium | mmol/L | mEq/L | 1 |
| `HB` | Hemoglobin | g/dL | g/L | 1 |
| `CA` | Calcium | mg/dL | mmol/L | 1 |
| `PHOS` | Phosphorus | mg/dL | mmol/L | 1 |
| `UACR` | Urine albumin-creatinine ratio | mg/g | mg/mmol | 0 |

Factors and ranges: [lab-svc/app/domain/catalog_data.py](app/domain/catalog_data.py); background in
[docs/DATABASE.md](../docs/DATABASE.md#reference-ranges).

### Clinical rules

All in `app/domain`, pure and table-tested.

| File | Rule |
|---|---|
| `units.py` | Unit matching by normalised key (`µmol/L`, `μmol/L` and `umol/L` all resolve); exact `Decimal` conversion rounded half-up to `decimals + 1` places. The stored `unit_original` is the catalog spelling |
| `flagging.py` | Range selection: sex, then age band, then the newest `effective_from` on the collection date. Critical limits first, then low and high. No range gives `unknown`, never `normal` |
| `ckd.py` | eGFR G1 to G5 and UACR A1 to A3 on the canonical stored value, lower-inclusive boundaries |
| `trends.py` | Least-squares slope per year, at least 3 points, per-test direction rules, rapid decline at or below -5 per year. Thresholds come from settings |
| `status.py` | Builds the read model from current results; the write path and `rebuild_status` use the same function. `RULES_VERSION` (now `lab-rules-2`) marks which rules built a row |
| `egfr.py` | CKD-EPI 2021, used only by the seed so creatinine and eGFR agree. It never computes a stored value from user input |

The shared vectors in `tests/vectors/lab_cases.json` are run by this service and by the Angular live preview
(`frontend/src/app/core/clinical/lab-preview.spec.ts`), so the browser and the server agree.

### Corrections and the read model

`lab_reports` and `lab_results` are append-only (database triggers). A result can be corrected once: the correction is a new
row with `supersedes_id` and a mandatory reason. "Current" means "not superseded", and every read goes through the
`lab_results_current` view. Each result keeps the range that judged it, so a later range change never rewrites history.
`patient_lab_status` is recomputed in the same transaction as every write, under a per-patient advisory lock. To verify or
rebuild it: `python -m app.cli.rebuild_status [--patient-id] [--stale-only] [--check]` (`make check-status` runs the check).
Every write and patient read adds an `audit_events` row with counts and field names, never values.

## Data

Database `nephro_lab_db` (tests use `nephro_lab_db_test`). Schema and relationships: [docs/DATABASE.md](../docs/DATABASE.md#lab-svc).

| Table | Holds |
|---|---|
| `lab_tests` | The eight tests: units, factors, decimals, plausibility limit |
| `lab_reference_ranges` | Ranges by test, sex and age band, with `effective_from` |
| `lab_reports`, `lab_results` | Reports and their results; append-only, with range snapshots |
| `patient_lab_status` | The per-patient read model |
| `audit_events` | Append-only audit trail |

Migrations: `0001` baseline, `0002` audit, `0003` schema alignment, `0004` `first_result_at` and `egfr_lt60_run`.

## Dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| `nephro_lab_db` | Everything | `/ready` fails, requests return `503` |
| auth-svc JWKS | Verifying tokens | Cached keys keep working; unknown key ids fail until it returns |
| patient-svc `GET /internal/patients/{id}/basic` | Checking the patient (and reading sex and date of birth for range selection) when a report is created. Connect timeout 1 s, read timeout 3 s | `502 UPSTREAM_UNAVAILABLE` or `504 UPSTREAM_TIMEOUT`; nothing is written. Reads and corrections are unaffected |

## Run

As part of the stack: see the root [README](../README.md#quick-start). Alone, for development (Python 3.12 and the shared
Postgres container on host port 5433):

```bash
cp .env.example .env            # set LAB_DB_PW and the two URLs
make init-db init-test-db       # idempotent: role lab_svc and nephro_lab_db (+ _test)
make install migrate seed       # venv, alembic upgrade head, catalog and ranges, the demo patients' labs
make run                        # http://localhost:8003 (/docs in development)
make check-status               # recompute the read model in memory and compare it
make seed-reset                 # development only: empty lab data and reseed (sets SEED_ALLOW_RESET)
make openapi explain            # explain needs LAB_DATABASE_URL pointing at a *_test database
```

The seed loads the ten demo patients' lab profiles through the real write path. It is idempotent: a patient that already has
reports is skipped. Dates count back from today, or from `SEED_ANCHOR_DATE`.

## Configuration

Service-specific settings. The full list is in [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `LAB_DATABASE_URL` | required | `postgresql+asyncpg://lab_svc:...@postgres:5432/nephro_lab_db` |
| `JWKS_URL` | `http://auth-svc:8000/.well-known/jwks.json` | auth-svc public keys |
| `PATIENT_SVC_URL` | `http://patient-svc:8000` | Patient existence check on report creation |
| `CLINIC_TZ` | `Asia/Kolkata` | Time zone for date-only rules |
| `RUN_MIGRATIONS_ON_START`, `SEED_ON_START` | `true` | Migrate and seed when the container starts (the seed skips existing data) |
| `SEED_ALLOW_RESET` | unset | Required for `seed_labs --reset`; refused in production |

## Tests

```bash
make test       # needs LAB_TEST_DATABASE_URL; REQUIRE_DB_TESTS=1 fails instead of skipping
make lint       # ruff and mypy
```

Last recorded full run: 328 passed. What the tests prove:

| Rule | Test |
|---|---|
| Unit conversion, flags, CKD categories and trends match the shared vectors | `tests/unit/test_domain.py`, `tests/vectors/lab_cases.json` |
| Results and reports cannot be updated or deleted; a correction supersedes exactly once | `tests/api/test_reports.py` |
| The read model equals a rebuild from the results after every write | `tests/api/test_status_rebuild.py` |
| History filters, trends, `latest` (including `result_count` and `ETag`) and the batch summary | `tests/api/test_reads.py` |
| Every route needs a valid token; internal routes mirror the public ones | `tests/api/test_auth_on_routes.py`, `tests/api/test_internal_and_audit.py` |
| The seed produces the outcomes ai-svc relies on | `tests/api/test_seed.py` |
| Concurrent writes to one patient serialise; no values in logs | `tests/api/test_concurrency_and_logs.py` |

## Design and deviations

Design: [docs/lab-svc-HLD-LLD.md](docs/lab-svc-HLD-LLD.md). Build plan (kept as a record): [docs/PHASES.md](docs/PHASES.md).
Query plans: [docs/db/explain/](docs/db/explain/).

| # | Design says | Here | Why |
|---|---|---|---|
| 1 | Database `lab_db` | `nephro_lab_db` and role `lab_svc` | Same naming as the other services |
| 2 | FastAPI default `redirect_slashes=True` | `redirect_slashes=False`: `/labs/tests/` is a 404 | A 307 through the gateway would leak the upstream path (gateway LLD R14) |
| 3 | A supplied reference-ranges file | The prototype's ranges, marked as a placeholder in the `source` column | No ranges file exists in the repository. Only `catalog_data.py` changes if one is supplied; a later `effective_from` keeps history |
| 4 | `app.seed` truncates first | `seed_labs` is idempotent; `--reset` needs `SEED_ALLOW_RESET=true` | The seed runs on every container start, so truncating would delete real data |
| 5 | Validation details with `message` | `issue` | One client can read every service's errors |
| 6 | An audit trail is not in the LLD | `audit_events` is kept | Parity with patient-svc |
| 7 | Creatinine factor from the design | 0.0113 (the prototype's); the exact value is 1 / 88.4 = 0.011312 | The factor is data in `lab_tests` and can be changed there |
| 8 | eGFR critical low | 10 (the prototype's) | An eGFR below 10 puts the patient on the attention list |
| 9 | Sex `O` has a range for every test | Tests with only sex-specific ranges (creatinine, hemoglobin) give `unknown` and no range | A guess would be a silent normal |
| 10 | PT-000110 eGFR profile | 59 to 49 over 500 days, about -7 per year | ai-svc LLD B20.1 item 3 asks for a rapid decline |

Upgrading an existing development database to `lab-rules-2` (migration `0004`): `make migrate`, then
`python -m app.cli.rebuild_status --stale-only`, then `make check-status`. `make seed-reset` reseeds PT-000110 with the new
profile (development only).

## Known limitations

- Reference ranges are placeholders taken from the prototype, not from a clinical source.
- Lab entry is manual; there is no analyzer or HL7 import.
- `flag=abnormal` excludes `unknown`; use `flag=unknown` to list those.
- eGFR is a reported value that clinicians enter. The service does not compute it from creatinine.
- CI for lab-svc is not set up; `make check-status` is meant to run in it after seeding.
