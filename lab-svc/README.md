# lab-svc

Laboratory data and everything derived from it: reference ranges, unit conversion, flags, CKD categories, trends
and the `patient_lab_status` read model.

- Design: [docs/lab-svc-HLD-LLD.md](docs/lab-svc-HLD-LLD.md) (the source of truth), system context in [../docs/HLD.md](../docs/HLD.md).
- Build plan and status: [PHASES.md](PHASES.md) (all twelve phases done).
- API export: [docs/api/lab-svc.json](docs/api/lab-svc.json). Query plans: [docs/db/explain/](docs/db/explain/).

## Run (same Postgres container as auth-svc and patient-svc)

```bash
cp .env.example .env            # set LAB_DB_PW and the two URLs (host port 5433)
make init-db init-test-db       # idempotent: role lab_svc, nephro_lab_db, nephro_lab_db_test
make install migrate seed       # venv, alembic upgrade head, catalog + ranges, the ten demo patients' labs
make run                        # http://localhost:8003  (/docs in development)
make test                       # needs LAB_TEST_DATABASE_URL; REQUIRE_DB_TESTS=1 fails instead of skipping
make lint                       # ruff + mypy
make check-status               # recompute the read model in memory and compare (CI runs this after seeding)
make seed-reset                 # development only: empty lab data and reseed (sets SEED_ALLOW_RESET)
make openapi explain            # explain needs LAB_DATABASE_URL pointing at a *_test database
```

In Docker (attached to `nephro-net`, where Postgres has the alias `postgres`): `docker compose up --build -d`.
The service publishes no port; only the gateway does (`LAB_SVC_URL=http://lab-svc:8000`; the gateway already routes
`/api/labs/**` and never exposes `/internal/**`).

`lab_svc` can connect to `nephro_lab_db` (and `_test`) only; it is refused on the other services' databases.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/labs/tests?sex=M\|F\|O&age=` | Catalog: units with exact string factors, plausibility limit, display order, the range in force today. With `sex` one `range` (null when none applies, never a guess); without it all `ranges`. `ETag` + `Cache-Control: private, max-age=300`, `304` on match |
| POST | `/labs/patients/{id}/reports` | 1-8 analytes. Returns `{report, results, summary}` and `Location …?report_id=`. Calls patient-svc once (404 `PATIENT_NOT_FOUND`, 502/504 if it is down, nothing written) |
| POST | `/labs/results/{id}/correct` | `{value, unit, reason}`; supersedes the result, judged against its own range snapshot, no patient-svc call. Returns `{corrected, current, status_version}`. 409 `RESULT_ALREADY_SUPERSEDED` carries `current_id` |
| GET | `/labs/patients/{id}/results` | `test`, `from` (inclusive), `to` (exclusive), `flag=abnormal\|critical\|unknown\|normal`, `report_id`, `include_superseded`, `page`, `size` (1-100, default 10) |
| GET | `/labs/patients/{id}/trends?tests=CREAT,EGFR` | Points + stats for the selected window, `reference` from the latest point's snapshot, `stage_bands` on eGFR |
| GET | `/labs/patients/{id}/latest` | One tile per test in display order (null when none), `ckd` block, attention flags, `first_result_at`, `egfr_lt60_run {since, n}` (trailing run of eGFR < 60 ending at the latest eGFR, null otherwise), `status_version`; `ETag: W/"status-<n>"` and `304` |
| GET | `/labs/summary?patient_ids=a,b` | 1-50 ids, one indexed read, one entry per id in request order (`has_results: false` when none), `TOO_MANY_IDS` beyond 50 |
| GET | `/internal/labs/patients/{id}/{results,trends,latest}` | For ai-svc. `results` takes `limit` (<= 50) and adds `truncated`; the others are identical to the public ones |
| GET | `/internal/labs/status?cursor=&limit=` | Bulk read model (same two extra fields as `/latest`), keyset by `patient_id`, limit <= 200, `INVALID_CURSOR` (400) on a bad cursor |
| GET | `/health`, `/ready`, `/metrics` | `/ready` checks the database, the migration head, the catalog and the JWKS |

