> Build plan used with an AI coding agent. Kept as a record of how the service was built; the README describes the result.

# ai-svc — Development Phases

Source of truth: [docs/ai-svc-HLD-LLD.md](ai-svc-HLD-LLD.md) (§ numbers below are its sections: A = HLD part, B = LLD part, AI-ADR = its decisions). System context: HLD v2 (`../docs/HLD.md`). The phases follow the build checklist in B21, grouped into 10.
Layout is B1 (`app/api`, `app/core`, `app/insights`, `app/context`, `app/prompts`, `app/llm`, `app/tools`, `app/validation`, `app/orchestrator`, `app/jobs`, `app/clients`, `app/repositories`, `migrations`, `tests`). Database objects live in `nephro_ai_db` / `nephro_ai_db_test` on the shared `graphgpt-postgres` container, network `nephro-net` (B18).
Each phase is finished, tested and committed before the next starts. Tests run against the real Postgres test database; upstreams are mocked with `respx`.

## Overview

| # | Phase | LLD | B21 step | State |
|---|---|---|---|---|
| 1 | Database provisioning and skeleton | B18.1–B18.3, B2, B8 (A8), B16 | 1, 2 | ✅ |
| 2 | Schema migration `0001` and repositories | B3, B15 | 3 | ✅ |
| 3 | Pure rule engine (16 rules, attention, CKD-EPI) | B4, B17.1 | 4 | ✅ |
| 4 | Downstream clients, adapters and parity test | B14, B4.1, B17.5, B20.1 | 5 | ✅ |
| 5 | Insights endpoints and snapshot cache | B11, B12.6–B12.8, B17.6 | 6 | ✅ |
| 6 | Context builder, refs, minimizer, hashing, prompts | B5, B6 | 7 | ✅ |
| 7 | MockProvider, orchestrator, job runner, summary API | B7, B10, B12.3–B12.5 | 8 | ✅ |
| 8 | Validation pipeline, safety lint, hydration | B9, B17.1 | 9 | ✅ |
| 9 | Tool calling and a real provider adapter | B8, B7.2–B7.4, B17.4 | 10, 11 | ✅ |
| 10 | Image, observability, contracts and handover | B16, B17, B18.4–B18.11, B19 | 12, 14 | ✅ |

Out of scope here (B21 step 13): the gateway routes (`/api/ai/**`, `/api/insights/**`, polling bucket) and the Angular dashboard, list filter, Overview alert and AI tab.

Cross-service prerequisites (B20.1) that block phases 4–5: lab-svc must expose `first_result_at` and `egfr_lt60_run` (rules version `lab-rules-2`) and reseed Kavita Joshi (PT-000110) eGFR 59 → 49. Until then phases 3–4 use captured fixtures.

---

## Phase 1 — Database provisioning and skeleton (B18.1–B18.3, B2, A8)
**Goal:** a service that boots, authenticates and answers health checks, with no business logic.
- Inspect `graphgpt-postgres`; idempotent `setup/init-ai-db.sh` and `init-ai-db-test.sh`: role `ai_svc`, `nephro_ai_db`, `nephro_ai_db_test`, `CONNECT` revoked from `PUBLIC`, `timezone=UTC`. Join `nephro-net` with the `postgres` alias. Isolation check (B18.8): `ai_svc` cannot connect to other services' databases.
- `pyproject.toml`, `Makefile`, `.env.example` (all B2 variables, mock provider default), `docker-compose.yml`.
- `core/`: `config.py` (every B2 setting), `security.py` + `jwks.py` (RS256, cached JWKS, refetch on unknown `kid` at most every 30 s, stale-on-error, `require_role("clinician")`), `errors.py` (envelope, B13 codes), `http.py` (ResilientClient: timeouts, GET retries, bulkhead), `logging.py` (JSON, redaction), `clock.py` (injectable `now()`/`today()` in `CLINIC_TZ`), `metrics.py`.
- `api/health.py`: `/health`, `/ready`, `/metrics`. App factory with request-id middleware and lifespan.
- `UVICORN_WORKERS=1` (AI-ADR-9).

**Done when:** `/health` is 200; any other route without a token is 401; wrong role is 403; JWKS cache tests (rotation, outage, unknown kid) pass; isolation check passes.

