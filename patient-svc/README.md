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

Phase 0 (scaffold), 1 (database provisioning) and 2 (skeleton: config, JWT/JWKS auth, error envelope,
`/health`, `/ready`, `/metrics`) are implemented. No business routes yet.

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

Phases 3-6 (schema and triggers, patients, conditions/medications/allergies, encounters) are implemented.
Audit rows (Phase 9) are not written yet. `requirements.lock` / `requirements-dev.lock` are still to be generated with `make lock`.