lab-svc never asks patient-svc whether a patient exists on a read, so results for an unknown patient are an empty
list. Errors use the platform envelope `{error: {code, message, details, request_id}}`; validation details are
`{field, issue}` plus a `code` for rule failures, with paths such as `results[1].unit`; the submitted value is never echoed.

## Clinical rules (all in `app/domain`, pure, table-tested)

- `units.py`: unit matching by normalised key (`µmol/L`, `μmol/L`, `umol/L`, `mL/min/1.73m2` all resolve), exact
  `Decimal` conversion rounded half-up to `decimals + 1` places. The stored `unit_original` is the catalog spelling.
- `flagging.py`: range selection (sex, then age band, then newest `effective_from` on the **collection date**);
  critical limits first, then low/high; no range means `unknown`, never `normal`. The shared vectors in
  `tests/vectors/lab_cases.json` are meant to be run by the Angular preview as well.
- `ckd.py`: eGFR G1-G5 and UACR A1-A3 on the canonical stored value, lower-inclusive boundaries.
- `trends.py`: least-squares slope per year, at least 3 points, per-test direction rules, rapid decline at or below
  -5 per year. All thresholds come from settings.
- `status.py`: builds the read model from the current results; the write path and `rebuild_status` use the same
  function. `constants.RULES_VERSION` marks which rules built a row.
- `catalog_data.py`: the one source of tests, units and ranges.

## Data guarantees

`lab_reports` and `lab_results` are append-only (database triggers). A result can be corrected once; the correction
is a new row (`supersedes_id`, mandatory `reason`); "current" means "not superseded" and every read goes through the
`lab_results_current` view. Each result keeps the range that judged it (`range_id`, limits, flag), so a later range
revision never rewrites history. `patient_lab_status` is recomputed in the same transaction as every write, under a
per-patient advisory lock, and `python -m app.cli.rebuild_status [--patient-id] [--stale-only] [--check]` rebuilds or
verifies it. Every write and patient read adds an `audit_events` row (counts and field names, never values).

## Demo data

`python -m app.cli.seed_labs` loads the ten profiles of LLD B11.2 through the real write path (idempotent; dates count
back from today or `SEED_ANCHOR_DATE`; fixed random seed). Patient ids are the UUIDv5 ids patient-svc uses.
`tests/api/test_seed.py` asserts the outcomes the later insights rely on. PT-000110 (Kavita Joshi) runs eGFR 59 -> 49
over 500 days (about -7 per year, a rapid decline) as ai-svc LLD B20.1 #3 asks.

Upgrading an existing development database to `lab-rules-2` (migration `0004`, ai-svc LLD B20.1):

```bash
make migrate                                  # adds first_result_at and egfr_lt60_run (nullable)
python -m app.cli.rebuild_status --stale-only # rows still on lab-rules-1 are recomputed; then `make check-status`
make seed-reset                               # development only: reseeds PT-000110 with the new 59 -> 49 profile
```

## Decisions to review

- Reference ranges and critical limits are the reference UI prototype's, not a separate "supplied ranges file"
  (none is in the repo). Only `catalog_data.py` changes if one exists; re-seeding with a later `effective_from`
  keeps history.
- Sex `O`: tests with only sex-specific ranges (creatinine, hemoglobin) get `unknown` and no reference range.
- `flag=abnormal` excludes `unknown`; `flag=unknown` lists them.
- Creatinine factor is 0.0113 (prototype); the exact value is 1/88.4 = 0.011312. It is data in `lab_tests`.
- eGFR critical low is 10 (prototype): an eGFR below 10 puts the patient on the attention list.
- The audit trail is not in the LLD; it is kept for parity with patient-svc.
- Validation details keep the platform's `issue` key (the LLD example shows `message`), so one client can read every
  service.
- `seed_labs` is idempotent by default instead of truncating (the LLD's `app.seed` truncates and needs
  `SEED_ALLOW_RESET`): it runs on every container start, so truncating there would delete real data. `--reset` keeps
  the `SEED_ALLOW_RESET=true` guard.
- Database and role names carry the `nephro_` prefix (`nephro_lab_db`) like the other services; the LLD says `lab_db`.
- Not built here (LLD B17 step 10): the Angular lab form, Labs tab and patient-list wiring, and the browser side of the
  shared vectors. ai-svc does not exist yet, so the `/internal/labs/status` contract is tested from the provider side
  only.
