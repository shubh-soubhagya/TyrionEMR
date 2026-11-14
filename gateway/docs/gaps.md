# TyrionEMR: close the backend gaps and connect the frontend through the gateway

> Paste everything below the line into your coding agent, opened at the TyrionEMR repo root.
> Written from `main` at commit `c71f7dc` (13 Nov 2026).

---

You are finishing the TyrionEMR repo (General Nephrology EMR). Four FastAPI services (auth-svc, patient-svc,
lab-svc, ai-svc) and the custom API gateway (Phases 1–7) are on `main`. The Angular frontend renders every
screen, but against an in-memory fake backend (`frontend/src/app/core/data/db.service.ts` plus localStorage).
Your job has two parts:

- **Part A (backend):** close the gaps listed in section 3 so that the whole stack runs from one set of
  commands, with every service reachable only through the gateway.
- **Part B (frontend):** replace the in-memory backend with real HTTP calls through the gateway, build sign-in
  and sign-up, and remove every piece of client-side code that recomputes what a service owns.

Read every section before you start. Section 0 overrides anything else in this prompt.

---

## 0. Ground rules (apply to every step)

**Git**
- Work on `main` only. Do not create, switch to, or merge any other branch.
- Before starting: `git checkout main && git pull --ff-only && git status`. If the tree is not clean, show
  me the status and stop.
- One commit per phase (more is fine, never fewer), Conventional Commits with a scope, e.g.
  `feat(lab): expose first_result_at and egfr_lt60_run`, `feat(frontend): add the auth interceptor`.
- Stage explicit paths only (`git add lab-svc/app/... lab-svc/tests/...`). Never `git add -A` or `git add .`.
- Do not push unless I ask.

**Scope**
- Each phase names the folders it may change. Touch nothing else. If a fix needs another folder, stop and ask.
- Follow each service's own conventions exactly: its `app/core` layout, error envelope
  `{error: {code, message, details, request_id}}`, injectable clock, hash-locked requirements, `make` targets,
  README "Deviations" table. When you deviate from a design document, add a row to that service's README
  deviations table in the same commit. Never deviate silently.
- Design documents are the authority for behavior: `docs/HLD.md` (system), `<svc>/docs/*-HLD-LLD.md`
  (service), `gateway/docs/gateway-HLD-LLD.md`. The frontend's authority is the repo-root `CLAUDE.md`,
  `frontend/docs/decisions.md` and `reference/emr-ui.html` (look) plus `reference/assignment.pdf` (behavior).
- Do **not** change auth-svc's database roles (`auth_app` / `auth_migrator`), its token format, or its cookie
  attributes. Tokens stay free of PII (auth LLD §17.9).
- Synthetic data only. Never log PHI, tokens, cookies, query strings or request bodies, in any service or test.
- No new npm or pip dependency unless you state why and what the alternative was, in the phase report.

**Frontend tooling (from the root `CLAUDE.md`, non-negotiable)**
- Docker only. Never run `node`, `npm`, `npx` or `ng` on the host. Use
  `docker compose -f frontend/compose.yaml exec web <cmd>` (or `cd frontend && docker compose exec web <cmd>`).
- Standalone components, `OnPush`, `inject()`, signal `input()/output()/model()`, built-in control flow,
  typed reactive forms, functional guards and interceptors, `strict: true`, no `any`, no `!` without proof.
- RxJS for HTTP and streams only; convert to signals at the component boundary (`toSignal`); unsubscribe with
  `takeUntilDestroyed()`.
- Every async view has explicit loading, empty, error and success states, modelled as a discriminated union,
  never as tangled boolean flags.
- Visual output must stay identical to `reference/emr-ui.html`. Wiring real data must not change the look.

**Verification (every phase)**
- Backend phases: the service's `make test` (with `REQUIRE_DB_TESTS=1` where the service supports it, so DB
  tests fail instead of skipping) and `make lint`, run for real. Paste the summary line (passed / failed /
  skipped counts).
- Frontend phases: `ng build` with zero errors and zero warnings, `ng test --watch=false` green, `ng lint` clean,
  `prettier --check` clean, browser console clean on the screens you touched.
- After each phase, report in 5–10 lines: what changed, the gap IDs closed (section 3), test counts, lint and
  build status, commit hash, and anything you deferred and why.

**Stop and ask only if**
1. a design document cannot work as written (show the evidence and propose a fix);
2. you need a deviation not approved in this prompt;
3. you need to change a folder the phase does not name;
4. Docker, the `nephro-net` network or the shared Postgres container (`graphgpt-postgres`) is missing or not
   running. **Never create, drop or alter anything on the shared Postgres container** except through each
   service's existing idempotent `setup/init-*-db.sh` scripts, and only after I confirm;
5. a test that passed before your change now fails and the fix is not obviously inside your phase.

Otherwise do not wait for me between phases.

---

## 1. Read first (then send me one plan message and wait for "go")

1. `docs/HLD.md` §3 (architecture), §4 (service catalog), §5.6 (how screens compose data), §7 (auth), §8
   (gateway), §10.3 (AI pipeline and polling), §10.9 (summary response), §10.12 (insights), §11 (API surface),
   §15 (frontend), §17 (deployment), §18 (synthetic data), §21 (submission checklist).
2. Each service's `README.md` (endpoints, deviations, open items) and `docs/api/*.json` (OpenAPI):
   `auth-svc/docs/api/openapi.json`, `patient-svc/docs/api/patient-svc.json`, `lab-svc/docs/api/lab-svc.json`,
   `ai-svc/docs/api/openapi.json`, and `ai-svc/docs/api/examples/*.json` (recorded summary and insights
   responses).
3. `ai-svc/docs/ai-svc-HLD-LLD.md` §B20.1 (what ai-svc needs from lab-svc).
4. `gateway/README.md`, `gateway/PHASES.md` (Phases 8 and 9 are not done), `gateway/docs/gateway-HLD-LLD.md`
   §6, §8, §18, §22, §28, §29, §32.