## Phase 2 — Schema migration `0001` and repositories (B3, B15)
**Goal:** the database enforces everything B3 lists.
- Alembic `0001` in hand-written SQL: `ai_summaries` with all CHECKs (terminal-state shapes, `error_code_values`, `finish_iff_terminal`, `not_self_cached`), `llm_tool_calls`, partial indexes (`ux_summaries_running`, history, cache, quota, reaper), immutability triggers (B3.4), advisory lock in `migrations/env.py`.
- `db/session.py`, `db/tables.py`, `repositories/summaries.py` and `tool_calls.py`: insert running row, progress/heartbeat write, final write, cache lookup, history, quota count, reap query, tool-call append.
- Pydantic models for every JSON column (B3.5) validated before write.
- `entrypoint` runs migrations under the lock when `RUN_MIGRATIONS_ON_START=true`.

**Done when:** `alembic upgrade head` is clean on an empty database; database-guard tests cover each constraint (second running row for the same patient and clinician rejected, completed row missing a part rejected, cache-hit with its own output rejected, update of a terminal row rejected, delete rejected, tool call on a finished summary rejected, `TRUNCATE` still works); statement timeout is applied.

## Phase 3 — Pure rule engine (B4, B17.1)
**Goal:** every insights rule is a pure, tested function.
- `insights/rules/facts.py` (frozen dataclasses), `constants.py` (display names, decimals, thresholds), `ckd_epi.py` (CKD-EPI 2021), `gaps.py` (the 16 rules with codes, severities and messages from the HTML prototype, `RULES_VERSION`), `attention.py` (attention rule and reason text), `dashboard.py` (KPIs, eGFR distribution, abnormal-results capping and ordering).
- Thresholds read from config; a change bumps `RULES_VERSION` (B4.7).
- `tests/unit/test_layers.py`: `insights/` imports no `llm`, `orchestrator`, `tools`, `validation`, `prompts`; pure packages import no `fastapi`, `sqlalchemy`, `httpx`.

**Done when:** every B17.1 rule has a positive, a negative and a boundary case (180 days, tolerance 12, 90-day run, exact slope thresholds); CKD-EPI vectors pass; layer tests pass.

## Phase 4 — Downstream clients, adapters and parity test (B14, B4.1, B17.5)
**Goal:** one `PatientFacts` model fed from both upstream shapes.
- `clients/patient.py`: `GET /internal/patients/{id}/basic`, `/chart`, tool endpoints, `/internal/patients/charts` (keyset pages). `clients/lab.py`: `/latest`, `/trends`, `/results`, `/internal/labs/status`. User JWT and `X-Request-ID` forwarded; timeouts, GET-only retries, bulk timeout; upstream failures mapped to `UPSTREAM_UNAVAILABLE` / `UPSTREAM_TIMEOUT` naming the upstream.
- `insights/rules/adapters.py`: `from_chart(...)` and `from_bulk(...)`.
- Fixtures captured from patient-svc and lab-svc seeds under `tests/fixtures/`.
- Parity test: every seed patient through both adapters yields identical findings (AI-ADR-5).

**Done when:** client tests (`respx`) cover success, timeout, 5xx retry, 4xx mapping and header forwarding; parity test is green on the captured fixtures.

## Phase 5 — Insights endpoints and snapshot cache (B11, B12.6–B12.8, B17.6)
**Goal:** gaps, worklist and dashboard work with no database and no LLM.
- `insights/service.py`, `insights/cache.py`: single-patient path (three upstream reads in parallel), bulk path (two keyset-paged reads in parallel, `INSIGHTS_BULK_PAGE`, `INSIGHTS_MAX_PAGES`), 30 s TTL cache with single-flight, `Cache-Control: no-cache` forces recompute, never served stale on upstream failure.
- `GET /insights/patients/{id}/gaps`, `GET /insights/worklist?attention=true`, `GET /insights/dashboard` with the schemas of B12.
- Insights routes keep working when `nephro_ai_db` is down.

**Done when:** B17.3 insights cases pass; the seed expectations of B17.6 hold (6 need attention, 4 rapid decline, per-patient findings); single-flight test shows one upstream fetch for concurrent calls; `/ready` failing on the database does not break insights.

