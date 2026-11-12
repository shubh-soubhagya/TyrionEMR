# ai-svc

Deterministic insights (gap rules, attention rule, worklist, dashboard) and the AI clinical summary (context builder,
tool calling, LLM adapter, validation, provenance) for the NephroCare EMR.

- Design: [docs/ai-svc-HLD-LLD.md](docs/ai-svc-HLD-LLD.md) (the source of truth). Build plan and status: [PHASES.md](PHASES.md).
- API export: [docs/api/openapi.json](docs/api/openapi.json). Recorded responses (running, completed, cache hit,
  degraded, failed, insights): [docs/api/examples/](docs/api/examples/).
- Insights never call the LLM (enforced by an import test) and never touch the database, so they keep working when
  either is down. AI output is never written into the chart.

## Run (same Postgres container as auth-svc, patient-svc and lab-svc)

```bash
cp .env.example .env            # AI_DB_PW, the two URLs (host port 5433), LLM_API_KEY
make init-db init-test-db       # idempotent: role ai_svc, nephro_ai_db, nephro_ai_db_test
make install migrate            # venv, alembic upgrade head
make run                        # http://localhost:8004  (/docs when APP_ENV is not production)
make test                       # needs AI_TEST_DATABASE_URL; REQUIRE_DB_TESTS=1 fails instead of skipping
make lint                       # ruff
make openapi check-openapi      # export / verify docs/api/openapi.json
make reap                       # run the stale-job reaper once
make live-llm                   # opt-in smoke test against the real Groq API (synthetic patient only)
```

In Docker (attached to `nephro-net`, where Postgres has the alias `postgres`): `make up`. The service publishes no
port; only the gateway does. The container is non-root with a read-only root file system and ONE Uvicorn worker
(the LLM semaphore, circuit breaker, insights cache and job registry are per process, AI-ADR-9).

`ai_svc` can connect to `nephro_ai_db` (and `_test`) only; it is refused on the other services' databases.

## LLM

Groq only, over raw httpx (no vendor SDK), model `openai/gpt-oss-20b` (the same as the Granthan llm-service).
`LLM_API_KEY` comes from `LLM_API_KEY_FILE` (Docker secret) or the environment and is never logged. `LLM_PROVIDER=mock`
runs the deterministic MockProvider; with `APP_ENV=dev` the header `X-Mock-Scenario` selects a scenario
(`success`, `tool_roundtrip`, `invalid_then_valid`, `invalid_twice`, `bad_refs`, `unsafe_then_safe`, `unsafe_twice`,
`timeout`, `rate_limited`, `upstream_down`). Prompts are Markdown files in `app/prompts/<version>/`.

gpt-oss is a reasoning model: reasoning tokens count against `LLM_MAX_OUTPUT_TOKENS` (2048), and `reasoning_effort`
is kept at `low`. No embedding model is used by this service.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/ai/patients/{id}/summary?force=` | `202` + `Location`; a duplicate POST joins the running job (`deduplicated: true`); `429 AI_QUOTA_EXCEEDED` with `Retry-After`; `401 TOKEN_EXPIRED` when the JWT has < 30 s left |
| GET | `/ai/summaries/{id}?include=context` | Poll every second. Terminal rows are cacheable (`ETag`, `immutable`); the context view never contains the ref index or identifiers |
| GET | `/ai/patients/{id}/summaries?page=&size=` | Completed and degraded originals, newest first |
| GET | `/insights/patients/{id}/gaps` | Rule findings with evidence refs, counts, attention |
| GET | `/insights/worklist?attention=true` | Ids and reasons in attention order |
| GET | `/insights/dashboard` | KPIs, attention rows, eGFR distribution, abnormal results; 30 s single-flight snapshot, `Cache-Control: no-cache` recomputes |
| GET | `/health`, `/ready`, `/metrics` | `/ready` checks DB, migrations at head and JWKS; upstreams and the LLM are not readiness checks |

## Dependencies on other services

lab-svc must add `first_result_at` and `egfr_lt60_run` (B20.1) to `/latest` and `/internal/labs/status`, and reseed
Kavita Joshi's eGFR 59 -> 49. Until then the rules `NO_ESTABLISHED_CKD_STAGE` and `LAB_DATE_INVALID` stay quiet and she
is not on the worklist; the fields are optional in the client models and the contract tests allow them as extras.