5. Frontend: root `CLAUDE.md`, `frontend/README.md`, `frontend/docs/decisions.md` (**D3 is the auth design you
   implement**), `frontend/docs/build-checklist.md`, `frontend/docs/ui-inventory.md`, then every file under
   `frontend/src/app/core/` and `frontend/src/app/features/`.

Then send **one** message containing:
- the current test counts of each service and the gateway (`make test` in each folder; note any skipped),
- every gap in section 3 confirmed or disputed with evidence (file and line),
- anything else you found that is missing or contradictory,
- the order you will run the phases in, if different from section 4.

Wait for my "go". After that, run all phases without waiting, except at the stop conditions in section 0.

---

## 2. Facts about the current stack (verified on `main`)

**Network and ports**
- Docker network `nephro-net` (external). Shared Postgres container `graphgpt-postgres` attached with alias
  `postgres`; host port **5433** (5432 on the host is a different server).
- Containers listen on 8000 and publish nothing: `auth-svc`, `patient-svc`, `lab-svc`, `ai-svc`.
  Only the gateway publishes a host port: `${GATEWAY_PORT:-8080}` → container 8000.
- Host-run (`make run`) ports: auth-svc 8001, patient-svc 8002, lab-svc 8003, ai-svc 8004, gateway 8080.
- Frontend dev server: `frontend/compose.yaml` service `web`, `ng serve` on 4200.

**Auth contract (auth-svc)**
- `POST /auth/login`, `/auth/signup` → `{access_token, token_type: "Bearer", expires_in, user}` and set cookie
  `nephro_rt` (HttpOnly, Secure, SameSite=Strict, **Path=/api/auth**). `POST /auth/refresh` rotates it and
  returns the same shape. `POST /auth/logout` → 204, clears it. `GET /auth/me` → `UserOut {id, email,
  full_name, role, last_login_at}`. `POST /auth/password` (change password) exists.
- `/auth/refresh` and `/auth/logout` reject an `Origin` outside `CORS_ALLOWED_ORIGINS`
  (`http://localhost:4200` in dev).
- Codes the client must handle: `401 TOKEN_EXPIRED`, `401 UNAUTHENTICATED`, `401 INVALID_CREDENTIALS`,
  `429 ACCOUNT_LOCKED` and `429 RATE_LIMITED` (both with `Retry-After`), `409 REFRESH_RACE` (retry, cookie kept),
  `401 REFRESH_REUSED` / `REFRESH_INVALID` / `REFRESH_EXPIRED` (cookie cleared, sign in again),
  `409 EMAIL_TAKEN`, `403 SIGNUP_DISABLED`, `422 VALIDATION_ERROR` with password rule codes in
  `details[].code` (`TOO_SHORT`, `TOO_LONG`, `NEEDS_LETTER`, `NEEDS_DIGIT`, `TOO_COMMON`, `CONTAINS_EMAIL`),
  `503 SERVICE_BUSY`.
- Demo users (when `SEED_DEMO_USERS=true`): `dr.rao@nephrocare.demo` and `dr.malhotra@nephrocare.demo`,
  password `Nephro#2026`.

**Gateway** (`gateway/`, Phases 1–7 done, 8–9 not done)
- Strips only `/api`. Routes: `auth` → auth-svc (cookies forwarded, `Set-Cookie` passed), `patients` and
  `encounters` → patient-svc, `labs` → lab-svc, `ai` and `insights` (10 s timeout) → ai-svc. `/api/internal/**`
  and unknown prefixes → 404. An empty upstream URL → `503 UPSTREAM_NOT_DEPLOYED`.
- Public (no token): exactly `POST /api/auth/login`, `/signup`, `/refresh`, `/logout`.
- Forwards only allow-listed request headers (`gateway/app/services/headers.py`): accept, accept-language,
  authorization, cache-control, content-type, if-match, if-none-match, if-modified-since, idempotency-key,
  origin, user-agent.
