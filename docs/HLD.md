# Nephrology EMR — High-Level Design (HLD) · v2

**Project:** General Nephrology EMR: Patient Management & AI Clinical Assistant
**Stack:** Angular · Python FastAPI microservices · PostgreSQL (Docker) · custom API Gateway · LLM via provider adapter
**Data:** Synthetic patients only. No real PHI anywhere in this repository.
**Version:** v2. Aligned feature-for-feature with the product prototype `nephrocare-emr-platform.html`. Section 0 lists what changed from v1 and why.

## Implementation differences

The design below was written before the code. A reviewer comparing the two will meet these differences first. Each links to
the deviation row that explains it; the service READMEs list the rest.

| Design says | The build does | Explained in |
|---|---|---|
| `services/`, `libs/common` and `infra/` folders (§17) | One self-contained folder per service at the repository root; no shared library. Shared pieces such as the error envelope and the JWKS cache are copied and kept identical by tests | [auth-svc D3](../auth-svc/README.md#design-and-deviations) |
| Databases `auth_db`, `patient_db`, `lab_db`, `ai_db` | `nephro_auth_db`, `nephro_patient_db`, `nephro_lab_db`, `nephro_ai_db` on the existing Postgres container (host port 5433, network alias `postgres`) | [auth-svc D1](../auth-svc/README.md#design-and-deviations), [patient-svc D1 to D3](../patient-svc/README.md#design-and-deviations), [lab-svc](../lab-svc/README.md#design-and-deviations) |
| One database role per service (§5.1) | auth-svc has two: `auth_migrator` owns the schema and `auth_app` runs the service with no schema rights | [auth-svc D22](../auth-svc/README.md#design-and-deviations) |
| Chart.js through `ng2-charts` with the annotation plugin (§15, ADR-014) | Chart.js used directly, with a small custom plugin for the reference band and the eGFR stage lines. The list sparkline is inline SVG | [frontend decisions](../frontend/docs/decisions.md#charting-library) |
| Clinician name from a JWT claim | Tokens carry no personal data; patient-svc reads the name from auth-svc `/auth/me` and stores it as nullable | [patient-svc D6](../patient-svc/README.md#design-and-deviations) |
| Patient list sorted by lateral joins | `patients.last_visit` and `patients.primary_dx_sort` keep the two sorts fast | [patient-svc D11](../patient-svc/README.md#design-and-deviations) |
| A supplied reference-ranges file | No file was supplied; the prototype's ranges are loaded as a placeholder | [lab-svc](../lab-svc/README.md#design-and-deviations), [DATABASE.md](DATABASE.md#reference-ranges) |
| Gateway Swagger with an Authorize button; no environment concept | A production start-up guard, a dev-only `X-Mock-Scenario` pass-through to ai-svc, and the Swagger CDN assets | [gateway D3, D15, D17](../gateway/README.md#design-and-deviations) |
| LLM providers `mock`, `gemini`, `groq`, `ollama` | `mock` and `groq` are built | [ai-svc D2](../ai-svc/README.md#design-and-deviations) |
| Seed ids not specified | UUIDv5 ids from one namespace, shared by the three seeding services | [DATABASE.md](DATABASE.md#synthetic-data), [auth-svc D28](../auth-svc/README.md#design-and-deviations) |


---

## Table of Contents

0. [What changed in v2](#0-what-changed-in-v2)
1. [Goals, scope and non-goals](#1-goals-scope-and-non-goals)
2. [Requirements traceability (PS → design)](#2-requirements-traceability-ps--design)
3. [Architecture overview](#3-architecture-overview)
4. [Service catalog and boundaries](#4-service-catalog-and-boundaries)
5. [Data architecture](#5-data-architecture)
6. [Clinical logic (CKD, flags, trends)](#6-clinical-logic-ckd-flags-trends)
7. [Authentication and security](#7-authentication-and-security)
8. [API Gateway](#8-api-gateway)
9. [Service-to-service communication](#9-service-to-service-communication)
10. [AI service design (incl. tool calling)](#10-ai-service-design-including-tool-calling)
11. [API surface](#11-api-surface)
12. [Cross-cutting concerns](#12-cross-cutting-concerns)
13. [Scalability and production readiness](#13-scalability-and-production-readiness)
14. [Design patterns used and why](#14-design-patterns-used-and-why)
15. [Frontend architecture (Angular)](#15-frontend-architecture-angular)
16. [Testing strategy](#16-testing-strategy)
17. [Deployment, repo layout and local setup](#17-deployment-repo-layout-and-local-setup)
18. [Synthetic data plan](#18-synthetic-data-plan)
19. [Decision log (ADRs)](#19-decision-log-adrs)
20. [Known simplifications and future work](#20-known-simplifications-and-future-work)
21. [Submission checklist](#21-submission-checklist)

---

## 0. What changed in v2

v1 designed the PS requirements. The prototype then added product features that v1 did not cover, and one v1 detail was wrong. v2 closes every gap. Each row names the prototype behavior that forced the change.

| # | Prototype behavior | v1 gap | v2 resolution | Where |
|---|---|---|---|---|
| 1 | **Dashboard**: KPIs, patients needing attention, abnormal results to review, eGFR category chart, upcoming follow-ups, draft encounters | No endpoint and no owner | Deterministic **insights** endpoints in ai-svc plus two cross-patient encounter queries in patient-svc | §10.12, §11, §15.4 |
| 2 | **Patient list** shows latest eGFR, eGFR sparkline, "Needs attention" filter and KPI strip | v1 said the list is one SQL query in patient-svc, but these values live in lab-svc and need chart rules | Batch lab summary endpoint, worklist ids as a list filter, and a lab-owned read model | §5.4, §5.6, §10.12 |
| 3 | **Record gaps** shown on Overview and on the dashboard without generating an AI summary | Gap rules ran only inside a summary request | `GET /insights/patients/{id}/gaps`, no LLM involved | §10.5, §10.12 |
| 4 | **AI progress stepper** with seven live steps | v1 had one blocking request | `POST` always returns `202` and the UI polls; progress is persisted on the summary row; a cache hit resolves through the same path | §10.3, §10.10 |
| 5 | **Source chips** with readable labels that open the record | Response carried bare ids such as `lab:EGFR:2026-10-21` | Server hydrates a `sources` map with label, type and target | §10.9 |
| 6 | "Corrected once", "13 of 13 sources found", "Safety check passed", "What the AI was given" | Stored but not returned | `validation` block and `context` returned on the detail endpoint | §10.9 |
| 7 | **Delete a draft encounter** | No route | `DELETE /patients/{id}/encounters/{eid}` for drafts only, soft delete | §5.3, §11.2 |
| 8 | **Abnormal-only filter** and "entered as" original unit in lab history | No `flag` filter, original unit not in the response contract | `flag=abnormal` filter, `value_original` and `unit_original` returned | §11.3 |
| 9 | **Live flag and unit conversion** while typing a lab value | Not specified who computes it | Client preview from the test catalog, server stays authoritative, shared test vectors prevent drift | §15.2, §16, ADR-019 |
| 10 | **Single clinician user**, no admin screens | v1 had an admin role, admin endpoints and a `roleGuard` | One role, `clinician`. Admin removed | §7, ADR-018 |
| 11 | **Established CKD stage dropdown** G1, G2, G3a, G3b, G4, G5 | v1 ER diagram said `G1..G5` (**an error**: G3a and G3b are required) | Corrected everywhere | §5.3, §6.1 |
| 12 | Trend chips **Worsening, Stable, Improving** | Thresholds were "configuration" with no values | Defaults defined: eGFR ±2 per year, creatinine ±0.1 mg/dL per year | §6.3 |
| 13 | List sort by name, ID, age, primary diagnosis, last visit | Not stated | Defined. **Latest eGFR is deliberately not a server-side sort** because it lives in another service | §5.6, ADR-020 |
| 14 | Synthetic patients with named scenarios | Generic plan | Ten patients mapped to scenarios, so every screen and rule has a fixture | §18 |

---

## 1. Goals, scope and non-goals

### Goals
- A working outpatient nephrology EMR: patient management, encounters, lab monitoring with CKD classification, and an AI clinical summary.
- Clean service boundaries, enforced data ownership, and a design that can be scaled horizontally without redesign.
- AI that is **safe by construction**: deterministic facts are computed in code, the LLM only writes narrative, and every AI output is validated, labeled and auditable.

### Non-goals (deliberate)
- No message broker, event sourcing, CQRS, sagas, service mesh or Kubernetes manifests. No workflow in this system needs them (see [ADR-005](#adr-005-no-saga-no-broker)).
- No real HL7/FHIR integration, billing, scheduling or e-prescribing. FHIR-friendly naming is used where cheap.
- No diagnosis or treatment recommendations from AI. Ever.
- No admin console. The product has one user type, the nephrologist (§7, ADR-018).

### Guiding principles
1. **Boundaries follow data ownership and consistency**, not screens or tables.
2. **Every write is a single local ACID transaction.** Cross-service calls are reads only.
3. **Deterministic first, generative second.** Anything computable is computed in code.
4. **LLM output is untrusted input.** It is schema-validated, grounded and labeled.
5. **Add infrastructure only when a requirement demands it.**
6. **The UI is the contract.** Every screen and button in the prototype maps to a documented endpoint (§15.4).

---

## 2. Requirements traceability (PS → design)

Nothing in the PS is left unmapped. "Where" points to the section that designs it.

### Functional

| PS requirement | Service / component | Where |
|---|---|---|
| **A. Patient listing** (ID, name, age, gender, primary diagnosis) | patient-svc `GET /patients`; age computed from DOB; primary dx from `patient_conditions.is_primary` | §4.2, §5.3 |
| Search by name or patient ID | `GET /patients?q=` — MRN exact/prefix + `pg_trgm` name search | §5.3, §11 |
| Demographics and medical history | `patients` table (PMH, family, social history) | §5.3 |
| Comorbidities and established diagnoses | `patient_conditions` (`category`, `status`, `is_primary`) + `established_ckd_stage` | §5.3 |
| Current medications and allergies | `medications`, `allergies`, `patients.allergy_status` | §5.3 |
| Previous clinical encounters | `GET /patients/{id}/encounters` | §4.2 |
| **B. Create encounter** | patient-svc `POST /patients/{id}/encounters` | §4.2 |
| Visit date, details | `encounters.encounter_date`, `type` | §5.3 |
| Vitals: BP, HR, temp, weight | `encounter_vitals` (1:1, CHECK constraints) | §5.3 |
| Chief complaint, symptoms, exam notes | `encounters` columns | §5.3 |
| Assessment and diagnoses | `encounters.assessment`, `encounter_diagnoses` | §5.3 |
| Treatment / follow-up plan | `encounters.plan`, `follow_up_date` | §5.3 |
| Save and retrieve previous encounters | draft/final lifecycle + list/get endpoints | §4.2 |
| **C. Lab parameters** (Creatinine, eGFR, BUN, K, Hb, Ca, Phos, UACR) | lab-svc `lab_tests` seeded with all 8 | §5.4 |
| Add results with dates and units | `lab_reports` + `lab_results`, unit validation and conversion | §4.3, §5.4 |
| View historical results | `GET /labs/patients/{id}/results` | §11 |
| Visualize Creatinine and eGFR trends | `GET /labs/patients/{id}/trends` + Chart.js in Angular | §6.3, §15 |
| Highlight abnormal values (supplied ranges) | `lab_reference_ranges` seeded from the supplied file; flag stored per result | §5.4, §6.2 |
| Display established CKD stage / classify eGFR | established stage (patient-svc) **and** computed eGFR category (lab-svc), both shown | §6.1 |
| **D. AI summary** (6 outputs) | ai-svc pipeline | §10 |
| 1. Nephrology history summary | LLM narrative, grounded | §10.4 |
| 2. Conditions and comorbidities | LLM narrative from structured conditions | §10.4 |
| 3. Creatinine/eGFR trends | **deterministic** stats from lab-svc; LLM only narrates | §10.3 |
| 4. Abnormal findings | **deterministic** flags from lab-svc | §10.3 |
| 5. Missing / inconsistent information | **deterministic** rule engine (`gaps/`) | §10.5 |
| 6. Follow-up considerations | LLM, for clinician review, no prescribing | §10.4, §10.7 |
| LLM through backend service | ai-svc, provider adapter | §10.2 |
| Prepare context before calling LLM | Context Builder (+ minimization) | §10.3 |
| Handle missing info, no fabrication | `not_documented` handling, grounding checks | §10.6 |
| Error handling: invalid LLM response, API failure | validate → repair retry → degrade gracefully | §10.8 |
| Distinguish AI from patient records | `provenance` field + visually separate UI panel | §10.9, §15 |
| Clinical review disclaimer | server-injected fixed disclaimer, not LLM-generated | §10.9 |
| No independent diagnosis / prescribing | prompt rules + output safety lint + schema without such fields | §10.7 |

### Product features beyond the PS (from the prototype)

| Prototype feature | Service / component | Where |
|---|---|---|
| Dashboard KPIs (patients, need attention, critical results, rapid decline, drafts) | ai-svc `insights/` `GET /insights/dashboard` + patient-svc draft count | §10.12 |
| Needs-attention list with reasons | ai-svc worklist (critical result, rapid decline, high-severity gap) | §10.12 |
| Patients by eGFR category chart | lab-svc read model aggregated by ai-svc | §5.4, §10.12 |
| Abnormal results to review | lab-svc latest results, composed by ai-svc | §10.12 |
| Upcoming follow-ups and draft encounters | patient-svc `GET /encounters?...` | §11.2 |
| Patient list: latest eGFR and sparkline | lab-svc `GET /labs/summary?patient_ids=` | §5.6, §11.3 |
| Needs-attention filter on the list | worklist ids passed to `GET /patients?ids=` | §5.6 |
| Kidney function panel on Overview (eGFR and creatinine charts, CKD strip) | lab-svc `/trends` and `/latest` | §6, §15.4 |
| Gap alert on Overview | `GET /insights/patients/{id}/gaps` | §10.5 |
| Established CKD stage dropdown and mismatch warning | `PATCH /patients/{id}` + lab-svc category | §6.1 |
| Encounter form: symptoms, diagnoses added to problem list, draft or final | patient-svc, one transaction | §5.3 |
| Live flag and unit conversion in lab form | Test catalog `GET /labs/tests` + client preview | §15.2 |
| AI progress stepper | `202` + polling, persisted `progress` | §10.3 |
| AI history, regenerate, copy narrative | `GET /ai/patients/{id}/summaries`, `?force=true` | §11.4 |
| Single-user session (sign in, sign out) | auth-svc, role `clinician` | §7 |

### Technical and engineering

| PS expectation | Design response | Where |
|---|---|---|
| Angular, TS, HTML, CSS | Angular standalone components + signals | §15 |
| Charting library | Chart.js via `ng2-charts` + annotation plugin for reference bands | §15 |
| REST APIs, clean design | Resource-oriented REST, OpenAPI per service | §11 |
| Any backend tech | Python FastAPI (async) | §4 |
| SQL database | PostgreSQL in Docker, database-per-service (one instance, four databases) | §5 |
| LLM API, free tier or mock | Provider adapter: Gemini / Groq / Ollama / **Mock** | §10.2 |
| AI coding tools | Encouraged; architecture is documented so each choice can be explained | §19 |
| Reusable Angular components | Shared component library | §15 |
| Separation of concerns | router → service → repository layering | §14 |
| Error handling, input validation | Pydantic + DB CHECKs + uniform error envelope | §12 |
| Meaningful DB relationships | FKs inside each database; UUID refs across services | §5 |
| Basic testing | Unit tests on clinical logic + API tests per service + shared test vectors for client and server | §16 |
| Setup and execution instructions | README + `docker compose up` | §17 |
| Schema and synthetic data | Alembic migrations + seed scripts | §5, §18 |
| API documentation | FastAPI OpenAPI exported to `docs/api/` + endpoint tables | §11 |
| Architecture and AI explanation | This document | all |
| Screenshots / recording | Listed in checklist | §21 |

---

## 3. Architecture overview

### 3.1 System context and containers

```mermaid
flowchart TB
    User([Nephrologist]) --> SPA[Angular SPA]
    SPA -- "HTTPS · Bearer JWT · refresh cookie" --> GW

    GW["API Gateway (custom)<br/>routing · JWT verify (JWKS) · CORS · rate limit<br/>request-id · timeouts · error envelope · blocks /internal"]

    subgraph PRIV["Private Docker network (no published ports except gateway)"]
        AUTH["auth-svc<br/>users · sessions · JWKS"]
        PAT["patient-svc<br/>patients · conditions · meds<br/>allergies · encounters"]
        LAB["lab-svc<br/>results · ranges · flags · CKD category<br/>trends · patient_lab_status read model"]
        AI["ai-svc<br/>insights (rules, worklist, dashboard)<br/>summary (context · tools · LLM adapter · validator)"]
    end

    GW --> AUTH
    GW --> PAT
    GW --> LAB
    GW --> AI

    LAB -- "GET /internal/patients/{id}/basic" --> PAT
    AI -- "chart reads, bulk chart export, tools" --> PAT
    AI -- "lab reads, bulk status, tools" --> LAB

    subgraph PG["PostgreSQL container (one instance)"]
        S1[("auth_db<br/>role auth_svc")]
        S2[("patient_db<br/>role patient_svc")]
        S3[("lab_db<br/>role lab_svc")]
        S4[("ai_db<br/>role ai_svc")]
    end

    AUTH --- S1
    PAT --- S2
    LAB --- S3
    AI --- S4

    AI -- "HTTPS (timeout, retry, breaker)" --> LLM[["LLM provider<br/>Gemini / Groq / Ollama / Mock"]]
```

### 3.2 Request path (typical read)

```mermaid
sequenceDiagram
    autonumber
    participant U as Angular
    participant G as Gateway
    participant P as patient-svc
    participant D as Postgres (patient_db)
    U->>G: GET /api/patients?q=ravi (Bearer JWT)
    G->>G: verify JWT (cached JWKS), rate-limit, add X-Request-ID
    G->>P: GET /patients?q=ravi (JWT + X-Request-ID forwarded)
    P->>P: verify JWT again, check role
    P->>D: SELECT ... JOIN patient_conditions (is_primary)
    D-->>P: rows
    P-->>G: 200 {items, page, size, total}
    G-->>U: 200 (+ X-Request-ID)
```

### 3.2b Composed screens (list and dashboard)

Two screens need data from more than one service. The Angular app composes them with parallel calls; no service queries another service's database.

```mermaid
sequenceDiagram
    autonumber
    participant U as Angular
    participant G as Gateway
    participant P as patient-svc
    participant L as lab-svc
    participant I as ai-svc (insights)
    Note over U: Patient list (page of 8)
    U->>G: GET /api/patients?q=&sort=&page=
    G->>P: forward
    P-->>U: 8 rows (id, mrn, name, age, sex, primary dx, stage, last visit)
    U->>G: GET /api/labs/summary?patient_ids=8 ids
    G->>L: forward
    L-->>U: latest eGFR + flag + sparkline points per patient
    Note over U: eGFR cells show a skeleton until this returns
    Note over U: Dashboard
    par three calls in parallel
        U->>G: GET /api/insights/dashboard
        G->>I: forward
        I->>P: GET /internal/patients/charts (bulk)
        I->>L: GET /internal/labs/status (bulk)
        I-->>U: kpis, attention, egfr distribution, abnormal results
    and
        U->>G: GET /api/encounters?status=draft
        G->>P: forward
        P-->>U: drafts with patient name
    and
        U->>G: GET /api/encounters?upcoming_followups=true
        G->>P: forward
        P-->>U: follow-ups with patient name
    end
```

Each panel renders as soon as its call returns. A failed call shows an error state in that panel only (§15.2).

### 3.3 Why these four services

| Service | Reason it exists as its own unit |
|---|---|
| **auth-svc** | Security boundary. Credentials and tokens must never share code, tables or blast radius with clinical data. |
| **patient-svc** | One consistency boundary: the patient chart. Patient + conditions + meds + allergies + encounters change together in ACID transactions. |
| **lab-svc** | Own domain rules (reference ranges, unit conversion, CKD classification, trend math), read-heavy access pattern, and in real life an external feed (analyzers/LIS). |
| **ai-svc** | Depends on a slow, flaky, rate-limited third party and must fail independently. Holds AI outputs in a separate store so they can never be confused with source records. It also hosts the **deterministic insights** (gap rules, worklist, dashboard) because it is the only service that already composes patient and lab data. Those endpoints never call the LLM, so they stay up when the LLM is down (ADR-016). |

> **Why patients and encounters are not split:** an encounter has no meaning without its patient; recording an encounter diagnosis and updating the problem list is one transaction. Splitting adds cross-service calls and compensation logic for zero benefit. Inside patient-svc they are **separate modules** (`patients/`, `encounters/`), so the seam exists if a real reason to split appears.

---

## 4. Service catalog and boundaries

### 4.1 auth-svc

| | |
|---|---|
| **Owns** | Identity, credentials, sessions, token signing keys |
| **Database / tables** | `auth_db`: `users`, `refresh_tokens` |
| **Exposes** | `/auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`, `/.well-known/jwks.json` |
| **Roles** | One: `clinician`. No admin role and no user-management API (ADR-018) |
| **Depends on** | Nothing |
| **Does NOT** | Know anything about patients, labs or AI |
| **Scaling** | Stateless; scale replicas. Password hashing (argon2) is CPU-bound — the main thing to size |

### 4.2 patient-svc

| | |
|---|---|
| **Owns** | The clinical chart |
| **Database / tables** | `patient_db`: `patients`, `patient_conditions`, `medications`, `allergies`, `encounters`, `encounter_vitals`, `encounter_diagnoses`, `audit_events` |
| **Modules** | `patients/`, `conditions/`, `medications/`, `allergies/`, `encounters/`, `internal/` |
| **Exposes** | Public: patient CRUD + search (with `ids=` filter), sub-resources, encounters per patient, **cross-patient encounter queries** (drafts, upcoming follow-ups). Internal: `/internal/patients/{id}/basic`, `/internal/patients/{id}/chart`, `/internal/patients/charts` (bulk, paged, for the insights worklist) |
| **Depends on** | Nothing |
| **Key invariants** | One primary condition per patient (partial unique index). Final encounters are immutable; **drafts can be edited or soft-deleted**. Soft delete only. Optimistic locking on patients |
| **Scaling** | Stateless; read replica for list/search if needed |

### 4.3 lab-svc

| | |
|---|---|
| **Owns** | Laboratory data and everything derived from it |
| **Database / tables** | `lab_db`: `lab_tests`, `lab_reference_ranges`, `lab_reports`, `lab_results`, **`patient_lab_status`** (read model) |
| **Exposes** | Public: test catalog, create report, list results (with `flag=abnormal`), trends, latest + CKD category, **batch summary for list rows**. Internal: same data plus `/internal/labs/status` (bulk) for ai-svc |
| **Depends on** | patient-svc (patient exists, sex, DOB) — **one read call, only when creating a report** |
| **Key invariants** | Reference range and flag are **snapshotted** at write time. Values are stored canonical + original. Results are append-only (corrections are new rows with `supersedes_id`). `patient_lab_status` is updated **in the same transaction** as the write and can be rebuilt from `lab_results` |
| **Scaling** | Stateless; read-heavy → index on `(patient_id, test_code, collected_at DESC)`, partition by time if volume grows |

### 4.4 ai-svc

| | |
|---|---|
| **Owns** | AI summaries and their audit trail, plus the deterministic insights (gap rules, worklist, dashboard aggregate) |
| **Database / tables** | `ai_db`: `ai_summaries` (+ `llm_tool_calls` for the tool-call trace) |
| **Exposes** | AI: `POST /ai/patients/{id}/summary` (`202`, then poll), `GET /ai/patients/{id}/summaries`, `GET /ai/summaries/{id}` (poll and detail). Insights, **no LLM**: `GET /insights/dashboard`, `GET /insights/worklist`, `GET /insights/patients/{id}/gaps` |
| **Depends on** | patient-svc, lab-svc (reads, including bulk), external LLM (summary only) |
| **Key invariants** | AI output is stored only after schema validation. The context actually sent is stored with it. Never writes to another service. Insights endpoints never call the LLM |
| **Scaling** | Stateless; bounded by LLM provider quota → concurrency semaphore + per-user quota (see §10.10, §13) |

---

## 5. Data architecture

### 5.1 Isolation model: one PostgreSQL instance, one database per service

```
PostgreSQL container (single instance)
├── auth_db     ← owner/role auth_svc      (only auth_svc may CONNECT)
├── patient_db  ← owner/role patient_svc   (only patient_svc may CONNECT)
├── lab_db      ← owner/role lab_svc       (only lab_svc may CONNECT)
└── ai_db       ← owner/role ai_svc        (only ai_svc may CONNECT)
```

**Rules**
1. Each service has **its own database and its own DB role**. `CONNECT` is revoked from `PUBLIC` and granted only to the owning role, so a service physically cannot open another service's database.
2. **PostgreSQL cannot join across databases.** A cross-service SQL join is therefore impossible, not just discouraged. Ownership is enforced by the engine rather than by convention.
3. **No cross-database foreign keys.** Cross-service references (`patient_id` in lab and ai, `clinician_id` everywhere) are plain UUIDs validated through the owning service's API.
4. Data from another service is obtained through that service's API, never its tables (see §5.6 for how this works in practice).
5. Each service uses the default `public` schema inside its own database, so there is no `search_path` juggling. Every service runs **its own Alembic migrations** against its own database.
6. All tables: UUID PKs, `created_at`, `updated_at`; user-authored rows add `created_by` (UUID from JWT).
7. **Clinical tables use soft delete** (`deleted_at`). Medical records are never hard-deleted. A side benefit is that a UUID reference from another service never dangles, so no cross-service cascade logic is needed.
8. Moving a service's database to its own server later is a connection-string change.

**Options considered**

| Option | Verdict |
|---|---|
| A. One database, shared tables, any service can touch any table | Rejected. Hidden coupling (the schema becomes an API), no ownership, and ai-svc, which talks to an external LLM, could read `password_hash` |
| B. One database, one schema per service, role grants | Viable lighter alternative. Isolation depends on grants being right, and cross-schema joins stay technically possible |
| **C. One instance, one database per service** | **Chosen.** Engine-enforced isolation on a single container |
| D. One Postgres instance per service | Overkill at this scale |

**What this costs (accepted)**
- No cross-database joins or FKs, by design. Cross-service data goes through APIs (§5.6).
- Extensions are installed per database: `citext` in `auth_db`, `pg_trgm` in `patient_db`.
- The four services' connection pools share one instance's `max_connections`, so pool sizes are set explicitly and PgBouncer is added when replicas grow.
- Slightly more init and backup plumbing (a database-creation script, per-database dumps or a cluster backup).

`infra/postgres/init-databases.sh` (runs once from `/docker-entrypoint-initdb.d/`, as the superuser):

```bash
#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE auth_svc    LOGIN PASSWORD '${AUTH_DB_PW}';
CREATE ROLE patient_svc LOGIN PASSWORD '${PATIENT_DB_PW}';
CREATE ROLE lab_svc     LOGIN PASSWORD '${LAB_DB_PW}';
CREATE ROLE ai_svc      LOGIN PASSWORD '${AI_DB_PW}';

CREATE DATABASE auth_db    OWNER auth_svc;
CREATE DATABASE patient_db OWNER patient_svc;
CREATE DATABASE lab_db     OWNER lab_svc;
CREATE DATABASE ai_db      OWNER ai_svc;

REVOKE CONNECT ON DATABASE auth_db    FROM PUBLIC;
REVOKE CONNECT ON DATABASE patient_db FROM PUBLIC;
REVOKE CONNECT ON DATABASE lab_db     FROM PUBLIC;
REVOKE CONNECT ON DATABASE ai_db      FROM PUBLIC;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname auth_db    -c "CREATE EXTENSION IF NOT EXISTS citext;"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname patient_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### 5.2 auth_db

```mermaid
erDiagram
    USERS ||--o{ REFRESH_TOKENS : has
    USERS {
        uuid id PK
        citext email UK
        text password_hash
        text full_name
        text role "clinician (only value today)"
        bool is_active
        int failed_login_count
        timestamptz locked_until
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        uuid family_id "rotation family"
        text token_hash UK
        timestamptz expires_at
        timestamptz revoked_at
        uuid replaced_by_id
        text user_agent
        timestamptz created_at
    }
```

### 5.3 patient_db

```mermaid
erDiagram
    PATIENTS ||--o{ PATIENT_CONDITIONS : has
    PATIENTS ||--o{ MEDICATIONS : takes
    PATIENTS ||--o{ ALLERGIES : has
    PATIENTS ||--o{ ENCOUNTERS : visits
    ENCOUNTERS ||--o| ENCOUNTER_VITALS : records
    ENCOUNTERS ||--o{ ENCOUNTER_DIAGNOSES : yields
    PATIENT_CONDITIONS ||--o{ ENCOUNTER_DIAGNOSES : "linked from"
    PATIENTS {
        uuid id PK
        text mrn UK "PT-000123"
        text first_name
        text last_name
        date date_of_birth
        text sex "M | F | O"
        text phone
        text email
        text address
        text past_medical_history
        text family_history
        text social_history
        text allergy_status "unknown | nka | has_allergies"
        text established_ckd_stage "G1 G2 G3a G3b G4 G5 or null"
        int version "optimistic lock"
        timestamptz deleted_at
        timestamptz created_at
        timestamptz updated_at
    }
    PATIENT_CONDITIONS {
        uuid id PK
        uuid patient_id FK
        text icd10_code
        text description
        text category "nephrology | comorbidity"
        bool is_primary
        text status "active | resolved"
        date onset_date
        uuid source_encounter_id FK
        timestamptz deleted_at
    }
    MEDICATIONS {
        uuid id PK
        uuid patient_id FK
        text name
        text dose
        text route
        text frequency
        date start_date
        date end_date
        text status "active | discontinued"
    }
    ALLERGIES {
        uuid id PK
        uuid patient_id FK
        text allergen
        text reaction
        text severity "mild | moderate | severe"
    }
    ENCOUNTERS {
        uuid id PK
        uuid patient_id FK
        timestamptz encounter_date
        text encounter_type "new | follow_up | emergency"
        uuid clinician_id "no FK, from JWT"
        text chief_complaint
        text_array symptoms
        text examination_notes
        text assessment
        text plan
        date follow_up_date
        text status "draft | final"
        int version
        timestamptz finalized_at
        timestamptz deleted_at "drafts only"
        uuid created_by
    }
    ENCOUNTER_VITALS {
        uuid encounter_id PK
        int systolic_bp
        int diastolic_bp
        int heart_rate
        numeric temperature_c
        numeric weight_kg
    }
    ENCOUNTER_DIAGNOSES {
        uuid id PK
        uuid encounter_id FK
        text icd10_code
        text description
        uuid condition_id FK
    }
```

`audit_events(id, actor_id, patient_id, action, resource, resource_id, at, request_id)` records chart reads and mutations (who looked at / changed what). Healthcare systems are expected to answer "who accessed this chart".

**Constraints and indexes**

| Item | Purpose |
|---|---|
| `UNIQUE INDEX ON patient_conditions(patient_id) WHERE is_primary AND status='active'` | At most one primary diagnosis per patient |
| `CHECK (systolic_bp BETWEEN 50 AND 300)`, `diastolic 20–200`, `heart_rate 20–300`, `temperature_c 30–45`, `weight_kg 1–500` | Reject implausible vitals at the database |
| `CHECK (systolic_bp > diastolic_bp)` | Basic physiological consistency |
| `GIN (first_name gin_trgm_ops, last_name gin_trgm_ops)` | Fast `ILIKE`/fuzzy name search |
| `UNIQUE (mrn)` (btree supports prefix search with `text_pattern_ops`) | Patient ID search |
| `INDEX ON encounters(patient_id, encounter_date DESC) WHERE deleted_at IS NULL` | Encounter history and `last_visit` |
| `INDEX ON encounters(status, encounter_date DESC) WHERE deleted_at IS NULL` | Dashboard draft list and draft count |
| `INDEX ON encounters(follow_up_date) WHERE status='final' AND deleted_at IS NULL` | Dashboard upcoming follow-ups |
| `CHECK (established_ckd_stage IN ('G1','G2','G3a','G3b','G4','G5'))` | Stage values match the UI dropdown |
| `INDEX ON medications(patient_id) WHERE status='active'` | "Current medications" |
| Partial index `WHERE deleted_at IS NULL` on patients | Soft-delete aware queries |

**Design decisions**
- **DOB is stored, age is computed.** A stored age is wrong tomorrow.
- **`allergy_status` is a real field.** "No allergy rows" is ambiguous (unknown vs none). This distinction is what lets the AI tell *missing* from *negative* without guessing.
- **Primary diagnosis comes from `patient_conditions.is_primary`**, not a duplicated text column on `patients`.
- **`established_ckd_stage`** is a clinician-entered diagnosis, separate from the eGFR category that lab-svc computes (see §6.1).
- **Encounter lifecycle:** `draft` (editable, **deletable**) → `final` (immutable, with `finalized_at`). A draft delete is a soft delete; deleting a final encounter returns `409`. Addenda would be new records, not edits.
- **Last visit** shown in the patient list is `MAX(encounter_date)` over **final** encounters, computed in the same query as the list (no extra column to keep in sync).
- **Problem list from an encounter:** each diagnosis row on the encounter form has an "add to problem list" choice. Choosing it inserts or reactivates a `patient_conditions` row in the same transaction as the encounter save (`source_encounter_id` records where it came from).
- **Primary diagnosis display:** the list and the dashboard use the one active `is_primary` condition. If none exists the UI shows "None recorded" and the gap rule `NO_PRIMARY_DIAGNOSIS` fires.
- **Optimistic locking:** `PATCH` requires the current `version`; mismatch returns `409 CONFLICT`. Prevents two clinicians silently overwriting each other.
- **Transactional diagnosis flow:** finalizing an encounter with a diagnosis that should appear on the problem list inserts/updates `patient_conditions` in the same transaction.

### 5.4 lab_db

```mermaid
erDiagram
    LAB_TESTS ||--o{ LAB_REFERENCE_RANGES : defines
    LAB_TESTS ||--o{ LAB_RESULTS : measured_as
    LAB_REPORTS ||--o{ LAB_RESULTS : contains
    LAB_RESULTS }o--|| PATIENT_LAB_STATUS : "summarized in"
    LAB_TESTS {
        text code PK "CREAT EGFR BUN K HB CA PHOS UACR"
        text name
        text canonical_unit
        jsonb allowed_units "unit to factor"
        int decimals
    }
    LAB_REFERENCE_RANGES {
        uuid id PK
        text test_code FK
        text sex "M | F | null=any"
        int age_min
        int age_max
        numeric low
        numeric high
        numeric critical_low
        numeric critical_high
        date effective_from
    }
    LAB_REPORTS {
        uuid id PK
        uuid patient_id "no FK, UUID ref"
        timestamptz collected_at
        text lab_name
        text notes
        uuid entered_by
        timestamptz created_at
    }
    LAB_RESULTS {
        uuid id PK
        uuid report_id FK
        uuid patient_id "denormalized"
        timestamptz collected_at "denormalized"
        text test_code FK
        numeric value "canonical unit"
        text unit "canonical unit"
        numeric value_original
        text unit_original
        numeric ref_low "snapshot"
        numeric ref_high "snapshot"
        text flag "normal low high critical_low critical_high"
        uuid supersedes_id "correction chain"
    }
    PATIENT_LAB_STATUS {
        uuid patient_id PK "UUID ref"
        jsonb latest "latest result per test: value, unit, flag, collected_at, report_id"
        text egfr_category "G1 G2 G3a G3b G4 G5"
        text uacr_category "A1..A3"
        jsonb egfr_stats "n, first, last, slope_per_year, direction, rapid_decline"
        jsonb creat_stats "same shape"
        jsonb egfr_spark "last 12 points: t, v"
        bool has_critical
        bool rapid_decline
        timestamptz last_result_at
        timestamptz updated_at
    }
```

**Decisions**
- **Report vs result:** a `lab_report` is one blood draw (one date, one lab); `lab_results` are its individual analytes. This mirrors how labs actually issue results and lets one form submit several tests at once.
- **Units:** the user may enter a value in any `allowed_units` entry for that test (for example creatinine in mg/dL or µmol/L). lab-svc converts to the canonical unit, stores both original and canonical, and computes flags on canonical. Unknown unit → `422`.
- **Snapshot `ref_low`, `ref_high`, `flag` at write time.** If ranges are revised, historical results keep the interpretation that applied when they were reported.
- **Deliberate denormalization** of `patient_id` and `collected_at` onto `lab_results` (same aggregate): trend queries become a single index scan with no join.
- **Index:** `(patient_id, test_code, collected_at DESC)`.
- **Append-only:** results are never updated. A correction inserts a new row pointing to `supersedes_id`; queries return the latest non-superseded row by default.
- **Reference ranges** are seeded from the **supplied ranges file**. Ranges are keyed by sex (and optionally age band) because values such as creatinine and hemoglobin differ by sex.
- Plausibility CHECKs per test (for example value ≥ 0, `collected_at` not in the future).
- **`patient_lab_status` is a read model owned by lab-svc.** It holds exactly what list rows, the dashboard and the worklist need (latest result per test, G and A categories, eGFR and creatinine trend stats, the last 12 eGFR points for the sparkline, and the two attention flags). It is written **in the same transaction** as every report or correction, so it is never stale, and it can be rebuilt from `lab_results` by a script. Without it, rendering one page of eight list rows would run eight trend computations; the dashboard would run one per patient. See ADR-015.
- **Flags kept per result vs per patient:** `lab_results.flag` is the interpretation at the time (snapshot). `patient_lab_status.has_critical` reflects the **latest** result per test only, which is what "needs attention" means.

### 5.5 ai_db

```mermaid
erDiagram
    AI_SUMMARIES ||--o{ LLM_TOOL_CALLS : traces
    AI_SUMMARIES {
        uuid id PK
        uuid patient_id "UUID ref"
        uuid requested_by
        text status "running | completed | degraded | failed"
        text provider
        text model
        text prompt_version
        text context_hash "cache key"
        jsonb context_snapshot "what was sent"
        jsonb output "validated result only"
        jsonb gaps "deterministic findings"
        jsonb facts "CKD category, abnormal results, trend stats"
        jsonb sources "ref to label, type, target"
        jsonb validation "schema, refs resolved, safety flags, repaired"
        jsonb progress "ordered pipeline steps with state, ms, note"
        uuid cached_from "set when the job reused an earlier summary"
        timestamptz started_at
        timestamptz finished_at
        text error_code
        int attempts
        int latency_ms
        int tokens_in
        int tokens_out
        timestamptz created_at
    }
    LLM_TOOL_CALLS {
        uuid id PK
        uuid summary_id FK
        int seq
        text tool_name
        jsonb arguments
        int result_bytes
        int latency_ms
        text status "ok | error | rejected"
    }
```

- `context_snapshot` makes every summary **reproducible and auditable**: you can see exactly what the model was shown. The UI exposes it in a collapsed "What the AI was given" panel, which also proves that name and patient ID were removed.
- `progress` is updated after each pipeline step. The UI polls the summary row and renders it as the stepper (§10.3). A reaper marks any `running` row older than `LLM_JOB_TTL_S` as `failed` (`JOB_TIMEOUT`), so a crashed worker never leaves a spinner forever.
- `failed` rows (for example upstream unavailable) and cache-hit job rows (`cached_from` set) are kept for observability but **hidden from the history list**. The history shows only `completed` and `degraded` originals.
- `context_hash` (sha256 of context + prompt version + model) powers caching (§10.10).
- `llm_tool_calls` records every tool the model invoked (§10.4). Arguments and result *sizes* are stored; large results are not duplicated.

### 5.6 How "joins" work without cross-service SQL

| Need | Approach |
|---|---|
| Patient list with primary dx and last visit | Same database → normal SQL JOIN inside patient-svc |
| Latest eGFR and sparkline on list rows | After the page of patients loads, Angular calls `GET /labs/summary?patient_ids=` once for that page (max 50 ids). One indexed read of `patient_lab_status` in lab-svc |
| List filter **Needs attention** | Angular calls `GET /insights/worklist?attention=true` (ids only), then `GET /patients?ids=...&q=...`. patient-svc filters, sorts and pages within those ids |
| Dashboard | Three parallel calls (§3.2b). ai-svc composes the clinical aggregate from bulk internal reads; patient-svc answers drafts and follow-ups by itself |
| Patient page showing demographics + labs | Angular fires parallel calls (`/patients/{id}`, `/labs/patients/{id}/…`) |
| Lab flag needs patient sex | lab-svc calls `GET /internal/patients/{id}/basic` once per report |
| AI summary needs everything | ai-svc gathers via APIs and composes in code (**API composition**) |

**What the list can and cannot sort by.** Server-side sort works for fields patient-svc owns: name, patient ID, age (date of birth), primary diagnosis and last visit. **Latest eGFR is not a server-side sort**, because sorting a page of patients by a value in another database would either sort only the visible page (misleading) or need a cross-service merge. The need behind that sort ("show me the sickest patients first") is served by the Needs attention filter and the dashboard, which are computed across all patients. See ADR-020.

**When composition hurts.** If list latency becomes a problem, add a BFF endpoint then, not before. The unit of composition is a page of at most 50 ids, so cost does not grow with total patients.

---

## 6. Clinical logic (CKD, flags, trends)

All clinical computation lives in **pure functions** (no I/O) in `lab-svc/app/domain/`. This makes them trivially unit-testable and keeps them out of the LLM.

### 6.1 CKD classification — two distinct concepts

| Concept | Source of truth | Meaning |
|---|---|---|
| **Established CKD stage** | `patients.established_ckd_stage` in patient_db (clinician-entered, one of G1, G2, G3a, G3b, G4, G5) | A diagnosis made by a clinician |
| **eGFR category (G-stage) of latest result** | computed by lab-svc | A classification of one lab value |

A single eGFR value does not establish CKD (CKD requires persistence beyond 3 months). So the UI shows both side by side, and the system flags a **mismatch** as an inconsistency.

**eGFR categories (KDIGO, mL/min/1.73 m²)** — to be aligned with the supplied classification criteria:

| Category | eGFR |
|---|---|
| G1 | ≥ 90 |
| G2 | 60–89 |
| G3a | 45–59 |
| G3b | 30–44 |
| G4 | 15–29 |
| G5 | < 15 |

**UACR categories (mg/g):** A1 < 30 · A2 30–300 · A3 > 300.

**Boundary rule:** thresholds are lower-inclusive (for example 60 → G2, 59.9 → G3a). Tests cover every boundary.

### 6.2 Abnormal flagging

```
flag(value, range):
    value < critical_low   → critical_low
    value < low            → low
    value > critical_high  → critical_high
    value > high           → high
    else                   → normal
```

Range selection: match by `test_code`, then `sex` (specific over `null`), then age band, then latest `effective_from`. If no range matches, `flag = unknown` (never silently "normal").

Illustrative seed values (**replace with the supplied reference ranges file; these are placeholders**). Note that eGFR ≥ 90 as "normal" flags every G2 value as low. That follows the supplied-range rule in the PS, so the UI shows the flag together with the G-category and does not treat a low flag on a G2 result as an alarm:

| Test | Canonical unit | Illustrative range |
|---|---|---|
| Creatinine | mg/dL | M 0.7–1.3, F 0.6–1.1 |
| eGFR | mL/min/1.73 m² | ≥ 90 normal |
| BUN | mg/dL | 7–20 |
| Potassium | mmol/L | 3.5–5.0 |
| Hemoglobin | g/dL | M 13.5–17.5, F 12.0–15.5 |
| Calcium | mg/dL | 8.5–10.5 |
| Phosphorus | mg/dL | 2.5–4.5 |
| UACR | mg/g | < 30 |

### 6.3 Trend computation (lab-svc `/trends`)

For each requested test over an optional date window, return the series and statistics:

```json
{
  "test_code": "EGFR",
  "unit": "mL/min/1.73m2",
  "points": [{"collected_at": "...", "value": 54.0, "flag": "low"}],
  "stats": {
    "n": 6, "first": 62.0, "last": 48.0,
    "abs_change": -14.0, "pct_change": -22.6,
    "slope_per_year": -9.4,
    "direction": "worsening",
    "rapid_decline": true,
    "span_days": 540
  }
}
```

- **Slope:** ordinary least squares over (days since first point, value), scaled to per-year.
- **Insufficient data:** fewer than 3 points → `direction: "insufficient_data"` and `slope_per_year: null`. The system never extrapolates from two points.
- **Rapid decline (eGFR):** slope worse than −5 mL/min/1.73 m²/year (KDIGO definition), configurable.
- **Direction thresholds** (stable vs improving vs worsening) are configuration, per test, with direction semantics defined per test (for eGFR a falling value is worsening; for creatinine a rising value is worsening). Defaults used by the prototype:

| Test | Worsening | Improving | Otherwise |
|---|---|---|---|
| eGFR | slope ≤ −2 mL/min/1.73 m² per year | slope ≥ +2 | stable |
| Creatinine | slope > +0.1 mg/dL per year | slope < −0.1 | stable |

- **Sparkline points:** `patient_lab_status.egfr_spark` holds the last 12 eGFR points. A list row therefore never needs the full series.
- **Date range on charts:** the Labs tab offers 6 months, 1 year, 2 years and all. The range maps to the `from` parameter. Stats are recomputed for the selected window, so the chips under each chart always describe what the chart shows.
- **Chart overlays:** the eGFR chart draws the KDIGO G-stage bands; the creatinine chart draws the sex-specific reference band. Both come from data the API already returns (`points`, `ref_low`, `ref_high`).

---

## 7. Authentication and security

### 7.1 Login and signup

| Flow | Behavior |
|---|---|
| **Signup** `POST /auth/signup` | Creates a `clinician`. Guarded by `ENABLE_PUBLIC_SIGNUP` (on for the demo). Production note: accounts would be created by an invite script or federated through the clinic's identity provider; there is no in-app admin. Password policy enforced (length ≥ 10, not in a small common-password list). Email unique (`citext`) |
| **Login** `POST /auth/login` | Verifies argon2id hash. Returns access JWT in body and sets refresh token as `httpOnly; Secure; SameSite=Strict; Path=/api/auth` cookie |
| **Refresh** `POST /auth/refresh` | Rotates the refresh token. Presenting an already-revoked token revokes the **entire family** (theft detection) |
| **Logout** `POST /auth/logout` | Revokes the family, clears cookie |
| **Me** `GET /auth/me` | Current user profile |
| **Lockout** | 5 failed logins → `locked_until = now + 15 min`. Generic "invalid credentials" message (no user enumeration), constant-time-ish comparison |

### 7.2 Tokens

- **Access token:** JWT, **RS256**, 15 min. Claims: `sub`, `role`, `iss`, `aud`, `iat`, `exp`, `jti`, `kid` header.
- **Refresh token:** opaque random 256-bit value, **stored only as a hash**, 7-day expiry, single use (rotated).
- **Why RS256 over HS256:** only auth-svc holds the private key. Gateway and services hold the public key, so a compromised downstream service cannot mint tokens. The gateway and services verify locally from a cached JWKS (`/.well-known/jwks.json`) — no per-request call to auth-svc, so auth-svc is not a runtime bottleneck or single point of failure for already-authenticated traffic.
- **Key rotation:** `kid` in the header; JWKS can publish two keys during rotation.

### 7.3 Authorization (defense in depth)

1. Gateway verifies the JWT and rejects unauthenticated requests early.
2. **Each service verifies the JWT again** (cheap public-key check) and authorizes from claims. Trusting only the network perimeter is fragile.
3. One role, `clinician` (clinical read/write, insights, AI). It is still carried as a claim and checked by `require_role("clinician")`, so a second role can be added later without changing the token format. There is no admin role, no user-management API and no admin screen (ADR-018).
4. `/internal/*` routes are **blocked at the gateway** and also require a valid JWT whose `aud` matches.

### 7.3b Session experience

The app shows the signed-in clinician (name and role) in the top bar with a sign-out action. Sign-out calls `POST /auth/logout`, which revokes the refresh-token family. A token that expires mid-session is refreshed silently and the failed request is retried once (§15.2). If the refresh token is revoked or expired, the user is returned to the sign-in screen with a short message. The prototype starts already signed in to keep the focus on the product screens; the sign-in and sign-up screens are listed in §15.4.

### 7.4 Other security measures

| Area | Measure |
|---|---|
| Transport | TLS terminates at the gateway/proxy in real deployments |
| Passwords | argon2id, per-user salt, tunable cost |
| Input | Pydantic validation, max lengths, parameterized queries (SQLAlchemy), no string-built SQL |
| CORS | Allow-list of the Angular origin only |
| Rate limiting | Strict on `/auth/login`, `/auth/signup`; moderate globally; separate bucket for `/ai` |
| Secrets | Env vars / mounted files, never in git. `.env.example` committed, `.env` ignored |
| DB | Per-service roles, least privilege |
| Audit | `audit_events` (patient-svc), `ai_summaries` (ai-svc), `created_by` on all authored rows |
| Logging | No PHI in logs: log IDs and request IDs, not names or free-text notes |
| Containers | Non-root user, minimal base image, only the gateway publishes a port |

---

## 8. API Gateway

A custom gateway (your own), kept **thin on purpose**.

### Responsibilities
| Concern | Detail |
|---|---|
| Routing | `/api/auth/*` → auth-svc, `/api/patients/*` and **`/api/encounters/*`** → patient-svc, `/api/labs/*` → lab-svc, `/api/ai/*` and **`/api/insights/*`** → ai-svc (prefix stripped) |
| Authentication | Verify JWT with cached JWKS (refresh on unknown `kid`); reject expired/invalid. Public paths allow-listed: `/auth/login`, `/auth/signup`, `/auth/refresh`, `/auth/logout` and health |
| CORS | Single allow-listed origin, credentials allowed (refresh cookie) |
| Rate limiting | Token bucket per client IP and per user; in-memory for one instance, Redis-backed when scaled out. `GET /ai/summaries/{id}` polling has its own generous bucket so progress polling is never throttled |
| Request ID | Generate `X-Request-ID` if absent; propagate; return to client |
| Timeouts | Per route: default 5 s, `/api/insights/**` 10 s (bulk composition). `/api/ai/**` is also 5 s now that `POST /summary` returns `202` immediately and the UI polls (§10.3). Gateway timeout → `504` envelope |
| Error envelope | Convert upstream failures (connect error, timeout) to the uniform error shape |
| Security | **Block `/internal/**` from outside**; strip hop-by-hop headers; size limit on bodies |
| Observability | Access log (method, path template, status, latency, request id, user id) and `/metrics` |
| Health | `/health` (self) and `/ready` (checks upstream reachability, optional) |

### Does NOT do
- Business logic.
- Response aggregation or orchestration (that belongs in a BFF if it is ever needed).
- Authorization decisions beyond coarse authentication — services own authorization.

### Contract with services
- Forwards `Authorization` and `X-Request-ID` unchanged.
- Adds `X-Forwarded-For`. Services must not trust headers like `X-User-Id` from clients; identity always comes from the verified JWT.

---

## 9. Service-to-service communication

**Synchronous REST over HTTP (httpx.AsyncClient), reads only.**

| Caller → Callee | Endpoint | Purpose | When |
|---|---|---|---|
| lab → patient | `GET /internal/patients/{id}/basic` | Patient exists, sex, DOB (for range selection and age) | Creating a lab report |
| ai → patient | `GET /internal/patients/{id}/chart` (and finer tools) | Chart data | AI summary |
| ai → lab | `GET /internal/labs/patients/{id}/…` | Results, flags, trends, CKD category | AI summary, gaps |
| ai → patient | `GET /internal/patients/charts?cursor=&limit=200` | Bulk chart export limited to fields the rules use, plus name, MRN and age for display | Worklist, dashboard |
| ai → lab | `GET /internal/labs/status?cursor=&limit=200` | Bulk read of `patient_lab_status` | Worklist, dashboard |

**Resilience policy for every internal call** (implemented once in `libs/common/http.py`):

| Mechanism | Setting |
|---|---|
| Timeouts | connect 1 s, read 3 s (configurable) |
| Retries | Max 2, exponential backoff + jitter, **only on idempotent GET** and only for connect errors / 502/503/504 |
| Propagation | Forward user JWT and `X-Request-ID` |
| Failure mapping | Upstream failure → `502 UPSTREAM_UNAVAILABLE` with the upstream named in `details` |
| Bulkhead | Bounded `httpx` connection pool per upstream |

**Why not async messaging:** no operation requires it. All cross-service interaction is a read needed to answer the current request. See [ADR-005](#adr-005-no-saga-no-broker) for the trigger conditions that would justify introducing an outbox + events.

**Why forward the user JWT instead of a service token:** the audit trail always shows who initiated the call, and downstream authorization is evaluated for the real user. (A service-to-service token is a reasonable hardening step for non-user-initiated jobs.)

---

## 10. AI service design (including tool calling)

### 10.1 Principle: deterministic first, generative second

| Output required by PS | Produced by | LLM involvement |
|---|---|---|
| Creatinine/eGFR trends | lab-svc statistics | Narrates only |
| Abnormal findings | stored flags from lab-svc | Narrates only |
| Missing / inconsistent info | rule engine in ai-svc (`insights/`) | Optional commentary only |
| Nephrology history summary | LLM from structured chart | **Writes** |
| Comorbidity summary | LLM from structured conditions | **Writes** |
| Follow-up considerations | LLM, constrained | **Writes**, for clinician review |

Consequence: a hallucinating or failing LLM cannot corrupt a number, a flag, or a gap finding. If the LLM is down, the response degrades to the deterministic sections instead of failing.

### 10.2 Internal structure

```
ai-svc/app/
  api/              routers: summary.py (AI), insights.py (deterministic)
  core/             config, security (JWT verify), logging
  orchestrator/     SummaryOrchestrator  (runs the pipeline)
  context/          ContextBuilder, minimizer, hashing
  insights/         deterministic, no LLM: gaps/ (pure-function rule engine),
                    attention.py (attention rule), worklist.py, dashboard.py
  tools/            tool registry + tool implementations (read-only)
  llm/
    base.py         LLMProvider protocol, capabilities
    gemini.py  groq.py  ollama.py  mock.py
    resilience.py   timeout, retry, circuit breaker, concurrency limiter
  prompts/          versioned prompt templates (v1, v2 ...)
  schemas/          Pydantic: LLM output schema, API schemas
  validation/       schema + grounding + safety lint
  repository/       ai_summaries, llm_tool_calls
  jobs/             in-process summary runner, progress writer, stale-job reaper
```

The `insights/` package imports nothing from `llm/`. A test asserts this, which is how "insights never depend on the LLM" is enforced rather than promised.

**`LLMProvider` (Strategy/Adapter):**

```python
class LLMProvider(Protocol):
    name: str
    capabilities: Capabilities           # supports_tools, supports_json_mode, max_context
    async def generate(self, req: LLMRequest) -> LLMResponse: ...
```

`LLMRequest` carries system prompt, messages, optional tool definitions, JSON schema, temperature (low, for example 0.2), and max tokens. Provider chosen by `LLM_PROVIDER` env var. `MockProvider` returns deterministic, schema-valid output (and can simulate tool calls and failures), which makes tests, CI and offline demos possible and satisfies the PS "documented mock" clause. Most major providers' free tiers expose function calling, but support varies by model, so the adapter declares `supports_tools` and the orchestrator adapts.

### 10.3 Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant GW as Gateway
    participant AI as ai-svc
    participant PAT as patient-svc
    participant LAB as lab-svc
    participant LLM as LLM provider
    participant DB as ai_db

    UI->>GW: POST /api/ai/patients/{id}/summary
    GW->>AI: forward (JWT, request-id, 5 s timeout)
    AI->>DB: insert row status=running
    AI-->>UI: 202 {summary_id, status: running}
    Note over UI,AI: UI now polls GET /api/ai/summaries/{id} every second
    AI->>AI: authz, per-user quota, concurrency slot
    par gather baseline context (parallel)
        AI->>PAT: chart (conditions, meds, allergies, last encounters)
        AI->>LAB: latest results + flags + trends + CKD category
    end
    AI->>AI: run gap rules (deterministic)
    AI->>AI: minimize/de-identify, build context packet, hash
    AI->>DB: lookup completed summary by context_hash
    alt cache hit and not force
        DB-->>AI: summary
        AI->>DB: mark job row cached_from=original, status=completed
        Note over UI,AI: next poll returns the saved summary with cached=true
    else cache miss
        loop up to MAX_TOOL_ITERATIONS (default 4)
            AI->>LLM: prompt + context packet + tool definitions
            LLM-->>AI: tool_call(s) or final JSON
            opt tool_call
                AI->>AI: validate tool + args, bind patient_id
                AI->>PAT: read-only fetch via tool (or LAB)
                AI->>AI: record llm_tool_calls row
            end
        end
        AI->>AI: parse → Pydantic → grounding check → safety lint
        alt invalid output
            AI->>LLM: one repair attempt (errors fed back)
        end
        AI->>DB: persist context_snapshot, output, gaps, trace, usage, status
        Note over UI,AI: next poll returns {facts, gaps, ai, sources, validation, disclaimer}
    end
```

**How the request is shaped (v2).** The pipeline above runs in a background task inside ai-svc. The client interaction is:

1. `POST /ai/patients/{id}/summary` always returns `202 {summary_id, status: "running", progress: [...]}` after inserting an `ai_summaries` row. It cannot answer `200` directly, because whether the data is unchanged is only known after the context has been gathered and hashed (steps 2 to 4).
2. The background task runs the pipeline and updates `progress` after each step.
3. The UI polls `GET /ai/summaries/{summary_id}` every second until `status` is `completed`, `degraded` or `failed`.

**Cache hit.** After step 4 the task finds a completed summary with the same context hash (and no `force`). It marks the job row `completed` with `cached_from = <original id>` and skips steps 5 to 7. Polling then returns the original summary's content with `cached: true`. History lists originals only (rows with `cached_from` are hidden), so repeated clicks never clutter the history.

This keeps every HTTP request short, lets the UI show real progress, and removes the 45-second gateway timeout as a failure mode. No queue or worker fleet is needed: the task runs in the same process, and the reaper covers a crashed process (§5.5). When one process is not enough, the same contract moves to a queue unchanged (ADR-017).

**Pipeline steps and what the user sees**

| # | Internal step | Label in the UI | Typical note shown |
|---|---|---|---|
| 1 | AuthZ, per-user quota, concurrency slot | Opening the chart | Ready |
| 2 | Gather chart and labs in parallel | Reading the chart and lab results | Done |
| 3 | Gap rules, trends, CKD category (deterministic) | Calculating trends and checking for gaps | N rule findings, N abnormal results |
| 4 | Minimize, build context packet, hash, cache lookup | Preparing what the AI will see | New or changed data, or "Same data as an earlier summary" |
| 5 | LLM loop with optional tool calls | Writing the summary | Looking up recent encounters, lab trend EGFR, and so on |
| 6 | Parse, schema, grounding, safety lint, one repair attempt | Checking the summary | 26 of 26 sources found in the record |
| 7 | Persist | Saving | Saved |

On a cache hit steps 5 to 7 are marked skipped with the note "Not needed, reusing the saved summary", and the UI shows "Nothing has changed since the last summary, so the saved one is shown."

**Step detail**

1. **Gather baseline context in parallel** (`asyncio.gather`) from patient-svc and lab-svc via their internal APIs.
2. **Compute deterministic facts**: flags (from lab-svc), trend stats (lab-svc), CKD category, and the gap findings (§10.5).
3. **Minimize and de-identify**: send age and sex, not name, MRN, phone, email or address. Send only fields the prompt uses. Dates are kept because trends need them (synthetic data here; real deployments need a DPA/BAA with the provider or a local model).
4. **Build the context packet**: a compact, structured JSON with stable item IDs, for example `lab:EGFR:2026-03-14`, `enc:ab12…`, `cond:…`. IDs let the model cite sources and let us verify citations.
5. **Hash and check cache** (§10.10).
6. **Run the LLM loop** (with or without tools — §10.4).
7. **Validate** (§10.6), **persist**, **respond** (§10.9).

### 10.4 Tool calling

**Why tool calling here.** The baseline context packet always contains the essentials (the PS requires context to be prepared before the call). Tool calling adds a controlled way for the model to *pull more detail only when it needs it*, rather than stuffing the whole chart into every prompt: for example older encounter notes, a specific lab series over a different window, or the active medication list. Benefits: smaller prompts, lower token cost, scales to long histories, and a clear audit trail of what the model chose to look at.

**Honest trade-offs.** Tool calling adds latency (extra round trips), nondeterminism, and a dependency on the chosen free-tier model supporting it well. For the six required outputs, a single-shot prompt over the baseline packet is sufficient. Therefore:

- Tool calling is **feature-flagged** (`LLM_TOOLS_ENABLED`) and gated by `provider.capabilities.supports_tools`.
- If unsupported or disabled, the pipeline runs **single-shot** with a larger baseline packet. Same output schema, same validation.

**Tool set (all read-only, thin wrappers over internal APIs):**

| Tool | Arguments (model-supplied) | Backed by |
|---|---|---|
| `get_conditions` | `status?` | patient-svc |
| `get_medications_and_allergies` | none | patient-svc |
| `get_recent_encounters` | `limit` (≤ 5), `include_notes` | patient-svc |
| `get_lab_history` | `test_code`, `from?`, `to?` | lab-svc |
| `get_lab_trend` | `test_code` | lab-svc |
| `get_gap_report` | none | ai-svc rule engine |

**Safety design for tools** (this is where tool calling goes wrong in naive implementations):

| Risk | Control |
|---|---|
| Model asks for another patient's data | **`patient_id` is never a tool argument.** It is bound server-side from the request. The model cannot choose or change it |
| Model invents a tool or argument | Strict registry; arguments validated by Pydantic; unknown tool → `rejected`, error fed back once |
| Write actions via tools | **No write tools exist.** Tools are read-only by construction |
| Infinite or expensive loops | `MAX_TOOL_ITERATIONS` (default 4), max tool calls per run, overall deadline, per-tool timeout |
| Oversized tool results flooding context | Per-tool result caps (rows, characters); results truncated with an explicit `truncated: true` marker |
| Prompt injection from patient free text | Patient-authored text is passed as **data** inside delimited blocks; system prompt states it is untrusted; because tools are read-only and patient-scoped, the blast radius of a successful injection is limited to the model producing odd text, which validation and the safety lint then check |
| PHI leakage via tool results | Same minimizer as the baseline context is applied to tool outputs |
| Auditing | Every call recorded in `llm_tool_calls` (name, args, size, latency, status) |

**Orchestration loop:**

```
messages = [system, user(context_packet)]
for i in range(MAX_TOOL_ITERATIONS):
    resp = provider.generate(messages, tools=registry.definitions if tools_enabled else None,
                             response_schema=OutputSchema)
    if resp.tool_calls:
        for call in resp.tool_calls[:MAX_CALLS_PER_TURN]:
            result = registry.execute(call, patient_id=bound_patient_id, user_jwt=jwt)
            messages += [call, tool_result(result)]
        continue
    return resp.final_json
force final answer without tools on the last iteration
```

### 10.5 Deterministic gap and inconsistency engine

Pure functions over the fetched data, unit-tested in isolation. Output is a list of findings `{code, severity, message, evidence_refs}`.

**Missing information**

| Code | Severity | Rule |
|---|---|---|
| `ALLERGY_STATUS_UNKNOWN` | medium | `allergy_status = unknown` ("unknown" is not "no known allergies") |
| `NO_PRIMARY_DIAGNOSIS` | medium | No active `is_primary` condition |
| `NO_MEDICATIONS_DOCUMENTED` | low | No medication rows (cannot distinguish "none" from "not recorded") |
| `NO_LABS_RECORDED` | **high** | No lab results at all |
| `NO_RECENT_LABS` | medium | Most recent result older than 180 days (configurable) |
| `NO_LABS_FOR_TEST` | low | Key tests (creatinine, eGFR, UACR) never recorded |
| `INSUFFICIENT_TREND_DATA` | low | Fewer than 3 eGFR or creatinine points |
| `ENCOUNTER_NO_VITALS` | low | Final encounter without vitals |
| `ENCOUNTER_NO_ASSESSMENT` | medium | Final encounter without assessment or plan |
| `NO_ESTABLISHED_CKD_STAGE` | medium | eGFR below 60 across at least 90 days, with no established stage |

**Inconsistent information**

| Code | Severity | Rule |
|---|---|---|
| `CKD_STAGE_MISMATCH` | **high** | Established stage ≠ category of latest eGFR |
| `LAB_DATE_INVALID` | **high** | Result dated before birth or in the future |
| `EGFR_CREATININE_DISCORDANT` | medium | Reported eGFR differs from CKD-EPI 2021 computed from creatinine, age and sex by more than 12 mL/min/1.73 m² (same report only) |
| `DIRECTION_CONTRADICTION` | medium | Creatinine and eGFR trending in clinically incompatible directions (3+ points each) |
| `ACTIVE_MED_PAST_END_DATE` | low | Medication `active` but `end_date` in the past |
| `IMPLAUSIBLE_VITALS` | low | Defensive check on legacy or imported data (not reachable from the UI, which validates input) |

Each finding is `{code, severity, kind (missing | inconsistent), message, evidence_refs}`. The screen shows `message` and the severity; the code is for logs, tests and the API.

**The attention rule.** A patient **needs attention** when any of these holds: the latest result of any test is **critical**; eGFR shows **rapid decline**; or any **high-severity** finding exists. The dashboard and list store no flag for this. They always derive it from the rules above (§10.12), so changing a rule changes the worklist immediately.

The LLM may *comment* on these findings, but it does not decide them.

### 10.6 Validation of LLM output ("anti-corruption layer")

LLM output is treated like untrusted external input. Applied in order:

1. **Parse:** must be valid JSON.
2. **Schema:** Pydantic model with strict types, length limits, and required fields. Unknown fields rejected.
3. **Grounding / citations:** every narrative field and follow-up item carries `source_refs`; each ref must exist in the context packet or tool results. Unknown refs → reject or strip with a warning.
4. **Numeric grounding (lightweight):** numbers appearing in narratives must appear in the context. Violations become `grounding_warnings`, shown to the clinician, not silently ignored.
5. **Missing-info rule:** where data is absent, the model must emit `"not documented"` rather than infer; the schema has a `not_documented: string[]` field for explicit absences.
6. **Safety lint (§10.7).**
7. **Repair:** on failure of 1–3, one repair attempt feeds the validation errors back to the model. A second failure → `degraded`.

**Output schema (LLM-authored parts only):**

```json
{
  "history_summary":      {"text": "...", "source_refs": ["cond:…", "enc:…"]},
  "comorbidity_summary":  {"text": "...", "source_refs": ["cond:…"]},
  "trend_commentary":     {"text": "...", "source_refs": ["lab:EGFR:…"]},
  "abnormal_commentary":  {"text": "...", "source_refs": ["lab:K:…"]},
  "follow_up_considerations": [
    {"consideration": "...", "rationale": "...", "source_refs": ["lab:EGFR:…"]}
  ],
  "not_documented": ["allergy information", "medication adherence"]
}
```

There is intentionally **no** field for diagnosis, drug name/dose, or orders.

### 10.7 Clinical safety constraints

- **Prompt rules (versioned):** use only provided data; state "not documented" for anything absent; do not diagnose; do not recommend, start, stop or dose medications; phrase follow-ups as *considerations for clinician review*; no certainty language about causation; cite sources.
- **Safety lint:** a denylist/pattern check over output for directive treatment language (for example "start/prescribe/increase dose of …", "you have …", "diagnosis is …"). Matches are redacted or cause a repair attempt, and are recorded.
- **Schema design** removes the places where a diagnosis or prescription would naturally go.
- **UI and API** both label the content as AI-generated and attach the disclaimer.
- Low temperature, bounded output length.

### 10.8 Failure handling

| Failure | Handling | Result to client |
|---|---|---|
| LLM timeout / 5xx / network | Retry (max 1–2, backoff+jitter) | Then `degraded`: deterministic sections returned, AI section `unavailable`, HTTP 200 with `status: "degraded"` |
| 429 / quota exhausted | Honor `Retry-After`; no tight retry loop | `degraded` + `error_code: LLM_RATE_LIMITED` |
| Circuit open (repeated failures) | Fail fast for a cooldown | `degraded` immediately, no wasted latency |
| Invalid JSON / schema failure | One repair attempt | else `degraded` + `LLM_INVALID_OUTPUT` |
| Grounding failure | Strip offending parts / repair | else `degraded` |
| Tool failure | Error returned to the model as tool result once; model continues | If persistent: finish without that data and add to `not_documented` |
| Upstream (patient/lab) unavailable | Cannot build context | Summary ends `failed` with `error_code: UPSTREAM_UNAVAILABLE`; the row is hidden from history and nothing partial is summarized. The UI shows what failed and a **Try again** button. Insights endpoints return `502 UPSTREAM_UNAVAILABLE` |
| Deadline exceeded | Abort loop | `degraded`, or `failed` with `JOB_TIMEOUT` if nothing usable |
| Daily quota reached | Checked before any work | `429 AI_QUOTA_EXCEEDED`, UI says "You have reached the daily limit for AI summaries" |

All outcomes are persisted in `ai_summaries` with `status`, `error_code`, `attempts`, `latency_ms`, so failures are observable.

### 10.9 Response contract and provenance

```json
{
  "summary_id": "uuid",
  "patient_id": "uuid",
  "status": "completed",
  "cached": false,
  "cached_from": null,
  "generated_at": "2026-11-10T17:20:00Z",
  "progress": [
    {"step": "Opening the chart", "state": "done", "ms": 261, "note": "Ready"}
  ],
  "facts": {
    "provenance": "system_computed_from_patient_records",
    "ckd": {"established": "G3b", "egfr_category": "G3b", "uacr_category": "A3", "mismatch": false},
    "abnormal_results": [ {"test": "CREAT", "value": 1.9, "unit": "mg/dL", "flag": "high", "collected_at": "..."} ],
    "trends": { "CREAT": { "...stats": 0 }, "EGFR": { "...stats": 0 } }
  },
  "gaps": {
    "provenance": "rule_engine",
    "findings": [ {"code": "ALLERGY_STATUS_UNKNOWN", "severity": "medium", "kind": "missing", "message": "..."} ]
  },
  "ai": {
    "provenance": "ai_generated",
    "provider": "gemini", "model": "…", "prompt_version": "v1",
    "content": { "...LLM schema in 10.6...": 0 },
    "grounding_warnings": []
  },
  "sources": {
    "lab:EGFR:2026-10-21": {"type": "lab", "label": "eGFR, 21 Oct 2026", "tab": "labs", "target_id": "uuid"},
    "cond:3f2a9c": {"type": "condition", "label": "Type 2 diabetes mellitus with diabetic nephropathy", "tab": "conditions", "target_id": "uuid"},
    "enc:95acc": {"type": "encounter", "label": "Encounter, 20 Oct 2026", "tab": "encounters", "target_id": "uuid"}
  },
  "validation": {
    "schema_valid": true, "refs_total": 26, "refs_resolved": 26,
    "safety_flags": 0, "attempts": 1, "repaired": false
  },
  "error_code": null,
  "disclaimer": "AI-generated content for clinician review only. It is not a diagnosis or treatment recommendation. Verify against the source record."
}
```

`GET /ai/summaries/{sid}?include=context` also returns `context` (the minimized `context_snapshot`) for the "What the AI was given" panel. The list endpoint returns the same object without `context` and `progress`.

How the UI uses each part:

| Field | UI element |
|---|---|
| `facts` | "Calculated from the chart" panel: CKD strip, trend table, abnormal chips. Labeled **not written by the AI** |
| `gaps.findings` | "Missing or inconsistent information" panel, labeled **checked by rules, not by AI**, with severity |
| `ai.content` | AI narrative panel with the AI banner. Each section's `source_refs` render as chips |
| `sources` | Turns each ref into a readable chip label ("eGFR, 21 Oct 2026"). Clicking opens the Labs, Conditions or Medications tab, or an encounter dialog, using `tab` and `target_id` |
| `validation` | "26 of 26 sources found in the record", "Safety check: passed", and "Corrected once automatically" when `repaired` is true |
| `ai.model`, `prompt_version`, `validation.attempts` | Inside the collapsed "What the AI was given" panel, not in the main reading flow |
| `progress` | Stepper while `status = running` |
| `status = degraded` | Facts and gaps still shown; the narrative panel shows an unavailable notice with the disclaimer |

The `sources` map is built by ai-svc after validation, from the data it already holds. Refs that do not resolve never reach the client (they are stripped and counted in `grounding_warnings`).

- `provenance` is explicit at every section, so the frontend can render system facts, rule findings and AI narrative differently.
- The **disclaimer is injected by the server**, never by the model, so it can't be omitted or reworded.
- AI output is **never written into patient records**. It lives only in `ai.ai_summaries`. A clinician copying text into an encounter is a deliberate human act.

### 10.10 Cost, latency and rate control

| Mechanism | Effect |
|---|---|
| Cache by `context_hash` (+ model + prompt version) | Repeat requests with unchanged data return instantly at zero LLM cost. `?force=true` regenerates |
| Concurrency semaphore (`LLM_MAX_CONCURRENCY`) | Prevents stampeding the provider and burning free-tier quota |
| Per-user quota (count in `ai_summaries` per day) | Protects shared quota; returns `429` |
| Gateway rate limit on `/api/ai` | Coarse protection |
| Circuit breaker around provider | Fail fast during provider outages |
| Low `max_tokens`, compact context packet | Cost and latency |
| Async I/O throughout | One worker handles many concurrent waits on the LLM |

The `202` plus polling contract (§10.3) is already the default. Evolution path if one process stops being enough: move the runner behind a queue with a worker pool and replace polling with SSE. The API contract and the `progress` column do not change.

### 10.11 Prompt management

Prompts are files under `prompts/` with explicit versions (`v1`, `v2`). The version is stored on every summary and included in the cache key. Changing a prompt never silently changes the meaning of historical summaries.

### 10.12 Insights: deterministic worklist and dashboard

These endpoints live in ai-svc because it is the one service that already reads both the chart and the labs. They contain **no LLM call** and share the rule engine with the summary pipeline, so the dashboard, the list badge, the Overview alert and the summary's gap section can never disagree.

| Endpoint | Returns | Used by |
|---|---|---|
| `GET /insights/patients/{id}/gaps` | Findings for one patient (same shape as `gaps.findings`) | Overview "gaps found" alert |
| `GET /insights/worklist?attention=true` | `[{patient_id, reasons[]}]` for patients that need attention | Patient list filter and KPI |
| `GET /insights/dashboard` | KPIs, top attention rows with reasons, eGFR category distribution, abnormal results to review | Dashboard |

**Dashboard payload**

```json
{
  "kpis": {"patients": 10, "need_attention": 6, "critical_results": 1, "rapid_decline": 4},
  "attention": [
    {"patient_id": "uuid", "mrn": "PT-000109", "name": "Aditya Singh", "age": 61,
     "reasons": [{"severity": "danger", "text": "Critical potassium 6.2 mmol/L"},
                 {"severity": "danger", "text": "eGFR falling 7.4 per year"}]}
  ],
  "egfr_distribution": {"G1": 0, "G2": 3, "G3a": 2, "G3b": 2, "G4": 1, "G5": 1, "none": 1},
  "abnormal_results": [
    {"patient_id": "uuid", "name": "Aditya Singh", "test": "K", "value": 6.2, "unit": "mmol/L",
     "flag": "critical_high", "collected_at": "..."}
  ]
}
```

- **Draft encounters** (count and list) and **upcoming follow-ups** are not here. patient-svc owns them (`GET /encounters?...`), and the dashboard KPI for drafts comes from that call.
- **Abnormal results to review** shows the **latest** abnormal result per patient and test, critical first, at most two per patient and eight in total, so one very sick patient cannot fill the panel.
- **Attention ordering:** critical results first, then rapid decline, then high-severity gaps.
- **How it is computed.** ai-svc pages through the two bulk internal endpoints (§9), runs the pure rule functions in memory and aggregates. At clinic scale (hundreds to low thousands of patients) this is milliseconds of CPU plus two bulk reads.
- **Caching.** The aggregate is cached per process for `INSIGHTS_CACHE_TTL_S` (default 30 s). Data changes show up within that window. A manual refresh in the UI sends `Cache-Control: no-cache`.
- **PHI.** These responses go to the UI, so they include names. They are **never** part of any LLM context.
- **Scaling path.** When bulk reads stop being cheap, lab-svc and patient-svc publish change events through an outbox and ai-svc keeps its own materialized worklist. That is the first point where messaging is justified (ADR-005); it is not needed now.

---

## 11. API surface

All routes are served behind the gateway under `/api`. Each service also publishes OpenAPI at `/docs` and `/openapi.json`. Exported specs are committed to `docs/api/` for the submission.

### 11.1 auth-svc

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/auth/signup` | Register a clinician (behind `ENABLE_PUBLIC_SIGNUP`) | Public |
| POST | `/auth/login` | Login, returns access token and sets refresh cookie | Public |
| POST | `/auth/refresh` | Rotate refresh token, new access token | Cookie |
| POST | `/auth/logout` | Revoke token family | Cookie |
| GET | `/auth/me` | Current user (name, role) for the top bar | JWT |
| GET | `/.well-known/jwks.json` | Public keys | Public |

There are no admin routes.

### 11.2 patient-svc

| Method | Path | Description |
|---|---|---|
| GET | `/patients?q=&sex=&stage=&ids=&sort=&dir=&page=&size=` | List and search. Returns ID, name, age, sex, primary dx, established stage, last visit |
| POST | `/patients` | Create patient |
| GET | `/patients/{id}` | Demographics, history and summary counts (conditions, active meds, encounters) |
| PATCH | `/patients/{id}` | Update demographics, history, `allergy_status` or `established_ckd_stage`. Requires `version` |
| DELETE | `/patients/{id}` | Soft delete |
| GET/POST | `/patients/{id}/conditions` | List and add conditions |
| PATCH/DELETE | `/patients/{id}/conditions/{cid}` | Update, set primary, resolve |
| GET/POST | `/patients/{id}/medications` | List and add |
| PATCH | `/patients/{id}/medications/{mid}` | Update or discontinue (sets end date today) |
| GET/POST | `/patients/{id}/allergies` | List and add (also sets `allergy_status = has_allergies`) |
| DELETE | `/patients/{id}/allergies/{aid}` | Remove (last one removed returns status to `unknown`) |
| GET | `/patients/{id}/encounters?page=&size=` | Encounter history |
| POST | `/patients/{id}/encounters` | Create encounter as `draft` or `final`, with diagnoses and optional "add to problem list" in one transaction |
| GET | `/patients/{id}/encounters/{eid}` | Detail incl. vitals and diagnoses |
| PATCH | `/patients/{id}/encounters/{eid}` | Edit a **draft** only (`409` if final) |
| POST | `/patients/{id}/encounters/{eid}/finalize` | Lock the encounter |
| DELETE | `/patients/{id}/encounters/{eid}` | Soft-delete a **draft** only (`409` if final) |
| GET | `/encounters?status=draft&limit=` | Cross-patient drafts with patient name and MRN (dashboard) |
| GET | `/encounters?upcoming_followups=true&limit=` | Final encounters with a follow-up date today or later, soonest first (dashboard) |
| GET | `/internal/patients/{id}/basic` | **Internal**: existence, sex, DOB |
| GET | `/internal/patients/{id}/chart` | **Internal**: chart for AI |
| GET | `/internal/patients/charts?cursor=&limit=` | **Internal**: bulk chart export for the worklist |

### 11.3 lab-svc

| Method | Path | Description |
|---|---|---|
| GET | `/labs/tests?sex=` | Catalog: code, name, canonical unit, allowed units with factors, reference range for that sex, critical limits. Feeds the lab form preview |
| POST | `/labs/patients/{id}/reports` | Add a report with one or more results (date, lab, notes, value, unit) |
| GET | `/labs/patients/{id}/results?test=&from=&to=&flag=abnormal&page=&size=` | Historical results with flags, `value_original`, `unit_original` |
| GET | `/labs/patients/{id}/trends?tests=CREAT,EGFR&from=&to=` | Series and stats for charts |
| GET | `/labs/patients/{id}/latest` | Latest per test, eGFR category, UACR category |
| GET | `/labs/summary?patient_ids=` | **Batch** (max 50 ids): latest eGFR, flag, category, sparkline points, critical and rapid flags. Feeds list rows |
| POST | `/labs/results/{rid}/correct` | Append a correction (supersedes) |
| GET | `/internal/labs/patients/{id}/…` | **Internal** equivalents for ai-svc |
| GET | `/internal/labs/status?cursor=&limit=` | **Internal**: bulk `patient_lab_status` for the worklist |

### 11.4 ai-svc (summary)

| Method | Path | Description |
|---|---|---|
| POST | `/ai/patients/{id}/summary?force=` | Always `202` with `summary_id` and `status: running`. `force=true` skips the cache |
| GET | `/ai/summaries/{sid}?include=context` | Poll status and progress; returns the full summary, optionally with the minimized context |
| GET | `/ai/patients/{id}/summaries` | History (completed and degraded only) |

### 11.4b ai-svc (insights, no LLM)

| Method | Path | Description |
|---|---|---|
| GET | `/insights/patients/{id}/gaps` | Missing and inconsistent findings for one patient |
| GET | `/insights/worklist?attention=true` | Patient ids that need attention, with reasons |
| GET | `/insights/dashboard` | KPIs, attention rows, eGFR distribution, abnormal results (§10.12) |

### 11.5 Status codes used consistently

`200/201` success · **`202` summary started** · `204` delete · `400` malformed · `401` unauthenticated · `403` forbidden · `404` not found · `409` version conflict or immutable resource (editing or deleting a final encounter) · `422` validation · `429` rate limit or AI quota · `502` upstream unavailable · `504` upstream timeout.

### 11.6 List endpoint parameters

| Endpoint | Sortable by | Filters |
|---|---|---|
| `GET /patients` | `name`, `mrn`, `age`, `dx`, `visit` | `q` (name or MRN), `sex`, `stage` (established stage, or `none`), `ids` (from the worklist) |
| `GET /labs/patients/{id}/results` | `collected_at` (default, newest first) | `test`, `from`, `to`, `flag=abnormal` |
| `GET /encounters` | `encounter_date` or `follow_up_date` depending on the mode | `status`, `upcoming_followups` |

All list endpoints return `{items, page, size, total}` (§12). The patient list's latest-eGFR column is filled by a second call (§5.6) and is not sortable.

---

## 12. Cross-cutting concerns

| Concern | Convention |
|---|---|
| **Error envelope** | `{"error": {"code": "VALIDATION_ERROR", "message": "...", "details": [...], "request_id": "..."}}` — same shape from gateway and every service. Stable machine-readable `code`s |
| **Validation** | Pydantic at the edge; DB CHECK/UNIQUE as the last line of defense; mapping of DB integrity errors to `409/422` |
| **Pagination** | `page`, `size` (max 100) with `{items, page, size, total}`. Keyset pagination is an upgrade for very large tables |
| **Config** | `pydantic-settings`, 12-factor env vars, `.env.example` |
| **Logging** | Structured JSON, includes `request_id`, `user_id`, service, route template, latency. No PHI |
| **Health** | `/health` (liveness), `/ready` (DB reachable, migrations at head) |
| **Metrics** | `/metrics` (Prometheus format) on each service: request count/latency, LLM latency/tokens/failures, tool call counts |
| **Time** | All timestamps `timestamptz`, UTC in storage/API, ISO-8601; UI localizes |
| **IDs** | UUIDv4 (or v7) PKs; human-readable `mrn` separate from PK |
| **Migrations** | Alembic per service; run on container start (or init job), forward-only in practice |
| **DB sessions** | SQLAlchemy 2.x async, session-per-request dependency, explicit transaction at the service layer |
| **Idempotency** | PUT/DELETE naturally idempotent; POST idempotency keys are listed under future work |
| **Dependency injection** | FastAPI `Depends` for config, sessions, auth, HTTP clients, LLM provider — makes tests trivial |
| **API versioning** | Gateway prefix `/api` with `/v1` reserved; avoid breaking changes inside a version |

---

## 13. Scalability and production readiness

### 13.1 Why this design scales

| Dimension | How |
|---|---|
| **Compute** | Every service is stateless (no in-process session state; identity in JWT; state in Postgres). Run N replicas behind the gateway; services scale independently (for example more ai-svc replicas if LLM wait dominates, more auth-svc for argon2 CPU) |
| **Auth** | JWT verified locally via cached JWKS. No per-request dependency on auth-svc, so auth load does not grow with traffic |
| **I/O concurrency** | Async FastAPI + `httpx.AsyncClient` + async SQLAlchemy: a worker handles many concurrent waits (especially the slow LLM) |
| **Database reads** | Targeted indexes (§5); trigram search; denormalized `patient_id, collected_at` for trends; read replica can serve list/search/trends |
| **Database writes** | Small, single-transaction writes; append-only labs; no cross-service transactions to coordinate |
| **Growth of lab data** | Time-partition `lab_results` (by `collected_at`) when row counts demand it; index design already matches partition pruning |
| **Connections** | Per-service pools sized explicitly; put **PgBouncer** in front when replica count grows |
| **Isolation of failure** | AI failure cannot take down charting; lab outage does not block patient CRUD; timeouts + bounded retries + circuit breaker stop cascades |
| **Data isolation growth** | Database-per-service → move a database to its own server by changing a connection string |
| **LLM cost/quota** | Cache, semaphore, per-user quota, compact context (tool calling reduces prompt size on large histories) |

### 13.2 Known bottlenecks and what we would do

| Bottleneck | Mitigation now | Mitigation at scale |
|---|---|---|
| LLM latency and quota | cache, concurrency limit, timeouts, degraded mode | async job (202 + polling/SSE) with queue + workers; multiple providers behind the adapter |
| Gateway in-memory rate limit | OK for one instance | Redis-backed limiter; multiple gateway replicas behind a load balancer |
| Gateway as single entry | Stateless, restartable | Replicate behind L4/L7 LB |
| Postgres single instance | Pooling, indexes | Managed HA Postgres, read replicas, PgBouncer, per-service instances |
| Patient search | `pg_trgm` GIN | Dedicated search index (OpenSearch) only if volumes justify |
| Trend queries on huge series | index + range filter | partitioning, downsampling for long ranges |
| Worklist and dashboard compute (all patients, every refresh) | Bulk paged reads, in-memory pure rules, 30 s cache | Materialized worklist in ai_db fed by change events (outbox) |
| List rows need lab data | One batch read of `patient_lab_status` per page (≤ 50 ids) | Same; the read model is already the scalable form |

### 13.3 Production-readiness checklist (implemented vs described)

| Area | In this repo | Described for real deployment |
|---|---|---|
| Containerization | Dockerfile per service (multi-stage, non-root), compose with healthchecks and `depends_on: service_healthy` | Orchestrator (Kubernetes/ECS), rolling deploys |
| Config/secrets | Env + mounted key files | Secret manager (Vault/KMS) |
| Observability | JSON logs, request IDs, `/metrics`, health | Central logs, tracing (OpenTelemetry), dashboards, alerts on error rate, p95 latency, LLM failures |
| Security | Items in §7 | WAF, TLS everywhere, SAST/dependency scanning, pen test |
| Data protection | Synthetic data, no PHI in logs, audit table | Encryption at rest, backups with tested restore, retention policy, RBAC review |
| Reliability | Timeouts, bounded retries, breaker on LLM, graceful degradation | SLOs, load tests, chaos tests |
| CI | Lint (ruff), type check (mypy optional), tests, build | Image scanning, migration checks, blue/green |
| Compliance | Not applicable to synthetic data | HIPAA/DPDP-style controls, DPA with LLM vendor, or local model |

---

## 14. Design patterns used and why

| Pattern | Where | Why it earns its place |
|---|---|---|
| **API Gateway** | Custom gateway | Single entry point; centralize authentication, CORS, rate limit, request IDs |
| **Database-per-service** | Separate databases + roles on one instance | Engine-enforced ownership (cross-database queries are impossible); independent migrations and deploys without extra infrastructure |
| **Bounded contexts (DDD)** | The four services | Boundaries follow consistency and ownership |
| **Layered architecture** (router → service → repository) | Every service | Testable domain logic; HTTP and SQL stay at the edges |
| **Repository** | Data access layer | Swap/mocking persistence; keeps SQL out of services |
| **DTO / schema separation** | Pydantic schemas vs SQLAlchemy models | API contract decoupled from table design |
| **Dependency Injection** | FastAPI `Depends` | Config, DB, auth, LLM provider injected → easy tests |
| **Strategy / Adapter** | `LLMProvider` implementations | Swap Gemini/Groq/Ollama/Mock via config |
| **Registry / Command** | Tool registry for LLM tool calls | Controlled, validated, auditable tool execution |
| **Pipeline / Orchestrator** | `SummaryOrchestrator` | Explicit ordered steps with clear failure handling |
| **Anti-corruption layer** | LLM output validation | Untrusted external output cannot corrupt internal model |
| **API Composition** | Cross-service reads in ai-svc, Angular parallel calls | Replaces cross-DB joins |
| **Snapshot** | Reference range and flag on results; context snapshot on summaries | Historical correctness; reproducibility |
| **Soft delete + audit columns** | Clinical tables | Record integrity, no dangling cross-service references |
| **Optimistic locking** | `patients.version`, `encounters.version` | Prevent lost updates between clinicians |
| **State machine** | Encounter `draft → final` | Enforced immutability |
| **Timeout + bounded retry + circuit breaker** | Internal HTTP and LLM calls | Failure isolation without a heavy framework |
| **Bulkhead** | Connection pools, LLM semaphore | One slow dependency cannot exhaust all resources |
| **Cache-aside (content hash)** | AI summaries | Cost/latency control with correctness (hash includes data, prompt, model) |
| **Pure core / functional core** | CKD, flags, trends, gap rules, attention rule | Deterministic, easily tested clinical logic |
| **Local read model (projection)** | `patient_lab_status` in lab_db | Cheap list and dashboard reads; written in the same transaction, so no eventual-consistency problem |
| **Async request-reply (202 + polling)** | AI summary | Short HTTP requests, real progress, no gateway timeout risk |
| **Hydration of references** | `sources` map on summaries | The model cites ids; the server turns them into labels and links |
| **Client-side preview with shared test vectors** | Lab form flag and unit conversion | Instant feedback without a round trip, no drift from the server |
| **Feature flag** | `LLM_TOOLS_ENABLED`, `ENABLE_PUBLIC_SIGNUP` | Safe rollout and graceful capability fallback |
| **12-factor config** | All services | Same image across environments |

**Patterns deliberately not used:** Saga, event sourcing, CQRS, message broker, service mesh, distributed cache, GraphQL federation, shared domain library. Reasons in §19.

---

## 15. Frontend architecture (Angular)

### 15.1 Structure

```
frontend/src/app/
  core/             auth service, http interceptors, guards, api clients, error handling, toast service
  shared/           reusable UI components, pipes, directives, models, chart helpers
  features/
    auth/           login, signup
    dashboard/      dashboard page and its panels
    patients/       list, detail shell, overview, conditions, meds-allergies
    encounters/     list, view dialog, encounter form
    labs/           results table, add-report form, trend charts, ckd strip
    ai-summary/     summary view, progress stepper, history
  app.routes.ts     lazy-loaded feature routes
```

Routes: `/login`, `/signup`, `/dashboard` (home), `/patients`, `/patients/:id/{overview|conditions|meds|encounters|labs|ai}`. Sidebar items: Dashboard, Patients. The top bar has global patient search, which navigates to `/patients?q=`, and the signed-in clinician with sign-out.

- **Standalone components**, **lazy-loaded** feature routes, **signals** for local state; no NgRx (state is per-screen and server-driven).
- **Typed API clients** per backend service, with DTO interfaces mirroring OpenAPI.
- **Reactive Forms** with typed controls and shared validators for vitals and labs.

### 15.2 Core mechanics

| Concern | Approach |
|---|---|
| Auth | Access token in memory (not localStorage). Refresh via httpOnly cookie. `AuthInterceptor` attaches the token; on `401` it performs a **single-flight refresh** (concurrent requests wait on one refresh) then retries once |
| Guards | `authGuard` for all routes except `/login` and `/signup`. No role guard (one role) |
| Errors | `ErrorInterceptor` maps the error envelope to user-friendly messages and shows `request_id` for support |
| Loading, empty, error | Standard components. **Every panel owns its state**: on the dashboard and the list, one failed call shows an error inside that panel only |
| Composed screens | Parallel calls with per-panel signals (§3.2b). List rows render first; the eGFR and sparkline cells show a skeleton until `/labs/summary` returns |
| Search | Debounced 300 ms; the URL query string is the source of truth so a search can be bookmarked and the back button works |
| AI summary | `POST` (`202`), then poll `GET /ai/summaries/{id}` every second with `timer` + `switchMap` until a terminal status. Polling stops on route leave. A cache hit resolves through the same polling path with `cached: true` and shows an info message |
| Lab form preview | The form loads `GET /labs/tests?sex=` once and computes unit conversion and the flag locally as the user types. The server recomputes and is authoritative. **Shared JSON test vectors** run in both pytest and Jest so the two implementations cannot drift (ADR-019) |
| Concurrency | A `409` on a patient `PATCH` shows "This record was changed by someone else" with a Reload action |
| Confirmations | `ConfirmDialog` for discontinue medication, remove allergy, delete draft, finalize encounter |
| Feedback | Toast service for success and info messages; field-level messages from `422` details |

### 15.3 Reusable components

| Component | Used for |
|---|---|
| `DataTable` (sort, pagination, empty state) | Patient list, encounters, lab results |
| `SearchBox` (debounced) | Global and list search |
| `PageHeader`, `Card`, `Tabs`, `KpiStrip` | Layout; KPI strip on dashboard and list |
| `StatusBadge` | Encounter status, condition status |
| `LabFlagChip` | Low, high, critical with icon and text |
| `CkdStageBadge` | Established stage vs computed eGFR category, with mismatch warning |
| `CkdStrip` | Established stage, eGFR category, UACR category side by side |
| `Sparkline` | eGFR trend in list rows (Chart.js with axes hidden, or a tiny SVG) |
| `LabTrendChart` | Creatinine and eGFR over time. Reference band (creatinine), KDIGO stage bands (eGFR), hover tooltip, last-point label |
| `TrendStats` | Direction, change, per-year slope and rapid-decline chips under a chart |
| `StageBars` | "Patients by eGFR category" horizontal bars on the dashboard |
| `VitalsForm` | Encounter vitals with range validation |
| `AttentionList` | Dashboard needs-attention rows with reason chips |
| `AiSummaryPanel` | Distinct "AI-generated" presentation + disclaimer |
| `SourceChip` | Readable citation chip; opens the record |
| `ProgressStepper` | AI pipeline steps with state and timing |
| `ConfirmDialog`, `Modal`, `Toast`, `ErrorBanner`, `Skeleton` | Common UX |

### 15.4 Key screens and the APIs behind them

Every row below exists in the prototype. "Calls" are the API requests the screen makes.

| Screen | What the user can do | Calls |
|---|---|---|
| **Sign in / Sign up** | Sign in, create an account, see password rules | `POST /auth/login`, `POST /auth/signup` |
| **Dashboard** | See KPIs; open a patient from Needs attention; hover the eGFR category bars; open a patient's labs from an abnormal result; open a follow-up or finish a draft; start a new patient | `GET /insights/dashboard`, `GET /encounters?status=draft`, `GET /encounters?upcoming_followups=true` |
| **Patient list** | Search by name or ID, filter by sex, established stage and Needs attention, sort by name, ID, age, diagnosis or last visit, page, open a chart, create a patient | `GET /patients`, `GET /labs/summary?patient_ids=`, `GET /insights/worklist` (attention filter), `POST /patients` |
| **Patient header** | See ID, age, sex, DOB, allergy chip, established stage vs eGFR category with a mismatch chip; start an encounter or lab report; open AI summary | `GET /patients/{id}`, `GET /labs/patients/{id}/latest` |
| **Overview** | Read the **Kidney function** panel (eGFR and creatinine charts with CKD strip); edit demographics (version-checked); read history; see recent encounters; see the gap alert | `GET /labs/patients/{id}/trends`, `/latest`, `GET /patients/{id}`, `PATCH /patients/{id}`, `GET /insights/patients/{id}/gaps` |
| **Conditions** | Set the established CKD stage; add a condition; make one primary; resolve or reactivate | `PATCH /patients/{id}`, `GET/POST/PATCH /patients/{id}/conditions` |
| **Medications and allergies** | Add and discontinue medications (with confirmation); show or hide discontinued; add and remove allergies; mark no known allergies | `GET/POST/PATCH /patients/{id}/medications`, `GET/POST/DELETE /patients/{id}/allergies`, `PATCH /patients/{id}` |
| **Encounters** | List and view past encounters; create with vitals, symptoms, exam, assessment, diagnoses (optionally added to the problem list) and follow-up; save as draft or finalize; edit or delete a draft | `GET/POST /patients/{id}/encounters`, `GET/PATCH/DELETE /patients/{id}/encounters/{eid}`, `POST .../finalize` |
| **Labs** | See the CKD classification grid and latest results; filter the date range; toggle eGFR stage bands; read two trend charts with stats; filter history by test and abnormal-only; page; add a lab report with live flag and unit conversion | `GET /labs/patients/{id}/latest`, `/trends`, `/results`, `GET /labs/tests`, `POST /labs/patients/{id}/reports` |
| **AI summary** | Generate or regenerate; watch progress; read calculated facts, rule findings and the AI narrative; open a source; copy the narrative; read the disclaimer; see what the AI was given; open an earlier summary | `POST /ai/patients/{id}/summary`, `GET /ai/summaries/{sid}?include=context`, `GET /ai/patients/{id}/summaries` |

The prototype also has a collapsed **Demo options** control on the AI tab that simulates an invalid response, a timeout, a rate limit and an upstream failure. It exists only to demonstrate the error handling required by the PS. In the real app the same paths are exercised by `MockProvider` scenarios in tests (§16) and are not a user-facing control.

### 15.5 UX decisions that matter in a clinical tool
- Abnormal values use color **and** icon/text (not color alone) for accessibility.
- AI content never appears inline in the patient record views; it is only inside the AI panel. The Overview shows calculated charts and rule findings only.
- The disclaimer is always visible with the AI content, not hidden behind a tooltip.
- Three provenance labels are always visible on the AI tab: **Calculated from the chart**, **Checked by rules, not by AI**, **AI-generated narrative**.
- Missing data is shown as "Not documented" or "None recorded", never as blank or zero.
- Chart tooltips show value, flag and date; the latest point is labeled directly.
- Trend chips say "Insufficient data (needs 3+ results)" instead of showing a direction from two points.
- Errors say what happened and what to do; they do not apologize and they do not show internal codes (the request id is available for support).

### 15.6 Prototype versus the Angular build
The prototype is one HTML file with a simulated backend. Its charts are hand-built SVG so it works offline. The Angular app uses **Chart.js (`ng2-charts`) with `chartjs-plugin-annotation`** for the reference band and KDIGO stage bands. Behavior, copy and data shapes in this document are taken from the prototype and are the acceptance reference for the Angular screens.

---

## 16. Testing strategy

Test the logic that carries clinical and architectural risk; keep the rest lean.

| Layer | What | Tools |
|---|---|---|
| **Unit (highest priority)** | CKD/eGFR/UACR classification incl. every boundary; flagging incl. missing range; unit conversion; trend math (slope, <3 points, rapid decline); gap rules including each severity and the attention rule; LLM output validation (invalid JSON, schema violation, bad citations, forbidden phrases); tool argument validation and `patient_id` binding; `sources` hydration; an import-boundary test that `insights/` never imports `llm/` | pytest |
| **Service/API** | Per service against a real Postgres (a throwaway test database per service) using `httpx.AsyncClient`: auth flows, JWT/role enforcement, patient CRUD + search, primary-diagnosis uniqueness, encounter immutability, optimistic-lock conflict, lab report creation with snapshot flags and `patient_lab_status` updated in the same transaction (and rebuildable), draft delete vs final `409`, list filters (`ids`, `stage`, sort keys), `/labs/summary` batch limit, error envelope | pytest + testcontainers or compose test DB |
| **AI pipeline** | `MockProvider` scenarios: success, tool-call round trip, invalid output → repair → success, repair fails → degraded, timeout → degraded, rate-limited, cache hit, upstream down → `failed` and hidden from history, `202` then poll through every `progress` step, reaper marks a stuck `running` row `failed` | pytest |
| **Insights** | Worklist and dashboard against the ten seeded patients: expected attention ids and reasons, abnormal-results capping (2 per patient, 8 total), eGFR distribution, cache TTL and `no-cache` | pytest |
| **Shared vectors** | One JSON file of lab cases (value, unit, sex, expected canonical value and flag) consumed by both the pytest suite and the Jest suite for the lab form preview | pytest + Jest |
| **Contract** | Internal endpoints used by lab-svc and ai-svc: response shape tests on both sides (lightweight schema checks) | pytest |
| **Frontend** | Component tests for `LabFlagChip`, `CkdStageBadge`, `CkdStrip`, `Sparkline`, `StageBars`, `AiSummaryPanel`, `SourceChip`, `ProgressStepper` (polling stops on terminal status and on route leave), interceptor refresh logic, search debounce, per-panel error isolation on the dashboard | Jest/Karma |
| **E2E smoke** | Login → dashboard → search patient → create encounter → add labs → view chart → generate AI summary (mock) | Playwright (optional, one flow) |

CI runs lint + unit + API tests on every push.

---

## 17. Deployment, repo layout and local setup

### 17.1 Repository layout

```
nephro-emr/
  README.md
  docker-compose.yml
  .env.example
  Makefile
  docs/
    HLD.md                 ← this document
    api/                   exported OpenAPI specs (one per service)
    db/                    schema diagrams, DDL dump
    screenshots/           UI screenshots / recording link
    prototype/             nephrocare-emr-platform.html (acceptance reference for the UI)
  infra/
    postgres/init-databases.sh
    keys/                  (gitignored) JWT keys; generate-keys script
  libs/
    common/                infra-only: JWT verify, error envelope, request-id/logging middleware,
                           pagination, resilient HTTP client
  gateway/                 custom gateway
  services/
    auth/      app/ alembic/ tests/ Dockerfile
    patient/   app/ alembic/ tests/ Dockerfile  (+ seed/)
    lab/       app/ alembic/ tests/ Dockerfile  (+ seed/: tests, ranges, results)
    ai/        app/ (insights/ summary/ llm/ tools/ ...) alembic/ tests/ Dockerfile
  frontend/                Angular app
```

`libs/common` contains **infrastructure code only**. Domain models never go in a shared library; that would force all services to deploy together (a distributed monolith).

### 17.2 docker-compose (summary)

| Container | Port | Notes |
|---|---|---|
| `postgres` | internal only | `init-databases.sh` creates the four databases and roles; named volume; healthcheck |
| `auth-svc`, `patient-svc`, `lab-svc`, `ai-svc` | internal only | Wait for DB healthy, run migrations, healthcheck on `/health` |
| `gateway` | **8080 (published)** | The only public API port |
| `frontend` | 4200 (dev) / 80 (nginx build) | Calls gateway |

If you reuse your existing Postgres container, run `init-databases.sh` against it once and point each service's `DATABASE_URL` at its own database.

### 17.3 Environment variables (excerpt)

```
# shared
LOG_LEVEL=INFO
JWT_ISSUER=nephro-auth        JWT_AUDIENCE=nephro-api
JWKS_URL=http://auth-svc:8000/.well-known/jwks.json

# per-service DB
AUTH_DATABASE_URL=postgresql+asyncpg://auth_svc:***@postgres:5432/auth_db
PATIENT_DATABASE_URL=postgresql+asyncpg://patient_svc:***@postgres:5432/patient_db
LAB_DATABASE_URL=postgresql+asyncpg://lab_svc:***@postgres:5432/lab_db
AI_DATABASE_URL=postgresql+asyncpg://ai_svc:***@postgres:5432/ai_db

# auth
ENABLE_PUBLIC_SIGNUP=true     ACCESS_TOKEN_TTL_MIN=15    REFRESH_TOKEN_TTL_DAYS=7
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem

# ai
LLM_PROVIDER=mock             # mock | gemini | groq | ollama
LLM_API_KEY=...               LLM_MODEL=...
LLM_TOOLS_ENABLED=true        LLM_MAX_TOOL_ITERATIONS=4
LLM_TIMEOUT_S=30              LLM_MAX_CONCURRENCY=4      AI_DAILY_QUOTA_PER_USER=50
LLM_JOB_TTL_S=120             # reaper marks stuck running summaries failed
INSIGHTS_CACHE_TTL_S=30       NO_RECENT_LABS_DAYS=180    EGFR_DISCORDANCE_TOLERANCE=12
EGFR_STABLE_BAND=2            CREAT_STABLE_BAND=0.1      EGFR_RAPID_DECLINE=-5
```

### 17.4 Local run (target README flow)

```bash
cp .env.example .env
./infra/keys/generate-keys.sh
docker compose up --build
# migrations + seed run automatically; then:
open http://localhost:4200          # UI
open http://localhost:8080/docs     # gateway-exposed docs (or each service's /docs in dev)
make test                           # unit + API tests
```

Demo clinicians are created by the seed (documented in README): `dr.rao@nephrocare.demo` and `dr.malhotra@nephrocare.demo`. `LLM_PROVIDER=mock` works with no API key.

---

## 18. Synthetic data plan

All data is invented. No real names, MRNs, or records. The ten patients below match the prototype, so every screen, rule and AI path has a fixture.

| MRN | Patient | Established stage | Scenario it exists to show |
|---|---|---|---|
| PT-000101 | Ramesh Kulkarni, 67 M | G3b | **Rapid eGFR decline**, albuminuria A3, penicillin allergy, one **draft encounter**, a lab report entered in µmol/L (unit conversion example). The main demo patient |
| PT-000102 | Sunita Verma, 58 F | G3a | Stable hypertensive CKD. A clean baseline with few findings |
| PT-000103 | Arjun Mehta, 45 M | G2 | **Allergy status unknown**, a final encounter with **no vitals**, IgA nephropathy. Shows missing-data findings |
| PT-000104 | Fatima Sheikh, 72 F | G4 | Advanced CKD with steady decline |
| PT-000105 | Vikram Rao, 39 M | none | **Post-AKI recovery** (improving trend), no medications documented |
| PT-000106 | Lakshmi Iyer, 63 F | G4 | **CKD stage mismatch**: established G4 but latest eGFR is G3b |
| PT-000107 | Mohan Das, 55 M | G2 | **No recent labs** (older than 180 days) and **eGFR vs creatinine discordance** |
| PT-000108 | Priya Nair, 50 F | none | **Near-empty chart**: no labs, no diagnosis, no visits |
| PT-000109 | Aditya Singh, 61 M | G5 | **Critical potassium** and critical creatinine, urgent follow-up |
| PT-000110 | Kavita Joshi, 34 F | none | Lupus nephritis, **no established stage** despite persistently low eGFR, a **medication past its end date** |

| Dataset | Content |
|---|---|
| Users | 2 clinicians. No admin |
| Conditions | Nephrology diagnoses plus comorbidities (hypertension, type 2 diabetes, anemia of CKD, hyperlipidemia), one primary each where documented |
| Medications / allergies | Realistic lists; some patients with `allergy_status = unknown`, some `nka`, some with allergies |
| Encounters | 0 to 4 per patient, mix of draft and final, follow-up dates spread over the next weeks so the dashboard list is populated |
| Labs | Up to ~60 results per patient over 1 to 2 years for all 8 tests; creatinine derived from eGFR with CKD-EPI 2021 so the two agree, except where a discordance is intended |
| Expected worklist | 6 of 10 need attention (Aditya, Ramesh, Fatima, Kavita, Lakshmi, Priya) with reasons as in the dashboard. This is asserted in an insights test |

The deliberate edge cases make the demo showcase the "missing or inconsistent information" requirement and give tests realistic fixtures.

---

## 19. Decision log (ADRs)

### ADR-001: Microservices, four of them
**Context:** The assignment is small, but the team chose microservices.
**Decision:** auth, patient, lab, ai — split on ownership and failure domain.
**Why:** Each has distinct data, rules and failure behavior. Fewer services (modular monolith) would also be valid; more would be a distributed monolith.
**Consequence:** Operational overhead is accepted deliberately; mitigated by shared infra library and a single compose file.

### ADR-002: Patients and encounters stay together
**Why:** Same consistency boundary, written together, ACID transaction between encounter diagnoses and the problem list. The PS itself lists encounters under patient management.
**Consequence:** Internal modular seam retained for a future split.

### ADR-003: One Postgres instance, one database per service (with per-service roles)
**Alternatives:** shared database and tables (rejected: hidden coupling, no ownership, ai-svc could read password hashes); schema per service (lighter, but isolation depends on getting grants right and cross-schema joins stay technically possible); one Postgres instance per service (strongest, overkill now).
**Decision:** Separate databases on a single instance. `CONNECT` is revoked from `PUBLIC` and granted only to the owning role.
**Why:** PostgreSQL cannot join across databases, so ownership is enforced by the engine, not by convention. Each service gets a clean default schema and independent migrations. Moving a database to its own server later is a connection-string change.
**Consequences:** No cross-database joins or FKs by design (cross-service data goes through APIs, §5.6). Extensions are installed per database. Connection pools share the instance's `max_connections`, so pool sizes are explicit and PgBouncer is added when scaling. Slightly more init and backup plumbing.

---

### ADR-004: JWT RS256 with JWKS, refresh-token rotation
**Why:** Only auth-svc can mint tokens; everything else verifies locally; no per-request auth call; refresh rotation limits stolen-token damage.
**Consequence:** Needs key management and `kid` rotation.

### ADR-005: No saga, no broker
**Why:** Every write touches one service's data. Cross-service interaction is read-only. No distributed transaction exists to compensate.
**Revisit when:** a single user action must durably change two services (for example creating an encounter that also places a lab order), or work must happen asynchronously (for example ingesting analyzer feeds). Then: **transactional outbox + events** (choreography), not a heavy orchestrator.

### ADR-006: Synchronous REST for internal calls
**Why:** Simple, debuggable, sufficient. Resilience via timeouts, bounded GET retries, breaker where it matters (LLM).
**Alternative considered:** gRPC (type safety, performance) — unnecessary for this payload size and adds tooling cost.

### ADR-007: Deterministic first, LLM second
**Why:** Trust and safety. Numbers, flags, trends and gaps must be reproducible and testable. The LLM adds language, not facts.
**Consequence:** Slightly more code (rule engine, trend math) but dramatically safer and testable; enables graceful degradation.

### ADR-008: Tool calling is read-only, patient-bound, bounded, and optional
**Why:** Gains: smaller prompts, scalable to long histories, auditable evidence trail. Risks: latency, nondeterminism, model support, injection.
**Decision:** Hybrid — always provide a baseline context packet (required by the PS), allow bounded read-only drill-down tools, flag-gated with single-shot fallback.
**Consequence:** Same output schema either way; `llm_tool_calls` gives audit.

### ADR-009: Lab ranges and flags are snapshotted; results are append-only
**Why:** Clinical results must be interpretable as they were at the time; corrections should be traceable, not overwritten.

### ADR-010: Soft delete for clinical data
**Why:** Record integrity and no dangling UUID references across services.

### ADR-011: LLM output is validated, grounded, and never stored in clinical records
**Why:** Prevents hallucinated content from becoming part of the chart; satisfies "distinguish AI-generated information from original records".

### ADR-012: Thin custom gateway
**Why:** Cross-cutting edge concerns in one place; business logic stays in services so the gateway never becomes a bottleneck for change.

### ADR-013: Python FastAPI (async)
**Why:** Fast to build, strong typing with Pydantic, auto OpenAPI (feeds the API documentation requirement), async I/O ideal for LLM waits. (.NET would also satisfy the PS preference; the PS allows free choice.)

### ADR-014: Chart.js (ng2-charts) with annotation plugin
**Why:** Lightweight, well-supported in Angular, and the annotation plugin gives clean reference-range bands, which matters for lab trends.

### ADR-015: `patient_lab_status` read model in lab-svc
**Context:** The list, the dashboard and the worklist need the latest eGFR, the trend and the critical and rapid flags for many patients at once.
**Alternatives:** compute from `lab_results` on every read (a trend computation per row); cache in the browser; a separate reporting service.
**Decision:** lab-svc keeps a small per-patient summary table, updated in the same transaction as each report or correction and rebuildable from `lab_results`.
**Why:** List rows cost one indexed read. Because the write is local and transactional there is no eventual consistency to explain. It is lab data, so lab-svc owns it.
**Consequence:** One more table and an update step on every write, covered by a rebuild test.

### ADR-016: Deterministic insights live in ai-svc and never call the LLM
**Context:** The dashboard, the list attention filter and the Overview gap alert need the same rules as the AI summary's gap section.
**Alternatives:** a fifth `insights-svc` (more moving parts for one module); put the rules in the gateway (breaks "thin"); duplicate the rules in each service (drift).
**Decision:** The rule engine and worklist are an `insights/` package in ai-svc with its own routes. A test forbids imports from `llm/`.
**Why:** ai-svc already composes patient and lab data, and one rule engine serves every screen. Insights stay up when the LLM is down.
**Consequence:** ai-svc's name undersells its role; the module boundary and routes (`/insights`) make the split explicit. If it grows, `insights/` can become its own service without changing the API.

### ADR-017: AI summary is asynchronous (202 + polling) with persisted progress
**Context:** The UI shows live pipeline steps and a summary can take many seconds.
**Alternatives:** one blocking request (no progress, long timeouts, and no way to answer a cache hit faster than the gather); SSE or WebSocket (more infrastructure); a queue and workers (not needed yet).
**Decision:** `POST` always returns `202` with a summary id. A background task in ai-svc updates `progress`; a cache hit resolves through the same path. The UI polls. A reaper fails stuck jobs.
**Why:** Short requests, honest progress, no timeout cliff, and the same contract survives a later move to a queue and SSE.
**Consequence:** A crash loses in-flight work (the user retries); `running` rows need the reaper.

### ADR-018: One role, no admin
**Context:** The product is used by a nephrologist. The PS has no administration requirement.
**Decision:** Remove the admin role, user-management endpoints and admin screens. Keep auth-svc, sign-in, sign-up (flagged) and the `role` claim.
**Why:** Less surface to build, secure and explain. The claim stays, so adding a role later does not change the token format or the services.
**Consequence:** Accounts are created by signup (demo) or a seed or invite script (production).

### ADR-019: Lab form preview runs in the browser, validated by shared test vectors
**Context:** The form shows the flag and the converted value as the user types.
**Alternatives:** call the server on every keystroke (latency, load); trust a second implementation without tests (drift).
**Decision:** The form downloads the test catalog once and computes locally. The server remains authoritative and recomputes on save. One JSON file of cases is run by both pytest and Jest.
**Consequence:** Two implementations of a small function, kept honest by one shared fixture.

### ADR-020: Cross-service fields are not server-side sort keys
**Context:** The prototype's list shows latest eGFR, which lives in lab-svc.
**Decision:** The list sorts server-side only by fields patient-svc owns. The eGFR column is display-only (filled by a batch call). The "sickest first" need is met by the Needs attention filter and the dashboard.
**Why:** Sorting one page by another service's value is misleading; sorting everything needs a cross-service merge that this scale does not justify.
**Consequence:** The eGFR column header is not sortable. If it ever must be, add a `latest_egfr` projection in patient-svc fed by events (outbox).

---

## 20. Known simplifications and future work

| Area | Current | Next step |
|---|---|---|
| Signup | Open (flag) | Invite script or federated sign-in, email verification, MFA |
| Gateway rate limit | In-memory | Redis |
| AI generation | In-process async task, `202` + polling | Queue + worker pool, SSE instead of polling |
| Worklist and dashboard | Computed on demand from bulk reads, 30 s cache | Materialized worklist fed by change events (outbox) |
| List sort by latest eGFR | Not supported (ADR-020) | `latest_egfr` projection in patient-svc |
| Idempotency | Natural only | `Idempotency-Key` for POST (labs, encounters) |
| Lab ingestion | Manual entry | HL7/FHIR `Observation` import, analyzer feed (the point where an outbox/event becomes justified) |
| Observability | Logs + metrics | Tracing (OpenTelemetry), dashboards, alerting |
| Data protection | Synthetic only | Encryption at rest, backup/restore drills, retention policy |
| LLM | Free tier / mock | Local model (Ollama) or enterprise provider with DPA for real PHI |
| Search | `pg_trgm` | Search index if scale demands |
| eGFR | Entered/reported value | Optional computed CKD-EPI 2021 display alongside reported value |
| Authorization | Role-based | Care-team / patient-assignment-based access (ABAC) |

---

## 21. Submission checklist

| # | PS requirement | Artifact | Status |
|---|---|---|---|
| 1 | Source code in Git | Monorepo (gateway, 4 services, frontend, libs, infra) | ☐ |
| 2 | README with setup and run steps | `README.md` (compose flow, env, demo users, tests) | ☐ |
| 3 | Database schema + synthetic data | Alembic migrations, `docs/db/` ER diagrams + DDL, seed scripts | ☐ |
| 4 | API documentation | Exported OpenAPI per service in `docs/api/` + §11 | ☐ |
| 5 | Architecture + AI integration explanation | This `HLD.md` (§3–§10) | ☐ |
| 6 | Screenshots / short recording | `docs/screenshots/`: sign-in, dashboard, patient list with sparklines and filters, Overview with Kidney function panel, conditions with stage mismatch, encounter form, lab table with flags and the add-report preview, trend charts, AI summary (normal, progress, degraded, failed), source chip opening a record | ☐ |
| 7 | Synthetic data only | Verified in seed, stated in README | ☐ |
| 8 | Basic tests | `make test` green; CI badge optional | ☐ |
| 9 | Reference ranges and classification from supplied files | Replace §6.2 placeholder values with the supplied ranges before seeding | ☐ |
| 10 | UI matches the prototype | Walk the §15.4 table screen by screen against `docs/prototype/nephrocare-emr-platform.html` | ☐ |

### Suggested build order
1. Repo skeleton, compose, `init-databases.sh`, `libs/common`.
2. **auth-svc + gateway** end to end (login works through the gateway).
3. **patient-svc** (patients, conditions, meds, allergies, encounters) + seed.
4. **lab-svc** (catalog, ranges, reports, flags, CKD, trends, `patient_lab_status`, batch summary) + seed.
5. Angular: auth, patient list/detail, encounter form, labs and charts, then the dashboard once the insights endpoints exist.
6. **ai-svc**: `insights/` first (gap engine, attention rule, worklist, dashboard), then context builder + MockProvider + the async runner with `progress`; then real provider; then tool calling; then validation hardening.
7. Tests, README, API export, screenshots.

### Interview talking points
- Why four services, and why patients and encounters stayed together.
- How the list and dashboard get data from three services without joins (page-sized batch reads, a lab-owned read model, deterministic insights).
- Why the eGFR column is not sortable, and what you would build if it had to be.
- Why the AI summary is `202` plus polling and what the reaper is for.
- Why no saga or broker, and exactly what would make you add an outbox.
- Database-per-service on one instance vs shared tables vs schema-per-service, and how data is combined without joins (API composition).
- How you prevent AI from fabricating or diagnosing (deterministic core, grounding, safety lint, schema with no diagnosis field).
- How tool calling is constrained (read-only, patient-bound, bounded, audited) and why it is optional.
- What happens when the LLM fails (degraded mode) and how you keep cost and quota under control.
- Snapshotted ranges, append-only labs, optimistic locking, immutable final encounters.