## Phase 6 — Context builder, refs, minimizer, hashing, prompts (B5, B6)
**Goal:** a deterministic, minimized, citable packet and versioned prompts.
- `context/refs.py` (`cond:1`, `lab:EGFR:2026-10-21`, `#2` on same-day collisions; `ref_index`), `packet.py` (B5.2 including `as_of`, draft-encounter count only), `minimize.py` (whitelist, scrub identifiers, truncate, budget `LLM_CONTEXT_MAX_CHARS` with recorded `trimmed`), `hashing.py` (canonical JSON + sha256 over packet, `patient_id`, provider, model, prompt, schema and rules versions, tools flag).
- `prompts/v1/` as Markdown files (`system.md`, `user.md`, `repair.md`) plus `output_schema.json` (prompt text lives in `.md` files, not in code), `loader.py` (read-only, hashed at startup).
- `orchestrator/facts.py`: facts block from lab-svc data, no LLM.

**Done when:** golden test for the PT-000101 packet (reviewed by hand); no UUID, name, MRN, contact or DOB in any packet; two empty-chart patients with the same age and sex get different hashes; hash changes with each key input; refs stable across runs; budget trimming tested.

## Phase 7 — MockProvider, orchestrator, job runner, summary API (B7, B10, B12.3–B12.5)
**Goal:** the full asynchronous summary flow end to end with the mock provider.
- `llm/base.py` (protocol, capabilities), `llm/mock.py` with all B7.5 scenarios, `X-Mock-Scenario` honoured only when `APP_ENV=dev` and the provider is `mock`, `llm/resilience.py` (deadline, retry, `CircuitBreaker`, `ConcurrencyLimiter`), `llm/factory.py`.
- `orchestrator/` (seven steps, `ProgressTracker`, heartbeat ticker), `jobs/runner.py` (task registry, `LLM_JOB_DEADLINE_S`, cancellation), `jobs/reaper.py` (single `UPDATE … WHERE heartbeat_at < …`).
- `SummaryService.start` (B10.2): token TTL check (`401 TOKEN_EXPIRED`), patient existence check, advisory-locked daily quota, deduplication (`deduplicated: true`), cache lookup (completed originals only), insert, `202`.
- Routes: `POST /ai/patients/{id}/summary` (`force=true`), `GET /ai/summaries/{sid}` (`?include=context`), `GET /ai/patients/{id}/summaries` (originals only).
- Degraded and failed outcomes per B10.8; the disclaimer is server text.

**Done when:** B17.2 scenarios pass (`success`, timeout, rate limit, upstream failure, invalid output → degraded with facts and gaps); concurrent POSTs create one job; unchanged data gives a cache hit with zero LLM calls; degraded results are never cache sources; killed job is reaped to `failed JOB_TIMEOUT`; quota race test passes; mock end-to-end under 1.5 s.

## Phase 8 — Validation pipeline, safety lint, hydration (B9)
**Goal:** no unvalidated model output is stored or returned.
- `validation/output_schema.py` (strict model with no diagnosis or prescribing fields), `refs.py` (citation check and stripping, "Not documented." for sections without refs), `numbers.py` (rounding-aware grounding, derived values, dates and ref ids excluded; misses are warnings), `safety.py` (directive treatment and diagnostic assertions everywhere, dose patterns in follow-up considerations only), `hydrate.py` (sources map: label, tab, target id), `pipeline.py` (parse → schema → refs → numbers → safety → verdict).
- Repair once with the failure reason; second safety hit redacts the sentence and records it (AI-ADR-8).
- The `validation` block for the UI (B9.8): sources found, safety result, corrected once.
- Wire the pipeline into orchestrator step 6 and the final write.

**Done when:** B17.1 safety and grounding cases pass; `unsafe_twice` redacts and reports "1 item removed"; unknown refs are stripped and counted; invalid JSON repaired once, then degraded; no stored `output` fails the schema.

## Phase 9 — Tool calling and a real provider adapter (B8, B7.2–B7.4, B17.4)
**Goal:** bounded read-only tools and one flag-gated real provider.
- `tools/registry.py` (spec validation, execution, per-call and per-job caps, result truncation, recording to `llm_tool_calls`), `tools/definitions.py` (the six tools, `patient_id` server-bound, patient free text treated as untrusted data).
- Orchestration loop per B8.3 honouring `LLM_MAX_TOOL_ITERATIONS`, `LLM_MAX_CALLS_PER_TURN`, `LLM_MAX_TOOL_CALLS`; `json_with_tools` capability handling (final turn forced without tools, with JSON mode); mock `tool_roundtrip` scenario.
- One real adapter over `httpx` (no vendor SDK), chosen from Gemini / Groq / Ollama; verify request and response shapes and capabilities against the provider's current docs (B20.3 #1) and record the model in `.env.example` (B20.3 #2). API key from `LLM_API_KEY_FILE`, never logged; provider error bodies not logged.
- Tool calls on a finished summary are rejected by the database.