- Gateway-made errors: `INVALID_PATH`, `NOT_FOUND`, `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `ORIGIN_NOT_ALLOWED`,
  `PAYLOAD_TOO_LARGE`, `URI_TOO_LONG`, `RATE_LIMITED` (+ `Retry-After`, `details[0].policy`),
  `UPSTREAM_UNAVAILABLE` (502), `UPSTREAM_NOT_DEPLOYED` / `GATEWAY_BUSY` (503), `UPSTREAM_TIMEOUT` (504),
  `UPSTREAM_ERROR` (upstream 5xx without JSON), `INTERNAL_ERROR`.

**Endpoints the frontend uses** (all under `/api` through the gateway)

| Service | Method and path | Notes |
|---|---|---|
| patient | `GET /patients?q=&sex=&stage=&ids=&sort=&dir=&page=&size=` | `sort` ∈ `name, mrn, age, dx, visit`; `stage` ∈ `G1…G5, G3a, G3b, none`; `sort=egfr` is 422 by design (ADR-020) |
| patient | `POST /patients`, `GET/PATCH/DELETE /patients/{id}` | `PATCH` needs `version`; 409 `VERSION_CONFLICT` |
| patient | `GET/POST /patients/{id}/conditions`, `PATCH/DELETE …/{cid}` | `PATCH {is_primary: true}` sets primary; `{status}` resolves/reactivates; response has `primary_cleared` |
| patient | `GET/POST /patients/{id}/medications?status=active\|all`, `PATCH …/{mid}` | `{action: "discontinue"}`; `route` is a code: `oral, sc, iv, topical, inhaled, other` |
| patient | `GET/POST /patients/{id}/allergies`, `DELETE …/{aid}` | responses carry `allergy_status` and `patient_version`; "no known allergies" is `PATCH /patients/{id} {version, allergy_status: "nka"}` |
| patient | `GET/POST /patients/{id}/encounters`, `GET/PATCH/DELETE …/{eid}`, `POST …/{eid}/finalize` | POST/PATCH return `{encounter, problem_list_changes: {added, linked, reactivated}}`; final → 409 `ENCOUNTER_FINAL` |
| patient | `GET /encounters?status=draft&limit=` and `?upcoming_followups=true&limit=` | dashboard; `{items, total}` with `patient_name`, `mrn` |
| lab | `GET /labs/tests?sex=&age=` | catalog: units with exact **string** factors, `range` for that sex; `ETag` |
| lab | `POST /labs/patients/{id}/reports` | `{collected_at, lab_name, notes, results: [{test_code, value, unit}]}` → `{report, results, summary: {n, abnormal, critical}}`; 422 details carry paths like `results[1].unit` |
| lab | `GET /labs/patients/{id}/results?test=&from=&to=&flag=abnormal&page=&size=` | history with `value_original`, `unit_original`, `lab_name` |
| lab | `GET /labs/patients/{id}/trends?tests=CREAT,EGFR&from=` | `series[]` with `points`, `stats`, `reference`, `stage_bands` (eGFR only) |
| lab | `GET /labs/patients/{id}/latest` | tiles in display order, `ckd` block, `has_critical`, `rapid_decline`; `ETag` |
| lab | `GET /labs/summary?patient_ids=a,b` | ≤ 50 ids, one item per id in request order, `has_results`, `latest_egfr`, `spark` |
| lab | `POST /labs/results/{rid}/correct` | `{value, unit, reason}` (no screen yet; do not build one) |
| ai | `GET /insights/dashboard` | `kpis {patients, need_attention, critical_results, rapid_decline}`, `attention[]`, `egfr_distribution`, `abnormal_results[]`; send `Cache-Control: no-cache` to force a recompute |
| ai | `GET /insights/worklist?attention=true` | ids and reasons, attention order |
| ai | `GET /insights/patients/{id}/gaps` | `findings[] {code, severity, kind, message, evidence[] {ref, label, tab, target_id, type}}`, `attention` |
| ai | `POST /ai/patients/{id}/summary?force=` | always `202` + `StartOut {summary_id, status, deduplicated, poll_after_ms, progress}`; `429 AI_QUOTA_EXCEEDED` with `Retry-After`; `401 TOKEN_EXPIRED` if the token has < 30 s left |
| ai | `GET /ai/summaries/{sid}?include=context` | poll until `status` ∈ `completed, degraded, failed`; `SummaryOut {progress, facts, gaps, ai, sources, validation, error_code, error_message, disclaimer, context}` |
| ai | `GET /ai/patients/{id}/summaries?page=&size=` | history (completed and degraded originals only) |
| ai | header `X-Mock-Scenario` (dev only, `LLM_PROVIDER=mock`, `APP_ENV=dev`) | `success, tool_roundtrip, invalid_then_valid, invalid_twice, bad_refs, unsafe_then_safe, unsafe_twice, timeout, rate_limited, upstream_down` |

---

## 3. Gap register (close every item; report against these IDs)

### Backend and platform

| ID | Where | Gap | Evidence |
|---|---|---|---|
| G1 | lab-svc | `first_result_at` and `egfr_lt60_run {since, n}` are missing from `patient_lab_status`, `/labs/patients/{id}/latest` and `/internal/labs/status`. ai-svc's rules `LAB_DATE_INVALID` and `NO_ESTABLISHED_CKD_STAGE` stay silent without them | ai-svc LLD §B20.1 #1–2; `ai-svc/README.md` "Dependencies"; `grep first_result_at lab-svc` finds nothing |
| G2 | lab-svc | Seed profile for Kavita Joshi (PT-000110) is eGFR 58 → 52; ai-svc needs 59 → 49 over 500 days so HLD §18's worklist (6 need attention, 4 rapid decline) holds | `lab-svc/app/cli/seed_labs.py` line with `PT-000110`; ai-svc LLD §B20.1 #3 |
| G3 | ai-svc | Upstream contract fixtures are hand-built; `make capture-fixtures` was never written, so ai-svc has never been checked against real patient-svc and lab-svc responses | `ai-svc/PHASES.md` "Not done" line |
| G4 | ai-svc | `.env.example` defaults to `LLM_PROVIDER=groq` with an empty key. HLD §17.4: the stack must run with no key (`mock`) | `ai-svc/.env.example` |
| G5 | gateway | Phase 8 not done: no `requirements.lock` / `requirements-dev.lock` / `requirements-build.lock` (README D1 claims them), no `Dockerfile`, `scripts/entrypoint.sh`, `docker-compose.yml`, `docker-compose.prod.yml` (README D3 claims it), `setup/network.sh`, `setup/smoke-test.sh`; the Makefile lists `build up down logs smoke` in `.PHONY` without recipes | `find gateway -type f` |
| G6 | gateway | `AI_SVC_URL` is empty in `gateway/.env.example`, but ai-svc exists | `gateway/.env.example` |
| G7 | gateway | `X-Mock-Scenario` is dropped by the request-header allow-list, so the AI tab's demo options can never reach ai-svc | `gateway/app/services/headers.py` `FORWARD_REQUEST_HEADERS` |
| G8 | patient-svc | Uvicorn's default h11 limit (16 KiB request line + headers) rejects `GET /patients?ids=…` with many ids (≈ 18.5 KB for 500 UUIDs). The gateway already allows 32 KiB | gateway LLD R8; `patient-svc/scripts/entrypoint.sh` |
| G9 | all four services | `FastAPI(...)` keeps `redirect_slashes=True`; a trailing slash costs a `307` round trip through the gateway | gateway LLD R14; only `gateway/app/main.py` sets it |
| G10 | auth-svc seed | Demo users get random `uuid4` ids, while patient-svc's seed gives their encounters `clinician_id = uuid5(SEED_NAMESPACE, "user:" + email.lower())`. Seeded encounters therefore belong to ids no real user has | `auth-svc/app/cli/seed_users.py` line 43; `patient-svc/app/domain/seed_ids.py` |
| G11 | repo root | No root `README.md`, no root compose file, no root `Makefile`: nothing starts the whole stack, and the submission items of HLD §21 (setup instructions, API docs index, screenshots) have no home | `ls` at the root |
| G12 | repo root | Root `.env.example` covers only auth-svc and the gateway | `.env.example` |
| G13 | all services | Docker images of patient-svc, lab-svc and ai-svc have never been built and run together (`patient-svc/README.md` O3); auth-svc's README still lists the gateway smoke test as open | READMEs |
| G14 | docs | Stale open items: `patient-svc/README.md` O1 (seed namespace: lab-svc now uses the same one), `ai-svc/README.md` "Dependencies" (closes with G1–G2), `auth-svc/README.md` "Status and open items" | READMEs |

### Frontend

| ID | Gap | Evidence |
|---|---|---|
| F1 | No HTTP layer at all: no `provideHttpClient`, no API services, no interceptors. Every screen reads `DbService` (in-memory + localStorage) | `grep HttpClient frontend/src` finds nothing; `core/data/db.service.ts` |
| F2 | Sign-in and sign-up are placeholders; no `AuthService`, no guards, no session restore; the signed-in user is `layout/placeholder-user.ts` | `features/auth/login-page.ts`, `app.routes.ts` comment "Guards arrive with Phase 5" |
| F3 | Dev `apiBaseUrl` is `http://localhost:8000/api` (nothing listens there) and there is no dev-server proxy, although `decisions.md` D3 requires one | `environment.development.ts`, `angular.json`, `compose.yaml` |
| F4 | Server-owned logic is recomputed in the browser: gap rules, attention, trends, dashboard aggregation, CKD category, MRN generation, problem-list linkage (`core/data/analysis.ts`, `db.service.ts`, `dashboard-page.ts`, `patient-list-page.ts`) | those files |
| F5 | The AI tab is a local simulation (`core/data/ai.service.ts`): fake stepper, fake narrative, fake failures | that file |
| F6 | Patient list filters, sorts and pages in the browser, including a sort by eGFR that the server deliberately does not offer (ADR-020) | `patient-list-page.ts` `result` computed |
| F7 | View models do not match the API: `allergyStatus 'has'` vs `has_allergies`; medication `route` labels vs codes; encounter `cc, exam, followUp, vitals {sys, dia, hr, temp, wt}` vs `chief_complaint, examination_notes, follow_up_date, vitals {systolic_bp, diastolic_bp, heart_rate, temperature_c, weight_kg}`; conditions `icd10, desc, onset` vs `icd10_code, description, onset_date`; labs `test, refLow` vs `test_code, ref_low`; camelCase vs snake_case throughout | `core/data/models.ts` vs the OpenAPI files |
| F8 | The lab form uses a hard-coded catalog (`core/clinical/lab-tests.ts`) instead of `GET /labs/tests`, and the shared vectors (`lab-svc/tests/vectors/lab_cases.json`) are not run by the frontend (HLD ADR-019) | those files |
| F9 | No network loading / error states, no per-panel error isolation on composed screens, no `request_id` shown on errors, no handling of 409 / 422 / 429 envelopes | screens |
| F10 | `useMocks` exists in both environments but nothing reads it | `grep useMocks` |
| F11 | No end-to-end check of the real flow and no screenshots for the submission (HLD §21 item 6); `build-checklist.md` is almost entirely unticked | `frontend/docs/build-checklist.md` |

