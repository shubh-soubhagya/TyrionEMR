# patient-svc

The clinical chart service of the Nephro EMR. Design: [docs/patient-svc-HLD-LLD.md](docs/patient-svc-HLD-LLD.md). Build plan: [PHASES.md](PHASES.md).
Layout, tooling and container setup mirror `auth-svc`.

## Run it (development)

Uses the same existing Postgres container as auth-svc (`graphgpt-postgres`, attached to the external
network `nephro-net` with the alias `postgres`; see `../auth-svc/README.md`).

```bash
cp .env.example .env            # then set PATIENT_DB_PW and the two URLs (host port 5433)
export PATIENT_DB_PW=...        # same value
make init-db init-test-db       # idempotent: role patient_svc + nephro_patient_db(+_test)
make install                    # local venv
make test                       # unit tests + API tests (API tests need the test database)
make run                        # uvicorn on :8002 (needs JWKS_URL reachable for /ready)
make up                         # Docker, on nephro-net, no published port
```

## Status

All ten phases of [PHASES.md](PHASES.md) are implemented: schema and immutability triggers, patients, conditions,
medications, allergies, encounters (draft, edit, finalize, delete, problem-list linkage), dashboard queries,
internal endpoints with JSON Schema contracts (`contracts/patient/`), audit trail, metrics, seed data,
OpenAPI export (`docs/api/patient-svc.json`) and measured query plans (`docs/db/explain/`).

```bash
make migrate      # alembic upgrade head on the dev database
make seed         # the ten synthetic demo patients (idempotent); make seed-reset wipes first (dev only)
make openapi      # docs/api/patient-svc.json
```

Not verified yet: the Docker image build and `docker compose up` (see "Open items").

## Configuration (service-specific settings)

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

## Runtime dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| `patient_db` (shared Postgres container) | everything | `/ready` fails, requests return 503 |
| auth-svc `/.well-known/jwks.json` | verifying access tokens | cached keys keep working; new key ids fail until it is back |
| auth-svc `/auth/me` | the clinician name stored on a new encounter | the name is null and the write still succeeds; the same clinician's later edit or finalize fills it in |

## Rules the tests prove

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

## Open items

| # | Item |
|---|---|
| O1 | **Resolved.** Seed namespace: this service, lab-svc (`app/domain/seed_ids.py`) and auth-svc's demo users (`app/cli/seed_users.py`, `uuid5(NS, "user:" + email)`) all use `9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10`. A development database seeded before that keeps its old random user ids until the two demo users are deleted and reseeded (see auth-svc README). |
| O2 | List sorted by last visit or primary diagnosis takes about 270 ms at 10,000 patients / 200,000 encounters (target 150 ms). The design's upgrade path is a `last_visit` column maintained at finalize. Everything else meets its target; see `docs/db/explain/README.txt`. |
| O5 | CI for patient-svc (workflow, `requirements-dev.lock`) is deferred by decision. `tests/conftest.py` already fails instead of skipping when `REQUIRE_DB_TESTS=1` is set, ready for it. |
| O3 | **Resolved.** The image is built and runs healthy with the other services (`make up` at the repo root); `GET /api/patients` answers 200 through the gateway (`make smoke`). |

## Deviations from the design document

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

Manual h11 check (no database needed): serve any ASGI app with `uvicorn.Config(app, http="h11",
h11_max_incomplete_event_size=N)`, send `GET /patients?ids=<500 uuids>` in 1,400-byte pieces on a raw socket. With
`N=16384` the connection is aborted; with `N=32768` the answer is `200 OK` (checked on 13 Nov 2026, uvicorn 0.54).

