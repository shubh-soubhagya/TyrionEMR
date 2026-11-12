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

## Runtime dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| `patient_db` (shared Postgres container) | everything | `/ready` fails, requests return 503 |
| auth-svc `/.well-known/jwks.json` | verifying access tokens | cached keys keep working; new key ids fail until it is back |
| auth-svc `/auth/me` | the clinician name stored on a new encounter | the name is null and the write still succeeds; the same clinician's later edit or finalize fills it in |

## Open items

| # | Item |
|---|---|
| O1 | Seed namespace: this service uses `9b3f6a52-...` (its design doc); lab-svc's doc lists `6f1c2d3e-...`, and auth-svc seeds users with random ids. All three must share one namespace (`app/domain/seed_ids.py`) before lab-svc is seeded, or lab results will point at patients that do not exist. |
| O2 | List sorted by last visit or primary diagnosis takes about 270 ms at 10,000 patients / 200,000 encounters (target 150 ms). The design's upgrade path is a `last_visit` column maintained at finalize. Everything else meets its target; see `docs/db/explain/README.txt`. |
| O3 | Dockerfile and compose file are copied from auth-svc but not yet built or run. |
| O4 | `requirements-dev.lock` is not generated yet (`make lock` kept timing out on the package index); `requirements.lock` and `requirements-build.lock` are. |

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