---

## 4. Part A: backend phases

### A1. lab-svc: fields and seed for ai-svc (closes G1, G2; folders: `lab-svc/`)

1. Migration `0004` (next number after the existing ones): add `first_result_at timestamptz NULL` and
   `egfr_lt60_run jsonb NULL` to `patient_lab_status`. Forward-only in practice, with a working `downgrade()`.
2. `app/domain/status.py` `build_status`:
   - `first_result_at` = minimum `collected_at` over the patient's **current** results (null when none).
   - `egfr_lt60_run` = the trailing run of eGFR values `< 60` that ends at the latest eGFR, as
     `{"since": <collected_at of the first value in the run>, "n": <count>}`; `null` when the latest eGFR is
     `>= 60` or there is no eGFR. Ordering by `(collected_at, created_at, id)` like the rest of the builder.
   - Bump `RULES_VERSION` to `lab-rules-2`.
3. Expose both fields on `GET /labs/patients/{id}/latest` (`LatestOut`) and on every item of
   `GET /internal/labs/status` (`StatusItem`). Update `contracts/lab/latest.schema.json` and
   `status.schema.json`, and re-export the OpenAPI file (`make openapi`).
4. Seed: change PT-000110's profile to eGFR 59 → 49 over 500 days (other values unchanged). Keep the seed
   idempotent. Document how to reseed an existing dev database (`make seed-reset`, dev only).
5. Run `python -m app.cli.rebuild_status --stale-only` logic in tests: rows built with `lab-rules-1` must be
   rebuilt and then pass `--check`.
6. Tests: unit table for `egfr_lt60_run` (no eGFR; latest ≥ 60; run of 1; run broken by a value ≥ 60; ties on
   `collected_at`; a superseded value inside the run is ignored), `first_result_at` with a correction, API tests
   that both endpoints return the fields, the seed test asserting PT-000110's slope ≤ −5 per year (rapid decline)
   and `rapid_decline = true`.
7. README: update the endpoint table and add a deviation row only if you differ from ai-svc LLD §B20.1.

### A2. ai-svc: real contracts, mock by default (closes G3, G4; folders: `ai-svc/`)

1. Make `first_result_at` and `egfr_lt60_run` part of the contract ai-svc reads from lab-svc (keep them
   tolerant of `null`, but a missing key now fails the contract test).
2. Write `make capture-fixtures`: a script (`app/cli/capture_fixtures.py` or `scripts/`) that, given a running
   stack and a token obtained by logging in as the demo user **through the gateway**, saves real responses of
   every upstream call ai-svc makes (`/internal/patients/charts`, `/internal/patients/{id}/chart`, the tool
   endpoints, `/internal/labs/status`, `/internal/labs/patients/{id}/latest|trends|results`) for two seeded
   patients into `tests/fixtures/captured/`. Internal routes are not reachable through the gateway, so the
   script calls the services over `nephro-net` (for example `docker compose run --rm` a one-off container on
   that network) with the demo user's token. Strip nothing: the data is synthetic.
