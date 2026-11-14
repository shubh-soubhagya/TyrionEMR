# patient-svc

The clinical chart service. patient-svc stores patients and everything in their chart that a clinician writes: demographics
and history, the problem list (conditions), medications, allergies and outpatient encounters with vitals and diagnoses. It
runs the encounter lifecycle (draft, then final and immutable) and keeps an audit trail of every write.

It owns: patients, conditions, medications, allergies, encounters, vitals, encounter diagnoses, the audit trail.
It does not own: laboratory results (lab-svc), accounts and tokens (auth-svc), AI output (ai-svc). It calls no service
except auth-svc, for token keys and the clinician's name.

Synthetic data only.

## Endpoints

Full reference: [docs/API.md](../docs/API.md#patient-svc). Paths are reached through the gateway under `/api`.

| Method | Gateway path | Purpose |
|---|---|---|
| GET, POST | `/api/patients` | List with search (`q`), filters (`sex`, `stage`, `ids`), sort (`name`, `mrn`, `age`, `dx`, `visit`) and paging; register a patient |
| GET, PATCH, DELETE | `/api/patients/{id}` | Read, edit with `version`, soft delete |
| GET, POST | `/api/patients/{id}/conditions` | The problem list |
| PATCH, DELETE | `/api/patients/{id}/conditions/{cid}` | Edit, set primary, resolve or reactivate; soft delete |
| GET, POST | `/api/patients/{id}/medications` | Medications |
| PATCH | `/api/patients/{id}/medications/{mid}` | Edit or discontinue |
| GET, POST, DELETE | `/api/patients/{id}/allergies` | Allergies; adding or removing one updates the patient's allergy status |
| GET, POST | `/api/patients/{id}/encounters` | List and create (draft or final) |
| GET, PATCH, DELETE | `/api/patients/{id}/encounters/{eid}` | Read, edit a draft, delete a draft |
| POST | `/api/patients/{id}/encounters/{eid}/finalize` | Freeze the encounter and update the problem list |
| GET | `/api/encounters` | Cross-patient lists for the dashboard: drafts and upcoming follow-ups |

Not routed by the gateway:

| Path | Caller |
|---|---|
| `GET /internal/patients/charts`, `/internal/patients/{id}/basic`, `/chart`, `/conditions`, `/encounters`, `/medications-allergies` | ai-svc (and lab-svc for `basic`), on the private network. No names, MRNs or contact details; contract files in `contracts/patient/` guard each response |
| `GET /health`, `GET /ready` | Docker health checks and the gateway |

### Encounter lifecycle

A new encounter is a `draft`: it can be edited and deleted. Finalising checks that chief complaint, assessment and plan are
present, links each diagnosis marked "add to problem list" to an existing condition or creates one, and sets the status to
`final` in one transaction. After that a database trigger rejects any change (`409 ENCOUNTER_FINAL`). Edits to patients and
drafts carry the `version` the client read; a stale version answers `409 VERSION_CONFLICT`. Every write adds one audit row
holding field names, never values.

## Data

Database `nephro_patient_db` (tests use `nephro_patient_db_test`). Schema and relationships:
[docs/DATABASE.md](../docs/DATABASE.md#patient-svc).

| Table | Holds |
|---|---|
| `patients` | Demographics, history, allergy status, established CKD stage, two derived list-sort columns |
| `encounters` | Visits with a draft or final status |
| `encounter_vitals`, `encounter_diagnoses` | Vitals and diagnoses of one encounter |
| `patient_conditions` | The problem list, with one active primary condition per patient |
| `medications`, `allergies` | Current and past medications; allergens |
| `audit_events` | Append-only audit trail |

Migrations: `0001` baseline, `0002` diagnosis category, `0003` nullable clinician name, `0004` list-sort columns.

## Dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| `patient_db` (shared Postgres container) | everything | `/ready` fails, requests return 503 |
| auth-svc `/.well-known/jwks.json` | verifying access tokens | cached keys keep working; new key ids fail until it is back |
| auth-svc `/auth/me` | the clinician name stored on a new encounter | the name is null and the write still succeeds; the same clinician's later edit or finalize fills it in |

## Run

As part of the stack: see the root [README](../README.md#quick-start). Alone, for development (Python 3.12 and the shared
Postgres container `graphgpt-postgres` on host port 5433):

```bash
cp .env.example .env            # set PATIENT_DB_PW and the two URLs
export PATIENT_DB_PW=...        # the same value
make init-db init-test-db       # idempotent: role patient_svc and nephro_patient_db (+ _test)
make install                    # local venv
make migrate                    # alembic upgrade head
make seed                       # the ten synthetic patients (idempotent); make seed-reset wipes first (dev only)
make run                        # uvicorn on http://localhost:8002 (needs JWKS_URL reachable for /ready)
make up                         # Docker, on nephro-net, no published port
make openapi                    # re-export docs/api/openapi.json
```

## Configuration

Service-specific settings. The full list is in [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `PATIENT_DATABASE_URL` | required | `postgresql+asyncpg://patient_svc:...@postgres:5432/nephro_patient_db` |
| `JWKS_URL` | `http://auth-svc:8000/.well-known/jwks.json` | auth-svc public keys |
| `AUTH_ME_URL` | `http://auth-svc:8000/auth/me` | clinician name lookup, called with the caller's own token |
| `CLINICIAN_NAME_CACHE_TTL_S` | 600 | how long a resolved name is cached |
| `CLINICIAN_NAME_NEGATIVE_TTL_S` | 30 | how long a failed lookup is remembered (protects auth-svc during an outage) |
| `CLINICIAN_NAME_CACHE_MAX` | 1000 | cache size cap; the oldest entry is evicted |
| `CLINIC_TZ` | `Asia/Kolkata` | "today" for date-only rules |
| `MAX_BODY_BYTES` | 1048576 | request bodies above this are rejected with `413 PAYLOAD_TOO_LARGE` |

## Tests

```bash
make test       # unit and API tests; API tests need the test database. REQUIRE_DB_TESTS=1 fails instead of skipping
make lint       # ruff and mypy
```

Last recorded full run: 230 passed. Rules the tests prove:

| Rule | Test |
|---|---|
| A final encounter, its vitals and diagnoses can never change, and nothing is hard-deleted (database triggers) | `tests/db/test_db_guards.py` |
| Every write has exactly one audit row, holding field names and never values; a failed write leaves none | `tests/api/test_audit.py` |
| The clinician name comes from auth-svc `/auth/me`, is null when it is unreachable, and is filled only by its own creator | `tests/api/test_clinician_name.py`, `tests/unit/test_clinician_directory.py` |
| No HTTP call is ever made while a database transaction (and the patient row lock) is open | `FakeDirectory` in `tests/conftest.py`, exercised by `test_clinician_name.py` |
| Migration 0003 turns the old placeholder into NULL, even on final encounters, then restores the guard | `tests/db/test_migration_0003.py` |
| No patient data (names, phone, notes, diagnoses, search text) appears in the service's logs | `tests/api/test_no_phi_in_logs.py`, `tests/unit/test_core.py` |
| A request body above the limit is rejected with 413, whether it declares a length or streams chunked | `tests/api/test_no_phi_in_logs.py` (body-limit tests) |
| The internal chart has no name, MRN or contact field; contract files guard every internal response | `tests/api/test_internal.py`, `contracts/patient/` |
| Every demo scenario fact survives a seed change | `tests/api/test_seed.py` |
| Layering: `domain` is pure and routers never touch repositories | `tests/unit/test_layers.py` |

## Design and deviations

Design: [docs/patient-svc-HLD-LLD.md](docs/patient-svc-HLD-LLD.md). Build plan (kept as a record): [docs/PHASES.md](docs/PHASES.md).
Measured query plans at 10,000 patients and 200,000 encounters: [docs/db/explain/README.txt](docs/db/explain/README.txt).

| # | Design | Here | Why |
|---|---|---|---|
| D1 | Database `patient_db` | `nephro_patient_db` (+ `_test`) | Same naming as `nephro_auth_db`; avoids clashing with other projects on the shared container |
| D2 | Provisioning via `infra/postgres/provision-patient-db.sql` | `setup/init-patient-db.sh` (+ `-test`, backup, restore) | Same scripts as auth-svc; kept inside the service folder |
| D3 | External network `nephro-pgnet`, alias `nephro-pg` | `nephro-net`, alias `postgres` | Reuses the network auth-svc already uses |
| D4 | `alembic/` folder | `migrations/` | auth-svc layout |
| D5 | Config names `DB_POOL_SIZE` etc. | `PATIENT_DB_POOL_SIZE`, ... | auth-svc prefixes service-specific DB settings |
| D6 | Clinician name from a JWT `name` claim (LLD §27.1 #1) | `clinician_name` is resolved from auth-svc `/auth/me` with the caller's token, cached per user, and is nullable when auth-svc is unreachable | auth-svc keeps tokens free of PII (its LLD §17.9) and that will not change; a `name` claim is ignored |
| D7 | `encounter_diagnoses` as in §9.2 | + `category` column (migration 0002) | A draft's explicit diagnosis category must survive until finalize, when the problem-list entry is created |
| D8 | Encounter `clinician_name` NOT NULL | Nullable (migration 0003); `set_updated_at()` honours an explicit `updated_at` | The name is resolved from auth-svc and can be unknown; the injected clock must be able to control timestamps |
| D9 | Uvicorn defaults | `--h11-max-incomplete-event-size 32768` in `scripts/entrypoint.sh` and `make run` | `GET /patients?ids=` with 500 UUIDs is about 18.5 KB; h11's 16 KiB default would reject it when it arrives in several TCP segments. 32 KiB matches the gateway (its LLD R8). The flag only matters when uvicorn uses h11; with `httptools` installed (it is in `requirements.lock`) uvicorn picks that parser, which has no such limit, so the flag is a safeguard. The in-process test client has no HTTP parser: `tests/api/test_patients.py` checks 500 ids return 200 and that the flag is present. Manual check below |
| D10 | FastAPI default `redirect_slashes=True` | `redirect_slashes=False` | `/patients/` costs a 307 round trip through the gateway and leaks the upstream path; it is a 404 now (gateway LLD R14) |
| D11 | LLD §26 upgrade path: lists sort by lateral joins, then a `last_visit` column if too slow | Migration 0004 adds `patients.last_visit` (latest final, not deleted encounter date) and `patients.primary_dx_sort` (`lower(description)` of the active primary condition), with partial indexes. `list_patients` sorts on them and slices the page first, so the two lateral joins (the displayed primary diagnosis and last visit) run for at most one page; the response is unchanged | O2: sorting by visit or diagnosis took about 270 ms at 10,000 patients / 200,000 encounters. Both columns are written in the same transaction as the change, under the patient row lock: `last_visit` by `_finalize_in_tx` (`GREATEST`, final encounters are immutable and only drafts can be deleted), `primary_dx_sort` by `refresh_primary_dx_sort` at the end of every condition add, edit, set primary, resolve and delete (a helper, never a trigger). They are written by statements that touch only these columns and never bump `version`, so a sort cache cannot cause `409 VERSION_CONFLICT` (the `patients_updated_at` trigger still moves `updated_at`). `tests/api/test_sort_columns.py` checks both columns against the lateral joins after a mixed sequence and after the seed; `seed --scale` fills them with SQL |

Manual h11 check (no database needed): serve any ASGI app with `uvicorn.Config(app, http="h11",
h11_max_incomplete_event_size=N)`, send `GET /patients?ids=<500 uuids>` in 1,400-byte pieces on a raw socket. With
`N=16384` the connection is aborted; with `N=32768` the answer is `200 OK` (checked on 13 Nov 2026, uvicorn 0.54).

## Known limitations

| # | Item |
|---|---|
| O1 | **Resolved.** Seed namespace: this service, lab-svc (`app/domain/seed_ids.py`) and auth-svc's demo users (`app/cli/seed_users.py`, `uuid5(NS, "user:" + email)`) all use `9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10`. A development database seeded before that keeps its old random user ids until the two demo users are deleted and reseeded (see auth-svc README). |
| O2 | **Resolved** by D11. Sort by last visit now takes about 46 ms and by primary diagnosis about 29 ms at 10,000 patients / 200,000 encounters (target 150 ms; was about 270 ms). See `docs/db/explain/README.txt`. |
| O3 | **Resolved.** The image is built and runs healthy with the other services (`make up` at the repo root); `GET /api/patients` answers 200 through the gateway (`make smoke`). |
| O5 | CI for patient-svc (workflow, `requirements-dev.lock`) is deferred by decision. `tests/conftest.py` already fails instead of skipping when `REQUIRE_DB_TESTS=1` is set, ready for it. |

- No sorting by latest eGFR in the patient list (ADR-020); the list shows eGFR from lab-svc for the visible page only.
- Patient registration has no duplicate detection beyond the generated MRN.
