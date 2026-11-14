# Development notes

For someone who wants to read, change or extend the code. The reviewer-facing documents are the root
[README](../README.md), [ARCHITECTURE.md](ARCHITECTURE.md), [API.md](API.md), [DATABASE.md](DATABASE.md) and
[ASSIGNMENT-CHECKLIST.md](ASSIGNMENT-CHECKLIST.md).

Contents:

- [Repository layout](#repository-layout)
- [Conventions](#conventions)
- [How AI coding agents were used](#how-ai-coding-agents-were-used)
- [Add an endpoint end to end](#add-an-endpoint-end-to-end)
- [Documentation tooling](#documentation-tooling)

## Repository layout

```
auth-svc/ patient-svc/ lab-svc/ ai-svc/     one self-contained service each
  app/            api (routes), services (use cases, transactions), repositories (all SQL), models, schemas,
                  domain (pure logic), core (settings, errors, logging, security), cli (seed, export, wait_for_db)
  migrations/     Alembic
  tests/          unit, api (real Postgres test database), db, contract (ai-svc)
  docs/           <service>-HLD-LLD.md (design), PHASES.md (build plan), api/openapi.json
  setup/          one-time database and key scripts
gateway/          the custom gateway: app/routing, app/services (pipeline, proxy, rate limiter, JWKS cache)
frontend/         the Angular app, compose.yaml (dev server, flow and parity tools), e2e/
docs/             reviewer documents, HLD.md (the full design), screenshots/
reference/        assignment.pdf and the HTML prototype
scripts/docs/     check_links.py, gen_api_docs.py, schema_dump.sh
docker-compose.yml   includes each service's compose file under the project name "tyrionemr"
```

Each service is self-contained: its own Dockerfile, dependencies, migrations, tests and documentation, and no shared library.
The few pieces that exist in several services (the error envelope, the JWKS cache, request-id middleware) are copied on
purpose and kept identical by their tests, so a service can be built and deployed on its own.

## Conventions

| Topic | Rule |
|---|---|
| Layering | Routes call services; services own transactions and call repositories; repositories hold all SQL; `domain` is pure (no I/O). Layer tests fail the build if a layer imports one it must not (for example [test_layers.py](../patient-svc/tests/unit/test_layers.py)) |
| Errors | Every error is `{"error": {"code", "message", "details", "request_id"}}` ([API.md](API.md#error-envelope)). Domain errors are `AppError` subclasses with a status and a code; validation details never echo input |
| Database | Alembic migrations in `migrations/versions`, applied by `make migrate` (lab, patient and AI services also migrate on container start). Constraints and triggers carry clinical rules, so the rule holds even if application code is wrong |
| Concurrency | Optimistic `version` columns for patients and encounters; the patient row lock serialises writes to one chart; lab writes take a per-patient advisory lock |
| Time | The injected clock, never `now()` in logic, so tests control time. Timestamps are UTC; "today" is computed in the clinic time zone |
| Logs | JSON lines with a request id; never bodies, tokens, cookies, names, MRNs or lab values. Tests assert this per service |
| Seeds | Deterministic UUIDv5 ids from one namespace; dates relative to the seed day; idempotent ([DATABASE.md](DATABASE.md#synthetic-data)) |
| Settings | Environment variables read by pydantic-settings; each service has its own `.env.example`; production refuses unsafe values at start-up |
| Deviations | Where the build differs from a design document, the service README has a row in its "Design and deviations" table with the reason. Rows are never deleted; a resolved row is marked resolved |
| Frontend | The rules in [CLAUDE.md](../CLAUDE.md): standalone components, OnPush, signals, typed forms, no `any`, tokens instead of literals, Docker only for Node |
| Commits | Conventional Commits with a scope, for example `feat(lab): return result_count on /latest` |

## How AI coding agents were used

The assignment encourages AI coding tools. They were used as follows, and every change was checked by tests and by reading
the result.

1. **Design first.** The system design ([HLD.md](HLD.md)) and one design per service (`<service>/docs/<service>-HLD-LLD.md`)
   were written before the code. They fix the boundaries, the data model, the error codes and the tests to write.
2. **A build plan per service.** Each service has a phase list ([auth-svc](../auth-svc/README.md), [patient-svc](../patient-svc/docs/PHASES.md),
   [lab-svc](../lab-svc/docs/PHASES.md), [ai-svc](../ai-svc/docs/PHASES.md), [gateway](../gateway/docs/PHASES.md)) that was given to the agent one
   phase at a time. The plans are kept as a record of how each service was built; the READMEs describe the result.
3. **Standing rules for the frontend.** The root [CLAUDE.md](../CLAUDE.md) is the rule file the frontend agent read on every task:
   the visual source of truth is the HTML prototype, the architecture rules, the quality gates and the Docker-only rule.
4. **Gap-closing passes.** After the first build, written lists of gaps (documents that claimed something the code did not do,
   missing wiring between services, stale numbers) were handed to the agent as prompts, one phase per commit.
5. **Verification.** A phase ends only when the service's tests and linters pass; the frontend adds `ng build` with no warnings
   and a browser check of the screens touched. Deviations found along the way are written into the README tables.

The agent was never trusted for clinical content: ranges, rules and the AI safety checks are written as code with tests, and
the AI features validate the model's output instead of assuming it is right.

## Add an endpoint end to end

Example: a new read endpoint in lab-svc used by the Angular app.

1. **Service.** Add the schema in `app/schemas`, the query in `app/repositories`, the use case in `app/services`, and the route
   in `app/api`. Raise `AppError` subclasses for domain errors. Add a migration if the schema changes.
2. **Tests.** Add API tests with the real test database (`tests/api`) and, for a pure rule, a unit test. If another service
   reads the response, update that provider's JSON Schema in `contracts/` and copy it to the consumer's `tests/contract/`
   (ai-svc compares its copies with the providers').
3. **OpenAPI.** Run `make -C lab-svc openapi`, which rewrites `docs/api/openapi.json`.
4. **Gateway.** A path under an existing prefix (`/api/labs/...`) needs no change. A new prefix needs a row in
   `gateway/app/routing/table.py`, a public-route entry only if it needs no token, and a rate-limit policy if it is expensive.
   Repeat the prefix in `scripts/docs/gen_api_docs.py`.
5. **Frontend.** Add the path to `core/api/endpoints.ts`, the DTO to `core/api/dto`, a mapper if the view model differs, a method on
   the feature's API service in `core/data`, and a test with the fake HTTP backend. Show the data inside `emr-remote-state`.
6. **Documentation.** Run `make docs` (re-exports OpenAPI and rewrites the generated tables in [API.md](API.md)), add a
   row to the service README's endpoint table, and update [ASSIGNMENT-CHECKLIST.md](ASSIGNMENT-CHECKLIST.md) if a requirement
   moved. Then `make docs-check`.

## Documentation tooling

| Command | What it does |
|---|---|
| `make docs` | Re-exports each service's OpenAPI file, then rewrites the generated endpoint tables in [API.md](API.md) |
| `make docs-check` | Fails when a relative link or anchor in the Markdown files is broken, or when the generated tables are out of date |
| `make schema-dump` | Writes a schema-only dump of each database to `docs/db/<service>.sql` (needs the Postgres container) |

The scripts use only the Python standard library.
