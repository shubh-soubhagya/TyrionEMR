# NephroCare EMR (TyrionEMR)

A General Nephrology EMR: patient management, outpatient encounters, laboratory results with kidney-function monitoring
(CKD staging, trends, rapid-decline detection) and an AI clinical summary that is always labelled as AI output and never
written into the chart. Four FastAPI services sit behind a custom API gateway; the Angular frontend talks only to the gateway.

All data is **synthetic**. The ten demo patients, their MRNs and the two demo clinicians are invented; no real person's
data is in the repository, the fixtures or the screenshots.

## Architecture

```
Angular (:4200) --> gateway (:8080, the only published port) --> auth-svc | patient-svc | lab-svc | ai-svc
                                                               \--> shared Postgres (one database per service)
```

The gateway verifies the access token, applies rate limits and routes `/api/<prefix>/**`; `/api/internal/**` is never
routed. ai-svc reads patient-svc and lab-svc over the private network. Full diagram and design: [docs/HLD.md](docs/HLD.md) §3.

## Prerequisites

Docker with Compose v2.20+ (`include:` is used), GNU make and bash (Git Bash on Windows), and a running Postgres container
`graphgpt-postgres` (the shared server; host port 5433). Python 3.12 is needed only to run the test suites on the host.
The frontend runs in Docker only ([CLAUDE.md](CLAUDE.md) §9); never run node, npm or ng on the host.

## First-time setup

```bash
cp .env.example .env                  # then edit the change-me passwords; each service also has its own .env.example
for s in auth-svc patient-svc lab-svc ai-svc; do cp $s/.env.example $s/.env; done   # fill in the DB passwords
make network                          # nephro-net, with graphgpt-postgres attached under the alias "postgres"
make init-dbs                         # prints the role/database commands and runs them only if you type "yes"
make keys                             # auth-svc JWT signing key (skipped when it already exists)
make migrate                          # auth-svc schema (the other three migrate when they start)
make up                               # builds and starts the five containers
make seed                             # demo clinicians, ten patients, lab catalog and results (idempotent)
make smoke                            # 19 end-to-end checks through the gateway
cd frontend && docker compose up -d   # dev server on http://localhost:4200
```

Open <http://localhost:4200>. Demo accounts (password `Nephro#2026`): `dr.rao@nephrocare.demo`, `dr.malhotra@nephrocare.demo`.

Other targets: `make ps`, `make logs`, `make down`, `make test` (each service's suite in turn, stops at the first failure).

## AI summary

The default provider is the deterministic **mock**: the stack needs no API key. With `APP_ENV=dev` the AI tab's demo
options send `X-Mock-Scenario` (the gateway forwards it only outside production). To use Groq set `LLM_PROVIDER=groq` and
`LLM_API_KEY` (or `LLM_API_KEY_FILE`) in `ai-svc/.env`, then `docker compose up -d ai-svc`.

## API documentation

| Service | OpenAPI export |
|---|---|
| auth-svc | [auth-svc/docs/api/openapi.json](auth-svc/docs/api/openapi.json) |
| patient-svc | [patient-svc/docs/api/patient-svc.json](patient-svc/docs/api/patient-svc.json) |
| lab-svc | [lab-svc/docs/api/lab-svc.json](lab-svc/docs/api/lab-svc.json) |
| ai-svc | [ai-svc/docs/api/openapi.json](ai-svc/docs/api/openapi.json) and [examples](ai-svc/docs/api/examples/) |

With the stack running, the gateway serves an aggregated Swagger UI (development only) at <http://localhost:8080/docs>.

## Tests

```bash
make test                      # all five, in turn (needs each service's venv and test database)
make -C lab-svc test           # or one service: auth-svc, patient-svc, lab-svc, ai-svc, gateway
make smoke                     # the running stack
docker compose -f frontend/compose.yaml exec web npx ng test --watch=false     # frontend
```

`make capture-fixtures` in `ai-svc/` records real upstream responses for ai-svc's contract tests (needs the stack up and seeded).

## Known limitations

Each service's README has a deviations table: [auth-svc](auth-svc/README.md), [patient-svc](patient-svc/README.md),
[lab-svc](lab-svc/README.md), [ai-svc](ai-svc/README.md), [gateway](gateway/README.md). Notable: the gateway image is not
yet built from hash-locked requirements (gateway README D1); CI workflows exist for auth-svc only; sorting the patient list
by eGFR is not offered by design (ADR-020).
