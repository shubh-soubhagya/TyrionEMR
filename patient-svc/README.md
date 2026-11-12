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
| D6 | JWT `name` claim | Optional; falls back to "Unknown clinician" | auth-svc does not issue `name` yet (LLD §27.1 #1) |
| D7 | `encounter_diagnoses` as in §9.2 | + `category` column (migration 0002) | A draft's explicit diagnosis category must survive until finalize, when the problem-list entry is created |

