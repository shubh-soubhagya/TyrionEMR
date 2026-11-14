# ai-svc

The AI clinical assistant and the deterministic insights. ai-svc builds the AI clinical summary of a patient (context
preparation, optional tool calling, an LLM adapter, validation, provenance), and it computes the worklist, the dashboard
numbers and the per-patient gap findings that the Angular app shows. The insights never call the LLM.

It owns: AI summaries and their tool-call log, the gap and attention rules, the worklist and dashboard computation, the
prompts, the LLM adapters.
It does not own: patients or lab results (it reads them from patient-svc and lab-svc), accounts (auth-svc). AI output is
never written into the chart.

Synthetic data only. Design: [docs/ai-svc-HLD-LLD.md](docs/ai-svc-HLD-LLD.md). The architecture summary is in
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#ai-integration).

## Endpoints

Full reference: [docs/API.md](../docs/API.md#ai-svc). Paths are reached through the gateway under `/api`. Recorded example
responses (running, completed, cache hit, degraded, failed, and the three insights): [docs/api/examples/](docs/api/examples/).

| Method | Gateway path | Notes |
|---|---|---|
| POST | `/api/ai/patients/{id}/summary?force=` | `202` with `Location`. A duplicate POST joins the running job (`deduplicated: true`). `429 AI_QUOTA_EXCEEDED` with `Retry-After`. `401 TOKEN_EXPIRED` when the token has under 30 s left |
| GET | `/api/ai/summaries/{id}?include=context` | Poll about once a second. A finished summary is cacheable (`ETag`, `immutable`). The context view never contains the reference index or identifiers |
| GET | `/api/ai/patients/{id}/summaries?page=&size=` | Completed and degraded originals, newest first |
| GET | `/api/insights/patients/{id}/gaps` | Rule findings with evidence references, counts and the attention reasons |
| GET | `/api/insights/worklist?attention=true` | Patient ids and reasons in attention order |
| GET | `/api/insights/dashboard` | KPIs, attention rows, eGFR distribution, abnormal results. A 30 s single-flight snapshot; `Cache-Control: no-cache` recomputes |

Not routed by the gateway: `GET /health`, `/ready` (database, migrations at head and JWKS; the upstreams and the LLM are not
readiness checks) and `/metrics`. ai-svc exposes no `/internal` routes of its own.

The two groups differ in what they need. Insights read patient-svc and lab-svc and run pure rules: no LLM, no database,
so they keep working when either is down (an import test enforces it). Summaries need the database, the upstreams and,
for the narrative, the LLM; when the LLM fails the summary is still saved with the facts and findings (`degraded`).

## Data

Database `nephro_ai_db` (tests use `nephro_ai_db_test`). Schema: [docs/DATABASE.md](../docs/DATABASE.md#ai-svc).

| Table | Holds |
|---|---|
| `ai_summaries` | One row per summary job: status, validated output, facts, findings, sources, validation report, progress, error code, token counts |
| `llm_tool_calls` | Append-only log of the read-only tool calls the model made |

Migration: `0001` initial schema. `ai_svc` can connect to `nephro_ai_db` (and `_test`) only.

## Dependencies

| Dependency | Used for | If it fails |
|---|---|---|
| patient-svc `/internal/patients/...` | Chart, conditions, encounters, medications, allergies, bulk charts for insights. Connect 1 s, read 3 s (bulk 8 s), 2 retries on GET | The summary job fails with `UPSTREAM_UNAVAILABLE` or `UPSTREAM_TIMEOUT`; insights answer `502` or `504` |
| lab-svc `/internal/labs/...` | Latest results, trends, history, bulk status | Same |
| LLM provider | The narrative sections | The summary is saved as `degraded` (facts and findings only). A circuit breaker opens after 5 consecutive failures for 60 s |
| auth-svc JWKS | Token verification | Cached keys keep working |
| `nephro_ai_db` | Jobs and history | `/ready` fails; insights are unaffected |

## Run

As part of the stack: see the root [README](../README.md#quick-start). Alone, for development (Python 3.12 and the shared
Postgres container on host port 5433):

```bash
cp .env.example .env            # needed: the code default provider is groq, the example sets mock
make init-db init-test-db       # idempotent: role ai_svc, nephro_ai_db and nephro_ai_db_test
make install migrate            # venv, alembic upgrade head
make run                        # http://localhost:8004 (/docs when APP_ENV is not production)
make reap                       # run the stale-job reaper once
make openapi check-openapi      # export and verify docs/api/openapi.json
make live-llm                   # opt-in smoke test against the real Groq API (synthetic patient only)
```

In Docker (on `nephro-net`): `make up`. The service publishes no port, the container is non-root with a read-only file
system, and it runs one Uvicorn worker, because the LLM semaphore, circuit breaker, insights cache and job registry are
per process (AI-ADR-9).

## Configuration

Service-specific settings. The full list is in [.env.example](.env.example); defaults are in `app/core/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `groq` in code, `mock` in `.env.example` | `mock` or `groq` |
| `LLM_API_KEY` or `LLM_API_KEY_FILE` | unset | Groq key; the file (a Docker secret) wins. Never logged |
| `LLM_MODEL` | `openai/gpt-oss-20b` | Groq model |
| `LLM_MAX_OUTPUT_TOKENS` | 1400 in code, 2048 in `.env.example` | Reasoning tokens count against it, so it is not set lower for gpt-oss |
| `LLM_TIMEOUT_S`, `LLM_MAX_CONCURRENCY` | 30, 4 | Per-call deadline and concurrent calls |
| `LLM_TOOLS_ENABLED` | `true` | Let the model call the read-only tools |
| `AI_DAILY_QUOTA_PER_USER` | 50 | Summaries per user per day (clinic time zone) |
| `APP_ENV` | `dev` | `dev` enables the `X-Mock-Scenario` header (mock provider only) |
| `PATIENT_SVC_URL`, `LAB_SVC_URL`, `JWKS_URL` | `http://<service>:8000` | Upstreams |
| `NO_RECENT_LABS_DAYS`, `EGFR_DISCORDANCE_TOLERANCE` | 180, 12 | Gap-rule thresholds |
| `INSIGHTS_CACHE_TTL_S` | 30 | Dashboard snapshot lifetime |

### LLM providers and demo scenarios

The stack needs no API key: with `LLM_PROVIDER=mock` the deterministic mock provider writes the narrative. To use Groq, set
`LLM_PROVIDER=groq` and a key in `ai-svc/.env` and run `docker compose up -d ai-svc`. The Groq adapter uses plain `httpx`
and no vendor SDK.

With the mock provider and `APP_ENV=dev`, the header `X-Mock-Scenario` selects a scenario per job. The AI tab's demo options
send it (the gateway forwards it only outside production):

| Scenario | Shows |
|---|---|
| `success`, `tool_roundtrip` | A normal summary, and one that used tool calls |
| `invalid_then_valid`, `invalid_twice` | Output repaired after one retry, and output rejected twice (degraded) |
| `unsafe_then_safe`, `unsafe_twice` | The safety lint blocking prescribing language, then repairing or degrading |
| `bad_refs` | Citations that do not exist, stripped |
| `timeout`, `rate_limited`, `upstream_down` | The LLM failure paths (degraded) |

Prompts are Markdown files in `app/prompts/<version>/`. gpt-oss is a reasoning model, so `reasoning_effort` is kept at `low`.
No embedding model is used.

## Tests

```bash
make test       # needs AI_TEST_DATABASE_URL; REQUIRE_DB_TESTS=1 fails instead of skipping
make lint       # ruff
```

Last recorded full run: 388 passed, 1 skipped (the opt-in live Groq test).

| Rule | Test |
|---|---|
| Sixteen gap rules and the attention rule fire on the right data | `tests/unit/test_rules.py`, `tests/unit/test_attention_dashboard.py` |
| Insights never import the LLM or the database layer | `tests/unit/test_layers.py` |
| Context is minimised: no name, MRN, phone or email; stable references; deterministic hash | `tests/unit/test_context.py` |
| Validation: schema, citations, numeric grounding, safety lint, one repair | `tests/unit/test_validation.py` |
| Timeout, retry, rate limit and the circuit breaker | `tests/unit/test_resilience.py` |
| Tools are read-only, patient-bound, bounded | `tests/api/test_tools.py` |
| The summary API: 202 and polling, deduplication, quota, cache, degraded and failed shapes | `tests/api/test_summary_api.py`, `tests/api/test_examples.py` |
| The client models and rules agree with what patient-svc and lab-svc really send | `tests/contract/` |

### Contract fixtures

`tests/fixtures/seed.py` builds the ten HLD §18 patients by hand from the providers' JSON Schemas. `make capture-fixtures`
records the real upstream responses (the stack running and seeded) into `tests/fixtures/captured/`, and
`tests/contract/test_captured.py` checks them against the schemas and the client models and asserts HLD §18 on all ten
patients (6 need attention, 4 show a rapid decline). The captured files are committed, so these tests always run.
After a change to a provider's contract, copy its schema into `tests/contract/` and recapture.

## Design and deviations

Design: [docs/ai-svc-HLD-LLD.md](docs/ai-svc-HLD-LLD.md). Build plan (kept as a record): [docs/PHASES.md](docs/PHASES.md).

| # | Design says | Here | Why |
|---|---|---|---|
| D1 | FastAPI `redirect_slashes=True` | `redirect_slashes=False`: `/insights/dashboard/` is a 404 | A 307 through the gateway would leak the upstream path (gateway LLD R14) |
| D2 | Providers `mock`, `gemini`, `groq`, `ollama` | `mock` and `groq` are built; the database check accepts the other names | The free tier and the mock cover the need |

## Known limitations

- Jobs run in process. A restart loses running jobs; the reaper marks them failed after the job deadline.
- One Uvicorn worker, so the LLM concurrency limit and the insights cache are per process.
- Names inside free text cannot be scrubbed reliably by pattern; the minimiser is built for synthetic data (design B5.4).
- The worklist and dashboard read all patients in pages on each refresh (cached for 30 s); a large clinic would need a
  materialised worklist.
