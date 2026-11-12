# lab-svc

Laboratory data and everything derived from it (reference ranges, unit conversion, flags, CKD categories,
trends). Design: [../docs/HLD.md](../docs/HLD.md) §4.3, §5.4, §6, §9, §11.3. Build plan: [PHASES.md](PHASES.md).

**Status: phases 1–11 done.**

## Run (uses the same Postgres container as auth-svc and patient-svc)

```bash
cp .env.example .env            # set LAB_DB_PW and the two URLs (host port 5433)
make init-db init-test-db       # idempotent; creates role lab_svc, nephro_lab_db, nephro_lab_db_test
make install migrate seed       # venv, alembic upgrade head, catalog + ranges, ten demo patients' labs
make seed-reset                 # development only: empty lab data and reseed
make openapi                    # docs/api/lab-svc.json
make explain                    # with LAB_DATABASE_URL = the *_test database; plans in docs/db/explain/
make run                        # http://localhost:8003  (/docs in development)
make test                       # needs LAB_TEST_DATABASE_URL; set REQUIRE_DB_TESTS=1 to fail instead of skip
make lint
```

In Docker (attached to `nephro-net`, the container has the alias `postgres`): `docker compose up --build -d`.
The service publishes no port; only the gateway does.

Isolation: `lab_svc` can connect to `nephro_lab_db` (and `_test`) only; it is refused on the other services'
databases (asserted by `tests/db/test_db_guards.py`).

## Endpoints so far

| Method | Path | Notes |
|---|---|---|
| GET | `/labs/tests?sex=M\|F` | Catalog: units + factors, plausibility limit, range for that sex. A sex-specific test without `sex` returns `reference_range: null`, never a guessed range |
| POST | `/labs/patients/{id}/reports` | One blood draw, 1-8 analytes. Converts to the canonical unit, snapshots range + flag, updates the read model in the same transaction. Calls patient-svc once (404 unknown patient, 502 if it is down) |
| POST | `/labs/results/{rid}/correct` | Appends a result that supersedes `rid`; 409 `ALREADY_CORRECTED` on a second attempt |
| GET | `/labs/patients/{id}/results` | `test`, `from`, `to`, `flag=abnormal\|low\|...`, `include_superseded`, `page`, `size`; newest first |
| GET | `/labs/patients/{id}/trends?tests=CREAT,EGFR` | Points + stats recomputed for the selected window |
| GET | `/labs/patients/{id}/latest` | Latest per test, eGFR G-category, UACR A-category, attention flags. Empty (not guessed) when nothing is documented |
| GET | `/labs/summary?patient_ids=a,b` | Max 50 ids, one indexed read; every id returned, `has_data: false` when none |
| GET | `/internal/labs/patients/{id}/{results,trends,latest}` | Same handlers for ai-svc |
| GET | `/internal/labs/status?cursor=&limit=` | Bulk read model, cursor = last `patient_id`, limit capped at 200 |
| GET | `/health`, `/ready`, `/metrics` | `/ready` checks DB, migration head and JWKS |

Results of a patient lab-svc has never heard of are simply empty: it calls patient-svc only when writing.

Operations: `python -m app.cli.rebuild_status [--patient <uuid>]` recomputes `patient_lab_status` from `lab_results`
with the same function the write path uses. Every write and every patient read writes an `audit_events` row in the
same transaction (field names and counts only, never values). JSON schemas for the responses are in `contracts/lab/`.

## Clinical rules (all in `app/domain`, pure and unit-tested)

- `units.py`: convert to canonical, half-up to `decimals + 1` places (same rule as the UI prototype).
- `flagging.py`: range selection (sex, then age band, then latest `effective_from`); critical, then low/high;
  no range gives `unknown`, never `normal`.
- `ckd.py`: eGFR G1–G5 and UACR A1–A3, lower-inclusive boundaries.
- `trends.py`: OLS slope per year, needs 3 or more points, direction and rapid-decline thresholds are config.
- `catalog_data.py`: the one source of tests, units and ranges, copied from `reference/emr-ui.html`.

## Decisions to review

- Ranges and critical limits come from the UI prototype, not from a separate "supplied ranges file" (none is
  in the repo). If one exists, only `catalog_data.py` changes; re-seeding with a later `effective_from` keeps
  history.
- `flag = 'unknown'` is allowed in the schema (HLD §5.4 lists five values, §6.2 requires `unknown`).
- `lab_results` and `lab_reports` are append-only through DB triggers (`HINT = LAB_APPEND_ONLY`).
- "collected_at not in the future" is a CHECK against `created_at` (stamped by the app clock) because a CHECK
  cannot use `now()`.

## Demo data (`app/cli/seed_labs.py`)

Ten invented patients, keyed by the same UUIDv5 ids patient-svc uses (namespace in `app/domain/seed_ids.py`, must
equal patient-svc's). Written through the real write path, with day offsets resolved at load time:
PT-000101 rapid decline + A3 + a µmol/L report, 102 stable, 103 G2, 104 steady (not rapid) decline, 105 improving,
106 latest G3b vs established G4, 107 no labs for 180+ days and eGFR/creatinine disagreement, 108 no labs,
109 critical potassium and creatinine, 110 low eGFR without an established stage.
`tests/api/test_seed.py` asserts each fact. Attention set (critical or rapid decline): PT-000101 and PT-000109;
the HLD's six-of-ten worklist also uses gap rules that live in ai-svc.

## Query plans

`docs/db/explain/` holds EXPLAIN (ANALYZE, BUFFERS) for the seven hot queries at 10,000 patients / 200,000
results: all use an index (no sequential scans); the slowest executes in under 1 ms.

## Gateway

The gateway already routes `/api/labs/*` to the `lab` upstream; set `LAB_SVC_URL=http://lab-svc:8000` (done in
`gateway/.env.example`). `/internal/*` is not exposed through it.