3. Contract tests run the ai-svc client models against both the hand-built and the captured fixtures.
4. An insights test against the captured fixtures for all ten seeded patients asserts HLD §18: 6 need attention
   (Aditya Singh, Ramesh Kulkarni, Fatima Sheikh, Kavita Joshi, Lakshmi Iyer, Priya Nair) and
   `rapid_decline = 4`. If the numbers differ, stop and show me the findings per patient.
5. `.env.example`: `LLM_PROVIDER=mock` by default, with a comment on how to switch to Groq
   (`LLM_PROVIDER=groq`, `LLM_API_KEY` or `LLM_API_KEY_FILE`). The README run section says the stack works with
   no key.
6. README: remove the "Dependencies on other services" paragraph once A1 is in (G14).

### A3. Cross-service hygiene (closes G8, G9, G10, part of G14; folders: `auth-svc/`, `patient-svc/`, `lab-svc/`, `ai-svc/`; one commit per service)

1. **patient-svc** `scripts/entrypoint.sh` and `Makefile run`: add `--h11-max-incomplete-event-size 32768`.
   Add an API test (or, if the in-process client cannot exercise h11, a documented manual check in the README)
   that `GET /patients?ids=` with 500 ids returns 200. Deviation row.
2. **All four services**: `FastAPI(..., redirect_slashes=False)`. Run each full suite. If a test relied on the
   redirect, fix the test's URL, not the setting. One deviation row per service (R14 of the gateway LLD).
3. **auth-svc seed** (`app/cli/seed_users.py` only): derive each demo user's id as
   `uuid.uuid5(UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10"), "user:" + email.lower())` (the namespace in
   `patient-svc/app/domain/seed_ids.py`). Keep the seed idempotent by email. Add a test that the seeded id equals
   that value. README: one line saying an existing dev database keeps its old random ids until the two demo users
   are deleted and reseeded; give the exact commands and do **not** run them.
4. **patient-svc README**: mark O1 resolved (lab-svc uses the same namespace; auth-svc after step 3).

### A4. Gateway Phase 8 and the AI header (closes G5, G6, G7; folders: `gateway/`, `.github/` only if I ask)

Follow `gateway/PHASES.md` Phase 8 and the gateway LLD §29, adapted to the repo standard (README D1, D3, D7, D8):
1. `make lock` in the pinned image → the three hash-locked files. If Docker is not running, stop.
2. `Dockerfile` copied from auth-svc's pattern (same digest `ARG PYTHON_IMAGE`, venv in `/opt/venv`,
   `--require-hashes`, the zlib1g upgrade step with its comment, uid 10001, HEALTHCHECK on `/health`).
3. `scripts/entrypoint.sh`: `exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
   --no-proxy-headers --no-server-header --h11-max-incomplete-event-size 32768 --timeout-graceful-shutdown 10`.
4. `docker-compose.yml`: external `nephro-net`, container name `gateway`, publishes
   `${GATEWAY_PORT:-8080}:8000`, `mem_limit: 256m`, `read_only`, `tmpfs /tmp`, `stop_grace_period: 15s`,
   `AUTH_SVC_URL`, `PATIENT_SVC_URL`, `LAB_SVC_URL`, `AI_SVC_URL` all set to `http://<svc>:8000`,
   `DOCS_ENABLED: "true"`. `docker-compose.prod.yml` per README D3. `.env.example`: `AI_SVC_URL=http://ai-svc:8000`.
5. Makefile recipes for `build up down logs smoke`. `setup/network.sh` (idempotent) and `setup/smoke-test.sh`
   (Git Bash on Windows: `mktemp` for every temp file, `$PY` for JSON). Smoke checks: health, ready, preflight
   from `http://localhost:4200` (204) and from a foreign origin (403), login with the demo user (cookie
   received), `/api/auth/me` with and without a token, garbage token 401, refresh with the cookie, internal
   route 404, raw traversal 400, encoded traversal 400, unknown prefix 404, and **200** for
   `GET /api/patients`, `GET /api/labs/tests`, `GET /api/insights/dashboard`, then logout and refresh-after-logout
   401.
6. **X-Mock-Scenario (G7):** forward `x-mock-scenario` **only** when the gateway's `ENVIRONMENT` is not
   `production` **and** the route's upstream is `ai`. In production it is dropped like any other unknown header.
   Add it to the CORS allowed request headers only outside production. Unit tests for both environments and for a
   non-ai route. Deviation row.
7. README: status section with the smoke output summary.

### A5. Whole-stack run from the root (closes G11, G12, G13, rest of G14; folders: repo root files, every service's `README.md` status section)

1. Root `docker-compose.yml` that uses Compose `include:` for `auth-svc/docker-compose.yml`,
   `patient-svc/docker-compose.yml`, `lab-svc/docker-compose.yml`, `ai-svc/docker-compose.yml`,
   `gateway/docker-compose.yml`. Each included file keeps resolving its own `.env` and secrets relative to its
   folder. The frontend stays in `frontend/compose.yaml` (it is a dev server with its own rules).
   Check the installed Compose version supports `include` (v2.20+); if not, stop and tell me.