**Done when:** `tool_roundtrip` passes; invented tool names are stored as `unknown`; caps enforced; a tool 401 or timeout becomes a tool error, not a failed job; adapter tests (`respx`) cover success, 429 with `Retry-After`, 5xx retry, timeout, breaker open; manual run on PT-000101 completes with the real provider.

## Phase 10 — Image, observability, contracts and handover (B16, B17, B18.4–B18.11, B19)
**Goal:** a deployable service with a closed test plan.
- Non-root, read-only-rootfs Dockerfile; `docker-entrypoint.sh` (wait for DB, migrate); Compose on `nephro-net` with no published port; Makefile targets; connection budget check (B18.10).
- Metrics and logs per B16 (IDs, counts, codes and latencies only; no prompt, packet, output, names or notes); log-redaction test.
- `cli/export_openapi.py` → `docs/api/openapi.json`; contract tests (B17.7) against patient-svc and lab-svc shapes and the schema of the summary response.
- Close the B17 test plan; seed walk-through; screenshots or recorded responses of the normal, progress, degraded and failed states.
- Update this file and open items (B20.3) with what was decided (below).

**Done when:** `make up` reaches `/ready` on `nephro-net`; full suite is green on the real Postgres test database; `openapi.json` committed; with the LLM provider stopped, insights still work and summaries degrade; with ai-svc stopped, patient-svc and lab-svc are unaffected.


---

## Built and verified (phases 6-10)

| Phase | What exists | Verified by |
|---|---|---|
| 6 | `context/` (refs, packet, minimizer, hashing), `prompts/v1/*.md` + `output_schema.json`, `orchestrator/facts.py` | `tests/unit/test_context.py` |
| 7 | `llm/` (types, resilience, mock, factory), orchestrator, progress, job runner, reaper, `SummaryService`, `/ai/**` | `tests/unit/test_resilience.py`, `tests/api/test_summary_api.py` (every B7.5 scenario, cache, quota, single-flight, reaper, shutdown, deadlines) |
| 8 | `validation/` (parse, citations, schema, grounding, safety, hydration) wired into step 6 | `tests/unit/test_validation.py` |
| 9 | `tools/` (six tools + registry), `llm/groq.py` | `tests/api/test_tools.py`, `tests/unit/test_groq.py`, live smoke test `tests/live` (real Groq, PT-000101: completed, 11 refs resolved, 0 stripped, no repair) |
| 10 | Dockerfile (hash-locked, non-root, read-only rootfs), entrypoint, compose, `make` targets, B16 logs and metrics, OpenAPI export, recorded examples, contract tests | image built and `/ready` reached from `nephro-net`; `tests/api/test_logs_and_metrics.py`, `tests/contract` |

### Decisions and deviations
- **Groq only** (B20.3 #1, #2): `json_with_tools=false`, `openai/gpt-oss-20b`, `reasoning_effort=low`, `LLM_MAX_OUTPUT_TOKENS=2048`. Gemini and Ollama adapters are not built; the provider CHECK in the database still allows them.
- **Disclaimer text** is the one in the frontend's CLAUDE.md (section 7), so the UI can show the server text verbatim. B12.4's example wording is shorter.
- **Numeric grounding**: 0-10 are always allowed (small counts), so B9.4's example "2.0 for 1.898" would not warn; the test uses values outside that range.
- **S1 safety rule** matches base and -ing verbs only, not past tense, so "Losartan 50 mg was started in 2023" in a history passes.
- **Quota** is checked at POST, before the cache lookup (the cache hash needs the chart, which only the job reads). A cache hit does not consume quota; it can still be refused when the day's quota is already used up.
- **Contract mismatch found and fixed**: lab-svc's real `/latest` is eight tiles plus a `ckd` block, not the `latest` map assumed from the LLD. `Latest` normalizes both shapes; the seed now follows the contract and the contract tests would have caught it.
- **Still open** (B20.3): #3 thresholds (12 and 180 as in the HLD), #4 degraded-after-a-call jobs count toward quota (yes), #5 retention (kept indefinitely, synthetic data), #6 Kavita seed fix is lab-svc's.
- Not done: gateway routes and the Angular wiring (B21 step 13); fixtures are hand-built from the contracts rather than captured from running services (`make capture-fixtures` is not written).