2. Root `Makefile`: `network` (create `nephro-net` if missing, attach `graphgpt-postgres` with alias
   `postgres` only if not attached), `init-dbs` (prints the four `make init-db` commands and asks for
   confirmation; never runs them unattended), `keys` (auth-svc), `migrate` (auth-svc migrate job; the others
   migrate on start), `seed` (auth demo users, patients, labs, in that order), `up`, `down`, `logs`, `ps`,
   `smoke` (gateway smoke), `test` (each service's tests in turn, stops on the first failure).
3. Root `.env.example`: one section per service listing only the variables the root compose needs, each
   pointing to that service's own `.env.example` for the rest. No real secrets.
4. Root `README.md` (the submission README): what the system is (two paragraphs), architecture diagram (link to
   `docs/HLD.md` §3 or a Mermaid copy), prerequisites, first-time setup step by step (network, databases, keys,
   `.env` files, migrate, seed), `make up`, opening `http://localhost:4200`, demo accounts, how AI runs with the
   mock provider and how to switch to Groq, where each service's API docs live (`<svc>/docs/api/...` and the
   gateway's dev `/docs` at `http://localhost:8080/docs`), how to run every test suite, the synthetic-data
   statement, known limitations (link each service's deviations table). Keep it factual and short per section.
5. Build and start everything once: `make up`, then `docker compose ps` must show every container healthy, then
   `make smoke` all PASS. Paste both outputs. Fix what fails inside the right service, one commit each.
6. Update each service README's status / open items to what is now true.

---

## 5. Part B: frontend phases (folder: `frontend/` only)

### Architecture you build (applies to every frontend phase)

```
src/app/core/
  api/
    endpoints.ts          every path, built from one API_BASE ('/api'); no path string anywhere else
    api-error.ts          ApiError {status, code, message, details, requestId, retryAfterS}; parse the envelope;
                          status 0 → code 'NETWORK_ERROR'
    remote.ts             type Remote<T> = {state:'idle'} | {state:'loading'} | {state:'ok', data:T}
                          | {state:'empty'} | {state:'error', error:ApiError}; helpers to map an Observable
    dto/                  one file per service: auth.dto.ts, patient.dto.ts, lab.dto.ts, ai.dto.ts
                          exact OpenAPI field names (snake_case), readonly
    mappers/              dto → view model, one file per service; pure, unit-tested
  auth/
    auth.service.ts       signals: user, accessToken (memory only), status; login, signup, logout,
                          restoreSession, refresh (single-flight), changePassword (no UI required)
    auth.guard.ts         authGuard, guestGuard (functional)
    auth.interceptor.ts   bearer on API_BASE requests only; withCredentials on /api/auth/*
    refresh.interceptor.ts on 401 TOKEN_EXPIRED / UNAUTHENTICATED from a non-auth route: single-flight refresh,
                          retry once; on refresh failure clear session, go to /login?returnUrl=
    error.interceptor.ts  envelope → ApiError; no toast here (screens decide)
  data/                   feature APIs: patients.api.ts, encounters.api.ts, labs.api.ts, insights.api.ts,
                          ai.api.ts (each returns typed Observables of view models)
```

- Components never call `HttpClient`; they call a feature API.
- View models may keep the names the templates use today, so templates change little. Mapping happens only in
  `core/api/mappers/`.
- The browser computes **only**: the lab form's live preview (catalog from the server, ADR-019), the
  established-stage-vs-eGFR-category mismatch chip (both values from the server), display formatting, and form
  validation. Everything else (flags, categories, trends, gaps, attention, KPIs, MRN, problem-list linkage, age)
  comes from a service.
- Value maps you need (put them in the mappers, with tests):

| View model (today) | API |
|---|---|
| `allergyStatus: 'unknown' \| 'nka' \| 'has'` | `allergy_status: 'unknown' \| 'nka' \| 'has_allergies'` |
| med `route` label (`Oral`, `SC`, …) | `route` code `oral, sc, iv, topical, inhaled, other` |
| med `freq`, `start`, `end` | `frequency`, `start_date`, `end_date` |
| condition `icd10, desc, onset, isPrimary` | `icd10_code, description, onset_date, is_primary` |
| encounter `date, type, clinician, cc, exam, followUp` | `encounter_date, encounter_type, clinician_name, chief_complaint, examination_notes, follow_up_date` |
| vitals `sys, dia, hr, temp, wt` | `systolic_bp, diastolic_bp, heart_rate, temperature_c, weight_kg` |
| encounter dx `icd, desc, prob, condId` | `icd10_code, description, add_to_problem_list, condition_id` (+ optional `category`) |
| patient `first, last, dob, pmh, fh, sh, ckd` | `first_name, last_name, date_of_birth, past_medical_history, family_history, social_history, established_ckd_stage` |
| lab result `test, refLow, refHigh, valueOriginal, unitOriginal, collectedAt` | `test_code, ref_low, ref_high, value_original, unit_original, collected_at` |
| `clinician_name: null` | display "Not documented" (CLAUDE.md §6) |

- Error display rules:

| Code | UI |
|---|---|
| `VERSION_CONFLICT` (409) | "This record was changed by someone else." with a Reload action (HLD §15.2) |
| `ENCOUNTER_FINAL` (409) | toast with the server message; refresh the encounter |
| `VALIDATION_ERROR` (422) | map `details[].field` (dotted / indexed paths like `results[1].unit`, `vitals.systolic_bp`) onto the form controls; unknown fields go to a form-level alert |
| `RATE_LIMITED`, `ACCOUNT_LOCKED`, `AI_QUOTA_EXCEEDED` (429) | message with the `Retry-After` seconds or minutes |
| `UPSTREAM_*`, `GATEWAY_BUSY`, `SERVICE_BUSY` (502/503/504) | that panel's error state with Retry; other panels keep working |
| `UPSTREAM_NOT_DEPLOYED` (503) | "This part of the system is not available yet." in the panel |
| any error | show `request_id` small and copyable for support, never the internal code |

### B1. Gateway connection and HTTP foundation (closes F3, F10, part of F1)

1. Dev-server proxy (decisions D3): `frontend/proxy.conf.mjs` sends `/api` to
   `process.env.GATEWAY_URL ?? 'http://host.docker.internal:8080'`, `changeOrigin: true`, no path rewrite.
   Register it in `angular.json` `serve.options.proxyConfig`. In `compose.yaml` add to `web`:
   `extra_hosts: ['host.docker.internal:host-gateway']` and `GATEWAY_URL` passthrough. The `Origin` header must
   still reach the gateway as `http://localhost:4200` (auth-svc checks it on refresh/logout); verify it.
2. Environments: dev and prod `apiBaseUrl: '/api'`. Remove `useMocks` from both environments and every reader.
   Keep `aiRequestTimeoutMs` only if you use it (B9); otherwise remove it.
3. `app.config.ts`: `provideHttpClient(withFetch(), withInterceptors([authInterceptor, refreshInterceptor,
   errorInterceptor]))`, `provideAppInitializer(() => inject(AuthService).restoreSession())`.
4. Build `core/api/` (endpoints, ApiError, Remote, all four DTO files from the OpenAPI documents, mappers with
   unit tests for every row of the value-map table).
5. Tests: ApiError parsing (envelope, non-JSON body, status 0), the `Remote` helpers.
6. Check with the running stack: from the browser at `http://localhost:4200`, `fetch('/api/auth/me')` returns
   `401` with the gateway envelope (proves the proxy path). Note it in the report.

### B2. Sign-in, sign-up and the session (closes F2)

1. Login and sign-up screens built **from the reference HTML** (`reference/emr-ui.html` lines 713–750, and
   `ui-inventory.md`): same fields, copy, password-rule checklist and errors. Reuse the shared UI components.
2. `AuthService` exactly as `decisions.md` D3: access token in a signal (never Web Storage), refresh at app start,
   single-flight refresh on 401 (concurrent requests wait on one refresh), retry the original request once,
   `409 REFRESH_RACE` → short random delay then one retry, `401 REFRESH_REUSED` → sign out with the server's
   message, logout → `POST /api/auth/logout` then clear memory.
3. Before `POST /api/ai/patients/{id}/summary`, refresh first if the token expires within 60 s (ai-svc rejects
   tokens with < 30 s left).
4. Guards: every app route behind `authGuard` (redirect to `/login?returnUrl=`), `/login` and `/signup` behind
   `guestGuard`. Only same-app `returnUrl` values are honoured (no open redirect).
5. Header user chip and menu from `user()` (`full_name`, role label "Nephrologist" for `clinician`); delete
   `layout/placeholder-user.ts` and every import of it. Sign out works.
6. Sign-up: live password checklist (length ≥ 10, letter and digit, not common), server `422` rule codes mapped to
   the checklist, `409 EMAIL_TAKEN` on the email field, `403 SIGNUP_DISABLED` as a page alert.
7. Tests: single-flight (three concurrent 401s cause exactly one refresh), retry once only, refresh failure clears
   the session and redirects, `REFRESH_RACE` retry, guards, `returnUrl` validation, interceptor attaches the token
   only to `/api` and `withCredentials` only to `/api/auth/*`.

### B3. Dashboard (closes part of F4, F9)

Three calls in parallel, each panel with its own `Remote` state (HLD §3.2b): `GET /insights/dashboard`,
`GET /encounters?status=draft&limit=10`, `GET /encounters?upcoming_followups=true&limit=5`. KPIs come from
`kpis` plus the drafts `total`. Attention rows use `reasons[] {severity, text}`; abnormal results and eGFR
distribution come from the response. A manual refresh sends `Cache-Control: no-cache`. Greeting uses the signed-in
user's name. Remove the client aggregation from `dashboard-page.ts`. Test: one panel failing leaves the other two
rendered.

### B4. Patient list and register patient (closes F6, part of F4)

1. Server-side `q`, `sex`, `stage` (including `none`), `sort` (`name, mrn, age, dx, visit`), `dir`, `page`,
   `size=8`. The URL query string is the source of truth (bookmarkable, back button works); search debounced
   300 ms; the global search navigates to `/patients?q=`.
2. Remove sorting by eGFR: the column header is not sortable (ADR-020). Keep the column.
3. eGFR cell and sparkline: after the page loads, one `GET /labs/summary?patient_ids=` for the visible ids; cells
   show a skeleton until it returns; `has_results: false` → "No results".
4. "Needs attention" filter: `GET /insights/worklist?attention=true` → ids → `GET /patients?ids=…&<other filters>`.
5. KPI strip: total from the list response, the rest from `GET /insights/dashboard` `kpis` and the drafts total
   (reuse the calls; do not add a new endpoint).
6. Register patient modal → `POST /patients` (allergy status only `unknown` or `nka`), 422 mapping, then navigate
   to the new chart.

### B5. Patient shell, Overview, Conditions, Medications and allergies (part of F4, F7, F9)

1. Shell: `GET /patients/{id}` (header, `counts` for tab pills, `allergy_summary` chip, `version`) and
   `GET /labs/patients/{id}/latest` (eGFR category chip; mismatch chip = established stage ≠ category). A 404
   shows the not-found state.
2. Overview: kidney panel from `GET /labs/patients/{id}/trends?tests=CREAT,EGFR`; gap alert from
   `GET /insights/patients/{id}/gaps`; recent encounters from the encounters list; edit demographics with
   `PATCH` + `version` and the 409 flow.
3. Conditions: list, add, set primary (`PATCH {is_primary: true}`; show "Primary cleared" when the response says
   so), resolve and reactivate, established stage via `PATCH /patients/{id}` with the current `version`.
4. Medications and allergies: active vs all, add, discontinue with confirmation (`{action: "discontinue"}`), add
   and remove allergy (keep `patient_version` in the shell's state from the response), "No known allergies" via
   `PATCH` with `version`; `409 ALLERGIES_PRESENT` and `DUPLICATE_ALLERGY` shown on the form.
5. After every write, refresh exactly the data that changed (shell header, counts, the tab list), not the whole page.

### B6. Encounters (part of F4, F7)

List with paging, view modal for final encounters (`GET …/{eid}`), create as draft or final, edit a draft with
`PATCH` + `version` (`vitals` and `diagnoses` replace the whole set when sent), finalize (`POST …/finalize`
with `version`, after the confirm dialog), delete a draft. The toast on finalize uses
`problem_list_changes.added`. Vitals limits from `decisions.md` D1 stay client-side (the server's limits are
wider). `clinician_name` null → "Not documented". Remove `saveEncounter` and the problem-list logic from the
client.

### B7. Labs tab and the add-lab-report modal (closes F8)

1. Latest grid and CKD grid from `/latest`; date range (6 months, 1 year, 2 years, all) maps to `from` on
   `/trends`; stage bands from `stage_bands`, the creatinine band from `reference`; chips from `stats`
   (`insufficient_data` → "Insufficient data (needs 3+ results)").
2. History table: `test`, `flag=abnormal`, paging (`size=10`), "Entered as" column from `value_original` /
   `unit_original` when they differ.
3. Lab modal: load `GET /labs/tests?sex=<patient sex>&age=<age>` once per patient; the live preview converts and
   flags with the server catalog (factors are decimal **strings**: use exact decimal arithmetic with half-up
   rounding to `decimals + 1`; if you add a decimal library, justify it). `POST` the report; show
   `summary.n` and `summary.abnormal` in the toast; map 422 `results[i].field` errors to the right row.
4. Shared vectors (ADR-019): mount `../lab-svc/tests/vectors` read-only into the `web` container
   (`compose.yaml`), and add a Vitest suite that runs every case in `lab_cases.json` through the preview
   functions. It must fail, not skip, when the file is missing. Delete the hard-coded ranges and factors from
   `core/clinical/lab-tests.ts` (keep only display helpers and types).

### B8. AI summary tab (closes F5)

1. Generate / regenerate: `POST …/summary` (regenerate adds `force=true`), then poll
   `GET /api/ai/summaries/{id}` every `poll_after_ms` with `timer` + `switchMap` until a terminal status; stop on
   route leave and on component destroy. A `deduplicated: true` start joins the running job.
2. Stepper from `progress[] {key, label, state, ms, note}`; cache hit (`cached: true`) shows "Nothing has changed
   since the last summary, so the saved one is shown."
3. Render the three provenance panels exactly as the reference: "Calculated from the chart" (`facts`), "Checked
   by rules, not by AI" (`gaps.findings`), "AI-generated narrative" (`ai.content`) with the disclaimer. The
   disclaimer text is the frontend constant (decisions D2); assert in a test that it equals ai-svc's `disclaimer`
   string from `ai-svc/docs/api/examples/summary-completed.json`.
4. Source chips from `sources` (`label`, `tab`, `target_id`): clicking opens the right tab or the encounter
   dialog. `validation` drives "N of N sources found", "Safety check: passed", "Corrected once automatically".
5. "What the AI was given" panel: `GET …?include=context`, collapsed by default.
6. History: `GET /ai/patients/{id}/summaries`; opening one shows it without regenerating.
7. Degraded: facts and findings shown, narrative replaced by `error_message`. Failed: `error_message` and a
   Try again button. `429 AI_QUOTA_EXCEEDED`: the daily-limit message with `Retry-After`.
8. Demo options (dev only): the existing select sends `X-Mock-Scenario` with the scenario values listed in
   section 2. Hidden and never sent in production builds (`environment.production`). Map the five existing
   options to: `normal` → `success`, `invalid` ("invalid output once, auto-repair") → `invalid_then_valid`,
   `timeout` → `timeout`, `ratelimit` → `rate_limited`, `upstream` → `upstream_down`. You may add the other
   scenarios (`invalid_twice`, `unsafe_then_safe`, `bad_refs`, `tool_roundtrip`) with plain labels.
9. Copy narrative keeps the disclaimer in the copied text.
10. Delete the simulation in `core/data/ai.service.ts`.

### B9. Remove the fake backend and finish quality (closes F1, F4, F9, F10)

1. Delete `core/data/db.service.ts`, `seed.ts`, `analysis.ts` (move any pure display helper that is still used
   into `shared/utils` with tests) and the localStorage key. `grep -r "DbService\|seedDb\|gapEngine\|localStorage"
   src` must find nothing except per-viewer UI conveniences you justify.
2. Component tests: guards, interceptors, every mapper, `Remote` rendering of loading / empty / error / ok on the
   dashboard, list and AI tab, polling stops on terminal status and on destroy, 409 Reload flow, 422 mapping on the
   encounter and lab forms.
3. Visual parity: run the parity harness against the running stack. Data now comes from the seeds, so some text
   differs from the reference HTML; record per-screen differences in `docs/ui-inventory.md` "Conflicts" and fix
   anything that is layout, not data.
4. Tick `docs/build-checklist.md` honestly (`❌` with a reason where something is not done).

### B10. End-to-end and submission material (closes F11)

1. With the whole stack running (`make up` at the root, frontend `docker compose up`), walk the flow:
   sign in → dashboard → global search → open Ramesh Kulkarni → add an encounter (draft, then finalize with
   "add to problem list") → add a lab report with a µmol/L creatinine → see the trend update → generate an AI
   summary (mock) → open a source chip → sign out → reload shows the sign-in page. Then sign in again and reload
   any page: the session survives (silent refresh).
2. Automate that flow as one Playwright test under `frontend/e2e/flow/` (runs in the existing Playwright image,
   against `http://host.docker.internal:4200`), seeded data only.
3. Screenshots into `docs/screenshots/` (root): sign-in, dashboard, patient list with sparklines and filters,
   Overview with the kidney panel, conditions with the stage mismatch, encounter form, lab table with flags and
   the add-report preview, trend charts, AI summary (running, completed, degraded, failed), a source chip opening
   a record. Link them from the root README.
4. Final frontend README: how it talks to the gateway (proxy), auth model, where API types live, how to run the
   flow test.

---

## 6. Final report (after the last phase)

- Gap register (section 3) with each ID marked closed, partly closed or deferred, and the commit that closed it.
- Test counts per service, gateway and frontend; lint and build status.
- `docker compose ps` output and the full `make smoke` output.
- The Playwright flow result.
- Every deviation row you added, per README.
- The list of commits on `main` created in this task.
- Follow-ups you did not do, with a reason each (at least: CI workflows for patient-svc, lab-svc, ai-svc and the
  gateway, which were deferred by decision; ai-svc's `APP_ENV` naming vs `ENVIRONMENT` elsewhere; the list's
  sort-by-visit latency in `patient-svc/README.md` O2).