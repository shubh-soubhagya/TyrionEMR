# lab-svc — High-Level and Low-Level Design

**Project:** General Nephrology EMR (NephroCare)
**Service:** `lab-svc` — laboratory results, reference ranges, flags, CKD categories, trends, `patient_lab_status` read model
**Parent document:** `HLD-v2.md` (system HLD). Section references like "HLD §5.4" point there.
**UI acceptance reference:** `nephrocare-emr-platform.html` (prototype). Catalog values, flag logic and screen behavior below are taken from it.
**Database:** `lab_db` on the **existing PostgreSQL Docker container** (one instance, one database per service, HLD §5.1)
**Stack:** Python 3.12 · FastAPI (async) · SQLAlchemy 2.x async + asyncpg · Alembic · Pydantic v2 · httpx
**Data:** Synthetic patients only.

---

## Table of Contents

**0. [How this document relates to HLD v2](#0-how-this-document-relates-to-hld-v2)**

**Part A — High-Level Design**
- A1. [Purpose and responsibilities](#a1-purpose-and-responsibilities)
- A2. [Context](#a2-context)
- A3. [Requirements served](#a3-requirements-served)
- A4. [Quality attributes and targets](#a4-quality-attributes-and-targets)
- A5. [Component architecture](#a5-component-architecture)
- A6. [Data ownership and consistency model](#a6-data-ownership-and-consistency-model)
- A7. [Dependencies and failure behavior](#a7-dependencies-and-failure-behavior)
- A8. [Security model](#a8-security-model)
- A9. [Design decisions (lab-svc ADRs)](#a9-design-decisions-lab-svc-adrs)

**Part B — Low-Level Design**
- B1. [Code layout](#b1-code-layout)
- B2. [Configuration](#b2-configuration)
- B3. [Database design (lab_db)](#b3-database-design-lab_db)
- B4. [Domain layer (pure clinical logic)](#b4-domain-layer-pure-clinical-logic)
- B5. [Persistence layer](#b5-persistence-layer)
- B6. [Service layer (use cases)](#b6-service-layer-use-cases)
- B7. [API specification](#b7-api-specification)
- B8. [Error catalog](#b8-error-catalog)
- B9. [patient-svc client](#b9-patient-svc-client)
- B10. [Transactions and concurrency](#b10-transactions-and-concurrency)
- B11. [Seed data and the status rebuild script](#b11-seed-data-and-the-status-rebuild-script)
- B12. [Observability](#b12-observability)
- B13. [Testing](#b13-testing)
- B14. [Running on the existing Postgres container](#b14-running-on-the-existing-postgres-container)
- B15. [Performance and scaling notes](#b15-performance-and-scaling-notes)
- B16. [Open items to confirm](#b16-open-items-to-confirm)
- B17. [Build checklist](#b17-build-checklist)

---

## 0. How this document relates to HLD v2

HLD v2 fixes the contract of lab-svc: its tables (HLD §5.4), its clinical rules (HLD §6), its endpoints (HLD §11.3), its single outbound dependency (HLD §9) and the read model decision (ADR-015). This document does not change any of those. It adds the detail needed to build the service, and it closes the gaps that only show up at implementation level.

| # | Implementation gap in HLD v2 | Resolution in this document | Where |
|---|---|---|---|
| 1 | "Append-only" was a convention | Enforced by database triggers that reject `UPDATE` and `DELETE` on `lab_reports` and `lab_results` | B3.4 |
| 2 | How to tell which result is current after a correction | A result is current when no row supersedes it. Partial unique index on `supersedes_id` (a result can be corrected once), plus a `lab_results_current` view | B3.3, B3.5 |
| 3 | `patient_id` and `collected_at` are denormalized onto results, but nothing kept them equal to the report | Composite foreign key `(report_id, patient_id, collected_at)` → `lab_reports(id, patient_id, collected_at)` | B3.3 |
| 4 | "No duplicate test in one report" was only a UI rule | Partial unique index `(report_id, test_code) WHERE supersedes_id IS NULL` | B3.3 |
| 5 | Incremental update of `patient_lab_status` breaks on back-dated reports and corrections | The row is **recomputed** from current results inside the same transaction, under a per-patient advisory lock | B6.2, B10 |
| 6 | Which range applies to a back-dated result | The range effective **on the collection date**, not today | B4.2 |
| 7 | Patients with sex `O` and tests that only have sex-specific ranges (creatinine, hemoglobin) | No range matches, so the flag is `unknown` with no reference shown. Never silently `normal` | B4.2 |
| 8 | Flag snapshot held only `ref_low` and `ref_high`, so a critical flag could not be explained later | Snapshot also stores `crit_low`, `crit_high` and `range_id` | B3.3 |
| 9 | Unit strings contain `µ` and `²`, which arrive in more than one Unicode form | Units are matched by a normalized key; ASCII aliases such as `umol/L` are accepted | B4.1 |
| 10 | The creatinine chart needs the sex-specific band, but lab-svc reads never call patient-svc | The band comes from the **snapshot on the latest point** in the window | B6.5 |
| 11 | Seeding lab data needs patient UUIDs owned by patient-svc | Deterministic UUIDv5 from the MRN, shared by both seeds through one fixture file | B11 |
| 12 | Rounding could differ between the browser preview and the server | `Decimal` with half-up rounding on the server; shared test vectors include the float-trap cases | B4.1, B13.3 |
| 13 | `GET /labs/summary` behavior for patients without labs | Returns one entry per requested id, with nulls when there are no results | B7.6 |
| 14 | Catalog had no plausibility limits or display order | `lab_tests.plausible_max` and `display_order` columns, values from the prototype | B3.2 |

Everything else in HLD v2 applies unchanged.

---

# Part A — High-Level Design

## A1. Purpose and responsibilities

lab-svc owns laboratory data and everything derived from it.

| Owns | Does not own |
|---|---|
| Test catalog (8 tests), allowed units and conversion factors | Patient identity, sex, date of birth (patient-svc) |
| Reference ranges and critical limits (seeded from the supplied ranges file) | The **established** CKD stage (patient-svc, clinician-entered) |
| Lab reports (one blood draw) and lab results (one analyte each) | Gap rules, the attention rule, the worklist, the dashboard (ai-svc `insights/`) |
| Unit conversion, flagging, range snapshots | CKD-EPI eGFR estimation and the eGFR/creatinine discordance rule (ai-svc rule engine) |
| eGFR category (G1–G5) and UACR category (A1–A3) of the latest result | Anything the LLM writes |
| Trend statistics (OLS slope, direction, rapid decline) | |
| Corrections (append-only, `supersedes_id` chain) | |
| `patient_lab_status` read model for list rows, dashboard and worklist | |

**One sentence:** lab-svc turns raw values into interpreted, snapshotted, queryable lab facts, and never needs any other service to answer a read.

## A2. Context

```mermaid
flowchart LR
    UI[Angular SPA] -->|"/api/labs/**"| GW[API Gateway]
    GW -->|"/labs/** (JWT, X-Request-ID)"| LAB

    subgraph LAB["lab-svc"]
        API[Routers<br/>public + internal]
        SVC[Use cases]
        DOM[Domain<br/>pure functions]
        REPO[Repositories]
    end

    AI[ai-svc] -->|"/internal/labs/** (reads only)"| LAB
    LAB -->|"GET /internal/patients/{id}/basic<br/>only when creating a report"| PAT[patient-svc]
    LAB --- DB[("lab_db<br/>role lab_svc<br/>on the existing Postgres container")]
```

| Caller | Calls | Why |
|---|---|---|
| Angular, through the gateway | Catalog, create report, results, trends, latest, batch summary, correction | Labs tab, Overview kidney panel, patient header, patient list rows, lab form |
| ai-svc | `/internal/labs/patients/{id}/…`, `/internal/labs/status` | AI summary context and tools, insights (worklist, dashboard, gaps) |
| lab-svc → patient-svc | `GET /internal/patients/{id}/basic` | Patient exists, sex and DOB for range selection. **One call per report creation, nothing else** |

## A3. Requirements served

| Requirement (PS or prototype) | Endpoint | Section |
|---|---|---|
| Lab parameters: creatinine, eGFR, BUN, K, Hb, Ca, Phos, UACR | `GET /labs/tests` (catalog, seeded) | B3.2, B7.1 |
| Add results with dates and units | `POST /labs/patients/{id}/reports` | B6.1, B7.2 |
| Enter in another unit, see the converted value ("entered as") | Conversion at write, `value_original` + `unit_original` returned | B4.1, B7.3 |
| Highlight abnormal values against the supplied ranges | Flag computed and snapshotted at write | B4.3 |
| Live flag and conversion while typing (prototype) | Catalog feeds the client preview; server stays authoritative (ADR-019) | B7.1, B13.3 |
| View historical results; filter by test, date, abnormal only; page | `GET /labs/patients/{id}/results` | B6.4, B7.3 |
| Creatinine and eGFR trend charts with stats, date range 6m/1y/2y/all | `GET /labs/patients/{id}/trends` | B4.5, B7.4 |
| Display CKD classification of eGFR; UACR category | `GET /labs/patients/{id}/latest` | B4.4, B7.5 |
| Latest-results grid (8 tiles) on the Labs tab | `GET /labs/patients/{id}/latest` | B7.5 |
| Patient list: latest eGFR, flag, sparkline | `GET /labs/summary?patient_ids=` | B7.6 |
| Correct a wrong result without losing history | `POST /labs/results/{rid}/correct` | B6.2, B7.7 |
| Dashboard, worklist, eGFR distribution, abnormal results (via ai-svc) | `GET /internal/labs/status` | B7.9 |
| AI tools `get_lab_history`, `get_lab_trend` | Internal mirrors of results and trends | B7.8 |

## A4. Quality attributes and targets

| Attribute | Target | How |
|---|---|---|
| Read latency (p95, at the service) | `latest`, `summary`: < 30 ms. `results` page, `trends`: < 60 ms | Single indexed reads; read model; no cross-service calls on reads |
| Write latency (p95) | Create report: < 250 ms including the patient-svc call | Patient call outside the transaction; small transaction; status recompute over one patient's rows |
| Consistency | Read model is **never stale**: it is written in the same transaction as the results | B10 |
| Correctness | Flags, categories and trends are pure functions with boundary tests; snapshots keep history interpretable | B4, B13 |
| Availability | Reads keep working when patient-svc is down; only report creation needs it | A7 |
| Data volume (design point) | 10k patients × 200 results ≈ 2M rows; partition by time beyond that | B15 |
| Auditability | Every row has `entered_by` and `created_at`; corrections keep the original and a reason | B3.3 |

## A5. Component architecture

Layering follows HLD §14 (router → service → repository), with the clinical rules isolated in a pure domain package.

```mermaid
flowchart TB
    subgraph API["api/ (FastAPI routers)"]
        R1["public.py<br/>/labs/**"]
        R2["internal.py<br/>/internal/labs/**"]
        R3["health.py"]
    end
    subgraph APP["services/ (use cases, own the transaction)"]
        S1[ReportService<br/>create, correct]
        S2[ResultQueryService<br/>results, trends, latest]
        S3[StatusService<br/>recompute, summary, bulk]
        S4[CatalogService<br/>cached catalog + ranges]
    end
    subgraph DOM["domain/ (pure, no I/O)"]
        D1[units.py]
        D2[ranges.py]
        D3[flags.py]
        D4[ckd.py]
        D5[trends.py]
        D6[status.py]
    end
    subgraph INF["infrastructure"]
        RP[repositories/]
        PC[clients/patient.py<br/>resilient httpx]
        DB[(lab_db)]
    end
    R1 --> S1 & S2 & S3 & S4
    R2 --> S2 & S3
    S1 --> DOM
    S2 --> DOM
    S3 --> DOM
    S1 --> RP
    S2 --> RP
    S3 --> RP
    S4 --> RP
    S1 --> PC
    RP --> DB
```

Rules:
1. `domain/` imports nothing from FastAPI, SQLAlchemy or httpx. A test enforces it (same technique as the `insights/` → `llm/` rule in HLD §10.2).
2. Only services open transactions. Repositories receive a session.
3. Routers do HTTP only: parse, authorize, call one service method, map the result.

## A6. Data ownership and consistency model

| Data | Source of truth | Mutability | Consistency |
|---|---|---|---|
| `lab_tests`, `lab_reference_ranges` | lab_db (seeded by migration from the supplied file) | Changed only by a migration or seed | Cached in process, reloaded on change |
| `lab_reports`, `lab_results` | lab_db | **Append-only** (DB triggers) | ACID |
| `patient_lab_status` | Derived from current `lab_results` | Upserted by lab-svc only | Same transaction as the write, so always consistent; rebuildable |
| Patient sex and DOB | patient-svc | Read once per report creation | Used at write time and then frozen into the snapshot (range id, limits, flag) |

**Why a sex or DOB change in patient-svc does not rewrite lab history.** The flag recorded at the time is the interpretation the clinician saw. Rewriting it would change the meaning of historical results silently. If a sex or DOB entry was simply wrong, the fix is a correction of the affected results (B6.2), which re-evaluates against the original range snapshot, or, in the rare case the range itself was wrong, a correction that a clinician makes explicitly. This matches ADR-009.

## A7. Dependencies and failure behavior

| Dependency | Used by | If it is slow or down |
|---|---|---|
| PostgreSQL (`lab_db`) | Everything | `/ready` fails; requests return `503 DB_UNAVAILABLE` |
| patient-svc `GET /internal/patients/{id}/basic` | Create report only | Timeout 1 s connect / 3 s read, up to 2 retries on GET for connect errors and 502/503/504. Then `502 UPSTREAM_UNAVAILABLE` with `details.upstream = "patient-svc"`. **Nothing is written.** All reads and corrections keep working |
| JWKS from auth-svc | Token verification | Keys cached; refreshed on unknown `kid`. auth-svc downtime does not affect already-issued tokens |

lab-svc never calls ai-svc, and never calls patient-svc on a read. A correction does not call patient-svc either, because it reuses the range snapshot of the result it corrects (B6.2).

## A8. Security model

| Layer | Control |
|---|---|
| Edge | Gateway verifies the JWT, blocks `/internal/**` from outside, rate-limits (HLD §8) |
| Service | Verifies the JWT again (RS256, cached JWKS, `iss=nephro-auth`, `aud=nephro-api`), then `require_role("clinician")` on every route |
| Internal routes | Same JWT dependency. ai-svc forwards the user's JWT, so the audit trail shows the real user (HLD §9) |
| Identity | `entered_by` comes from `sub` in the verified JWT. No client-supplied user header is trusted |
| Database | Role `lab_svc` owns `lab_db`; `CONNECT` revoked from `PUBLIC`. No other service can open the database |
| Input | Pydantic strict schemas, length limits, `Decimal` values, parameterized SQL only |
| Logs | IDs, counts and flags only. No lab values, names or notes |
| Container | Non-root, slim image, no published port (only the gateway publishes) |

## A9. Design decisions (lab-svc ADRs)

These sit under the system ADRs in HLD §19 and refine ADR-009, ADR-015 and ADR-019.

### LAB-ADR-1: Recompute the read model, do not patch it
**Context:** `patient_lab_status` must reflect the latest result per test, trend stats and the last 12 eGFR points.
**Alternatives:** incremental merge of the new result into the JSON (fast, but wrong for back-dated reports, corrections of older values and ties); a trigger in SQL (logic duplicated in PL/pgSQL, harder to test).
**Decision:** after every write, load the patient's current results and rebuild the row with the same pure function the rebuild script uses.
**Why:** one code path, provably equal to a full rebuild, and cheap (one patient has tens to a few hundred rows).
**Consequence:** a write costs one extra indexed read. Covered by a "recompute equals rebuild" test.

### LAB-ADR-2: Append-only enforced by the database
**Decision:** `BEFORE UPDATE OR DELETE` triggers raise on `lab_reports` and `lab_results`.
**Why:** a bug or a manual `UPDATE` cannot silently rewrite a clinical result. `TRUNCATE` (used only by test fixtures and the dev reset script) does not fire row triggers.

### LAB-ADR-3: Corrections supersede, once
**Decision:** a correction is a new row with `supersedes_id` set and a mandatory reason. A partial unique index allows only one correction per row, so corrections form a single chain. "Current" means "not superseded".
**Why:** the history of a value stays visible and ordered, and two simultaneous corrections cannot fork the chain.

### LAB-ADR-4: Range effective on the collection date
**Decision:** range selection uses `effective_from <= collected_at::date`.
**Why:** a back-dated report entered today must be interpreted with the range that applied when the sample was taken.

### LAB-ADR-5: Patient call before the transaction, never inside it
**Why:** holding a database transaction (and the advisory lock) while waiting on the network would let a slow patient-svc exhaust the connection pool.

### LAB-ADR-6: Reads never cross a service boundary
**Decision:** everything a read needs is in lab_db, including the creatinine reference band (taken from the snapshot on the latest point).
**Why:** list rows, charts and the dashboard stay up when patient-svc is down, and read latency is one query.

### LAB-ADR-7: Exact decimal arithmetic
**Decision:** values are `numeric` in PostgreSQL and `Decimal` in Python. Conversion rounds half-up to `decimals + 1` places.
**Why:** binary floats turn `150 µmol/L` into `1.6949999…`; a flag on a boundary must not depend on that. The browser preview uses the same rule and the shared vectors prove it.

---

# Part B — Low-Level Design

## B1. Code layout

```
services/lab/
  Dockerfile
  pyproject.toml
  alembic.ini
  alembic/
    env.py                      async env, takes a pg advisory lock while migrating
    versions/
      0001_initial_schema.py    tables, indexes, triggers, view (hand-written SQL)
      0002_catalog_and_ranges.py  8 tests + reference ranges (placeholder values, see B16)
  app/
    main.py                     app factory, lifespan: engine, catalog cache, httpx client, JWKS cache
    core/
      config.py                 Settings (pydantic-settings)
      security.py               JWT verify (libs/common), require_role("clinician")
      errors.py                 DomainError hierarchy -> error envelope
      logging.py                JSON logs with request_id, user_id
    api/
      deps.py                   get_session, current_user, service factories
      public.py                 /labs/**
      internal.py               /internal/labs/**
      health.py                 /health, /ready, /metrics
    schemas/                    Pydantic v2 DTOs (API contract, separate from tables)
      common.py catalog.py reports.py results.py trends.py status.py
    domain/                     PURE: no FastAPI, SQLAlchemy or httpx imports
      models.py                 frozen dataclasses (TestDef, RangeDef, Point, TrendStats, StatusSnapshot)
      constants.py              RULES_VERSION, KDIGO thresholds, trend rules
      units.py  ranges.py  flags.py  ckd.py  trends.py  status.py
    db/
      session.py                async engine + sessionmaker
      tables.py                 SQLAlchemy Core tables mirroring 0001
    repositories/
      catalog_repo.py  reports_repo.py  results_repo.py  status_repo.py
    services/
      catalog_service.py        in-process cache of tests + ranges
      report_service.py         create report, correct result
      status_service.py         recompute, summary, bulk
      query_service.py          results, trends, latest
    clients/
      patient.py                resilient client for /internal/patients/{id}/basic
    scripts/
      rebuild_status.py         python -m app.scripts.rebuild_status [--check] [--patient-id]
    seed/
      __main__.py               python -m app.seed
      generator.py              deterministic synthetic results
  tests/
    unit/                       domain functions, boundaries, import rule
    api/                        httpx.AsyncClient against lab_db_test
    contract/                   shapes consumed by ai-svc
```

Shared code lives in `libs/common` (infrastructure only, HLD §17.1): JWT verification, error envelope, request-id middleware, pagination model, resilient HTTP client. Shared fixtures live in `libs/fixtures/` (patients seed file, B11) and `libs/test-vectors/` (lab vectors, B13.3).

## B2. Configuration

All settings come from environment variables (`pydantic-settings`). Defaults are safe for local use.

| Variable | Default | Purpose |
|---|---|---|
| `LAB_DATABASE_URL` | none (required) | `postgresql+asyncpg://lab_svc:***@<pg-host>:5432/lab_db` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` | Explicit pool size, because four services share one instance's `max_connections` (HLD §5.1) |
| `DB_POOL_TIMEOUT_S` | `5` | Wait for a pooled connection |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` | Sent as `statement_timeout` on connect |
| `PATIENT_SVC_URL` | `http://patient-svc:8000` | Internal base URL |
| `PATIENT_CONNECT_TIMEOUT_S` / `PATIENT_READ_TIMEOUT_S` | `1` / `3` | HLD §9 |
| `PATIENT_RETRIES` | `2` | GET only, connect errors and 502/503/504 |
| `JWKS_URL`, `JWT_ISSUER`, `JWT_AUDIENCE` | from HLD §17.3 | Token verification |
| `SUMMARY_MAX_IDS` | `50` | `/labs/summary` limit |
| `RESULTS_PAGE_MAX` | `100` | Max `size` for result pages |
| `STATUS_BULK_MAX` | `200` | Max `limit` for `/internal/labs/status` |
| `SPARK_POINTS` | `12` | eGFR points kept in the read model |
| `TREND_MIN_POINTS` | `3` | Below this, `direction = insufficient_data` |
| `EGFR_STABLE_BAND` | `2` | mL/min/1.73 m² per year (HLD §6.3) |
| `CREAT_STABLE_BAND` | `0.1` | mg/dL per year |
| `EGFR_RAPID_DECLINE` | `-5` | Slope at or below this is rapid decline |
| `CLOCK_SKEW_S` | `60` | Tolerance when rejecting future `collected_at` |
| `CATALOG_CACHE_TTL_S` | `300` | Catalog and ranges cache lifetime |
| `RUN_MIGRATIONS` | `false` | Dev convenience: run `alembic upgrade head` on start |
| `LOG_LEVEL` | `INFO` | |

Changing a trend setting changes `RULES_VERSION` (B4.7), so the rebuild script can find rows computed with old rules.

## B3. Database design (lab_db)

### B3.1 Entity relationships

```mermaid
erDiagram
    LAB_TESTS ||--o{ LAB_REFERENCE_RANGES : "has ranges"
    LAB_TESTS ||--o{ LAB_RESULTS : "measured as"
    LAB_REPORTS ||--|{ LAB_RESULTS : contains
    LAB_REFERENCE_RANGES |o--o{ LAB_RESULTS : "snapshot of"
    LAB_RESULTS |o--o| LAB_RESULTS : "superseded by (once)"
    LAB_RESULTS }o--|| PATIENT_LAB_STATUS : "summarized in"

    LAB_TESTS {
        text code PK
        text name
        text canonical_unit
        jsonb allowed_units
        smallint decimals
        numeric plausible_max
        smallint display_order UK
    }
    LAB_REFERENCE_RANGES {
        uuid id PK
        text test_code FK
        char sex "M F or null"
        smallint age_min
        smallint age_max
        numeric low
        numeric high
        numeric critical_low
        numeric critical_high
        date effective_from
        text source
    }
    LAB_REPORTS {
        uuid id PK
        uuid patient_id "UUID ref to patient-svc"
        timestamptz collected_at
        text lab_name
        text notes
        uuid entered_by
        timestamptz created_at
    }
    LAB_RESULTS {
        uuid id PK
        uuid report_id FK
        uuid patient_id "denormalized, FK-checked"
        timestamptz collected_at "denormalized, FK-checked"
        text test_code FK
        numeric value "canonical"
        text unit "canonical"
        numeric value_original
        text unit_original
        uuid range_id FK
        numeric ref_low
        numeric ref_high
        numeric crit_low
        numeric crit_high
        text flag
        uuid supersedes_id FK
        text correction_reason
        uuid entered_by
        timestamptz created_at
    }
    PATIENT_LAB_STATUS {
        uuid patient_id PK
        jsonb latest
        text egfr_category
        text uacr_category
        jsonb egfr_stats
        jsonb creat_stats
        jsonb egfr_spark
        bool has_critical
        bool rapid_decline
        int result_count
        timestamptz last_result_at
        int version
        text rules_version
        timestamptz updated_at
    }
```

### B3.2 Catalog tables

```sql
-- alembic 0001_initial_schema (part 1)

CREATE TABLE lab_tests (
    code            text        PRIMARY KEY CHECK (code ~ '^[A-Z]{1,10}$'),
    name            text        NOT NULL,
    canonical_unit  text        NOT NULL,
    allowed_units   jsonb       NOT NULL,          -- {"mg/dL": "1", "µmol/L": "0.0113"}  unit -> factor to canonical
    decimals        smallint    NOT NULL CHECK (decimals BETWEEN 0 AND 4),
    plausible_max   numeric(12,4) NOT NULL CHECK (plausible_max > 0),
    display_order   smallint    NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT allowed_units_is_object    CHECK (jsonb_typeof(allowed_units) = 'object'),
    CONSTRAINT allowed_units_has_canonical CHECK (allowed_units ? canonical_unit)
);

CREATE TABLE lab_reference_ranges (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    test_code      text        NOT NULL REFERENCES lab_tests(code),
    sex            char(1)     NULL CHECK (sex IN ('M','F')),       -- NULL = any sex
    age_min        smallint    NULL CHECK (age_min >= 0),
    age_max        smallint    NULL CHECK (age_max <= 130),
    low            numeric(12,4),
    high           numeric(12,4),
    critical_low   numeric(12,4),
    critical_high  numeric(12,4),
    effective_from date        NOT NULL DEFAULT DATE '2000-01-01',
    source         text        NOT NULL,                             -- e.g. 'supplied-ranges-file v1'
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT range_has_a_limit  CHECK (low IS NOT NULL OR high IS NOT NULL),
    CONSTRAINT range_low_lt_high  CHECK (low IS NULL OR high IS NULL OR low < high),
    CONSTRAINT range_age_order    CHECK (age_min IS NULL OR age_max IS NULL OR age_min <= age_max),
    CONSTRAINT crit_low_le_low    CHECK (critical_low  IS NULL OR low  IS NULL OR critical_low  <= low),
    CONSTRAINT crit_high_ge_high  CHECK (critical_high IS NULL OR high IS NULL OR critical_high >= high)
);

-- one range per (test, sex, age band, effective date)
CREATE UNIQUE INDEX ux_ranges_key ON lab_reference_ranges
    (test_code, COALESCE(sex, '*'), COALESCE(age_min, -1), COALESCE(age_max, -1), effective_from);
```

`gen_random_uuid()` is built in from PostgreSQL 13. B14.1 checks the version of the existing container.

**Catalog seed (migration 0002).** Values are taken from the prototype and are **placeholders** until the supplied ranges file is loaded (HLD §6.2, B16).

| Code | Name | Canonical unit | Decimals | Allowed units (factor to canonical) | Plausible max | Order |
|---|---|---|---|---|---|---|
| `CREAT` | Serum creatinine | mg/dL | 2 | mg/dL ×1 · µmol/L ×0.0113 | 30 | 1 |
| `EGFR` | eGFR | mL/min/1.73m² | 0 | mL/min/1.73m² ×1 | 200 | 2 |
| `BUN` | Blood urea nitrogen | mg/dL | 1 | mg/dL ×1 · mmol/L (urea) ×2.8 | 300 | 3 |
| `K` | Potassium | mmol/L | 1 | mmol/L ×1 · mEq/L ×1 | 12 | 4 |
| `HB` | Hemoglobin | g/dL | 1 | g/dL ×1 · g/L ×0.1 | 25 | 5 |
| `CA` | Calcium | mg/dL | 1 | mg/dL ×1 · mmol/L ×4.008 | 20 | 6 |
| `PHOS` | Phosphorus | mg/dL | 1 | mg/dL ×1 · mmol/L ×3.097 | 20 | 7 |
| `UACR` | Urine albumin-creatinine ratio | mg/g | 0 | mg/g ×1 · mg/mmol ×8.84 | 20000 | 8 |

| Test | Sex | Low | High | Critical low | Critical high |
|---|---|---|---|---|---|
| CREAT | M | 0.7 | 1.3 | | 5.0 |
| CREAT | F | 0.6 | 1.1 | | 5.0 |
| EGFR | any | 90 | | 10 | |
| BUN | any | 7 | 20 | | 100 |
| K | any | 3.5 | 5.0 | 2.8 | 6.0 |
| HB | M | 13.5 | 17.5 | 7.0 | |
| HB | F | 12.0 | 15.5 | 7.0 | |
| CA | any | 8.5 | 10.5 | 6.5 | 13.0 |
| PHOS | any | 2.5 | 4.5 | 1.0 | 8.0 |
| UACR | any | | 30 | | |

Factors are stored as JSON **strings** so they load as exact `Decimal` values, not floats.

### B3.3 Reports and results

```sql
-- alembic 0001_initial_schema (part 2)

CREATE TABLE lab_reports (
    id            uuid        PRIMARY KEY,
    patient_id    uuid        NOT NULL,                          -- UUID ref to patient-svc, no FK (HLD §5.1 rule 3)
    collected_at  timestamptz NOT NULL CHECK (collected_at >= TIMESTAMPTZ '1900-01-01 00:00Z'),
    lab_name      text        NOT NULL CHECK (char_length(lab_name) BETWEEN 1 AND 120),
    notes         text        NULL     CHECK (notes IS NULL OR char_length(notes) <= 500),
    entered_by    uuid        NOT NULL,                          -- JWT sub
    request_id    text        NULL,                              -- X-Request-ID, for tracing a write
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_reports_id_patient_collected UNIQUE (id, patient_id, collected_at)
);
CREATE INDEX ix_reports_patient_collected ON lab_reports (patient_id, collected_at DESC);

CREATE TABLE lab_results (
    id                 uuid          PRIMARY KEY,
    report_id          uuid          NOT NULL,
    patient_id         uuid          NOT NULL,
    collected_at       timestamptz   NOT NULL,
    test_code          text          NOT NULL REFERENCES lab_tests(code),
    value              numeric(12,4) NOT NULL CHECK (value >= 0),            -- canonical unit
    unit               text          NOT NULL,                               -- canonical unit (app-checked)
    value_original     numeric(14,4) NOT NULL CHECK (value_original >= 0),
    unit_original      text          NOT NULL,
    range_id           uuid          NULL REFERENCES lab_reference_ranges(id),
    ref_low            numeric(12,4) NULL,                                   -- snapshot
    ref_high           numeric(12,4) NULL,                                   -- snapshot
    crit_low           numeric(12,4) NULL,                                   -- snapshot
    crit_high          numeric(12,4) NULL,                                   -- snapshot
    flag               text          NOT NULL CHECK (flag IN
                         ('normal','low','high','critical_low','critical_high','unknown')),
    supersedes_id      uuid          NULL,
    correction_reason  text          NULL CHECK (correction_reason IS NULL OR char_length(correction_reason) BETWEEN 3 AND 300),
    entered_by         uuid          NOT NULL,
    created_at         timestamptz   NOT NULL DEFAULT now(),

    -- denormalized patient_id and collected_at must equal the report's
    CONSTRAINT fk_results_report FOREIGN KEY (report_id, patient_id, collected_at)
        REFERENCES lab_reports (id, patient_id, collected_at),

    -- a correction must point at a result of the same report and the same test
    CONSTRAINT ux_results_id_report_test UNIQUE (id, report_id, test_code),
    CONSTRAINT fk_results_supersedes FOREIGN KEY (supersedes_id, report_id, test_code)
        REFERENCES lab_results (id, report_id, test_code),

    CONSTRAINT correction_needs_reason CHECK ((supersedes_id IS NULL) = (correction_reason IS NULL)),
    CONSTRAINT not_self_superseding    CHECK (supersedes_id IS DISTINCT FROM id),
    CONSTRAINT unknown_iff_no_range    CHECK ((flag = 'unknown') = (range_id IS NULL))
);

-- each result can be corrected at most once -> corrections form a single chain
CREATE UNIQUE INDEX ux_results_supersedes ON lab_results (supersedes_id) WHERE supersedes_id IS NOT NULL;

-- one ORIGINAL result per test per report (corrections share report_id and test_code)
CREATE UNIQUE INDEX ux_results_report_test_original ON lab_results (report_id, test_code)
    WHERE supersedes_id IS NULL;

-- trends, per-test history (HLD §4.3)
CREATE INDEX ix_results_trend ON lab_results (patient_id, test_code, collected_at DESC);
-- result history across all tests, newest first
CREATE INDEX ix_results_patient_collected ON lab_results (patient_id, collected_at DESC);
```

**Why each constraint is there**

| Constraint | Protects against |
|---|---|
| `fk_results_report` (composite) | A result row whose `patient_id` or `collected_at` drifts from its report. The denormalization (HLD §5.4) becomes safe |
| `fk_results_supersedes` (composite, self) | Correcting a potassium result with a creatinine row, or a result from another report |
| `ux_results_supersedes` | Two corrections of the same row (a forked chain). Concurrent corrections: one gets `23505`, mapped to `409` |
| `ux_results_report_test_original` | The same test twice in one report |
| `unknown_iff_no_range` | A `normal` flag without a range (the "never silently normal" rule from HLD §6.2) |
| `correction_needs_reason` | Corrections without an explanation |
| `collected_at >= 1900` | Garbage dates. "Not in the future" and "not before birth" are checked in the service (B6.1) because a `CHECK` using `now()` is not immutable and DOB lives in patient-svc |

### B3.4 Append-only triggers

```sql
-- alembic 0001_initial_schema (part 3)

CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only; insert a correction instead', TG_TABLE_NAME
        USING ERRCODE = 'P0001';
END;
$$;

CREATE TRIGGER trg_reports_append_only BEFORE UPDATE OR DELETE ON lab_reports
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TRIGGER trg_results_append_only BEFORE UPDATE OR DELETE ON lab_results
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
```

`TRUNCATE` does not fire row-level triggers, so the API test fixture and the dev reset script can still clear tables. Production code never truncates.

### B3.5 Current-results view

```sql
-- alembic 0001_initial_schema (part 4)

CREATE VIEW lab_results_current AS
SELECT r.*
FROM lab_results r
WHERE NOT EXISTS (
    SELECT 1 FROM lab_results s WHERE s.supersedes_id = r.id
);
```

The anti-join is answered by `ux_results_supersedes`, one index probe per row. Every read path in lab-svc reads this view. `include_superseded=true` on the results endpoint (B7.3) reads the base table.

```mermaid
stateDiagram-v2
    [*] --> Current: original inserted
    Current --> Superseded: correction inserted (new row becomes Current)
    Superseded --> [*]
    note right of Superseded: row is never updated, it is excluded by the view
```

### B3.6 Read model

```sql
-- alembic 0001_initial_schema (part 5)

CREATE TABLE patient_lab_status (
    patient_id      uuid        PRIMARY KEY,                     -- UUID ref
    latest          jsonb       NOT NULL DEFAULT '{}'::jsonb,    -- latest current result per test
    egfr_category   text        NULL CHECK (egfr_category IN ('G1','G2','G3a','G3b','G4','G5')),
    uacr_category   text        NULL CHECK (uacr_category IN ('A1','A2','A3')),
    egfr_stats      jsonb       NULL,                            -- TrendStats over all eGFR results
    creat_stats     jsonb       NULL,                            -- TrendStats over all creatinine results
    egfr_spark      jsonb       NOT NULL DEFAULT '[]'::jsonb,    -- last SPARK_POINTS eGFR points
    has_critical    boolean     NOT NULL DEFAULT false,          -- latest result of any test is critical_*
    rapid_decline   boolean     NOT NULL DEFAULT false,
    result_count    integer     NOT NULL DEFAULT 0,              -- current results
    last_result_at  timestamptz NULL,
    version         integer     NOT NULL DEFAULT 1,              -- +1 on every recompute (ETag)
    rules_version   text        NOT NULL,                        -- domain RULES_VERSION used
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- the worklist reads patients with an attention flag often
CREATE INDEX ix_status_attention ON patient_lab_status (patient_id)
    WHERE has_critical OR rapid_decline;
```

**JSON shapes** (validated by Pydantic before writing):

```jsonc
// latest
{
  "EGFR":  {"result_id": "uuid", "report_id": "uuid", "value": 38, "unit": "mL/min/1.73m²",
            "flag": "low", "collected_at": "2026-10-21T04:00:00Z", "ref_low": 90, "ref_high": null},
  "CREAT": {"result_id": "uuid", "report_id": "uuid", "value": 1.82, "unit": "mg/dL",
            "flag": "high", "collected_at": "2026-10-21T04:00:00Z", "ref_low": 0.7, "ref_high": 1.3}
}
// egfr_stats / creat_stats  (same shape as the trends endpoint, B4.5)
{"n": 8, "first": 54, "last": 38, "abs_change": -16, "pct_change": -29.6,
 "slope_per_year": -8.31, "direction": "worsening", "rapid_decline": true,
 "span_days": 700, "first_at": "...", "last_at": "..."}
// egfr_spark
[{"t": "2025-01-02T04:00:00Z", "v": 54}, {"t": "...", "v": 51}]
```

The status is a function of the results only, never of the current date. It therefore needs no nightly job. Time-based rules such as `NO_RECENT_LABS` live in ai-svc and use `last_result_at`.

### B3.7 Ownership, grants and migrations

- `lab_db` and every object in it are owned by `lab_svc` (B14.2 creates them). The service connects as that role.
- Migrations: Alembic, **hand-written SQL** in `op.execute(...)` for triggers, the view and partial indexes. `tables.py` mirrors the tables for queries; autogenerate is not used, because it cannot see triggers or views.
- `alembic/env.py` takes `pg_advisory_lock(hashtext('lab-svc-migrations'))` before upgrading, so two replicas starting together cannot run migrations twice.
- Migrations are forward-only in practice. Each revision has a `downgrade()` for local use.
- Test database `lab_db_test` (same owner) is created next to `lab_db` (B14.2).

## B4. Domain layer (pure clinical logic)

Everything here is deterministic, has no I/O and is covered by table-driven unit tests (B13.1).

### B4.1 Units and conversion

```python
# domain/units.py
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

def unit_key(unit: str) -> str:
    """Matching key: 'µmol/L', 'μmol/L', 'umol/L', 'UMOL / L' -> 'umol/l';
    'mL/min/1.73m²' and 'mL/min/1.73m2' -> 'ml/min/1.73m2'."""
    s = unicodedata.normalize("NFKC", unit)      # '²' -> '2', MICRO SIGN U+00B5 -> GREEK MU U+03BC
    s = s.replace("\u03bc", "u")                  # mu -> 'u'
    return "".join(s.split()).casefold()

def resolve_unit(test: TestDef, unit: str) -> str:
    """Return the catalog display spelling of the unit, or raise UnknownUnit."""
    display = test.unit_index.get(unit_key(unit))   # built once per TestDef
    if display is None:
        raise UnknownUnit(test.code, unit, allowed=list(test.units))
    return display

def to_canonical(test: TestDef, value: Decimal, unit_display: str) -> Decimal:
    factor = test.units[unit_display]                         # Decimal, exact
    quantum = Decimal(1).scaleb(-(test.decimals + 1))         # 10^-(decimals+1)
    return (value * factor).quantize(quantum, rounding=ROUND_HALF_UP)
```

- Stored canonical precision is `decimals + 1` places (the prototype's rule): `150 µmol/L × 0.0113 = 1.695 mg/dL`. Display rounds to `decimals`.
- `unit_original` is stored in the catalog's display spelling, not the raw client string, so "entered as" always renders the same way.
- At startup the catalog asserts that no two units of one test share a key. `BUN` accepts `mmol/L (urea)` but not a bare `mmol/L`, which would be ambiguous.
- Accepted value precision on input: at most 4 decimal places, at most 10 significant digits.

### B4.2 Range selection

```python
# domain/ranges.py
def age_on(dob: date, on: date) -> int:
    years = on.year - dob.year
    return years - ((on.month, on.day) < (dob.month, dob.day))

def select_range(ranges: Sequence[RangeDef], test_code: str, sex: str,
                 age_years: int, on: date) -> RangeDef | None:
    candidates = [
        r for r in ranges
        if r.test_code == test_code
        and r.effective_from <= on                       # LAB-ADR-4
        and (r.sex is None or r.sex == sex)
        and (r.age_min is None or age_years >= r.age_min)
        and (r.age_max is None or age_years <= r.age_max)
    ]
    if not candidates:
        return None
    # specific beats generic: sex-specific > any sex, age-banded > unbanded, then newest
    return max(candidates, key=lambda r: (
        r.sex is not None,
        r.age_min is not None or r.age_max is not None,
        r.effective_from,
    ))
```

| Case | Result |
|---|---|
| Male, creatinine | `CREAT/M` range |
| Sex `O`, creatinine or hemoglobin (only `M`/`F` ranges exist) | `None` → flag `unknown`, no reference shown, chip "No range" |
| Sex `O`, potassium (an any-sex range exists) | The any-sex range |
| Report dated 2024, ranges revised in 2026 | The range effective in 2024 |

### B4.3 Flagging

```python
# domain/flags.py
def flag_for(value: Decimal, r: RangeDef | None) -> str:
    if r is None:
        return "unknown"
    if r.critical_low  is not None and value < r.critical_low:  return "critical_low"
    if r.critical_high is not None and value > r.critical_high: return "critical_high"
    if r.low  is not None and value < r.low:  return "low"
    if r.high is not None and value > r.high: return "high"
    return "normal"
```

Comparisons are strict, as in the prototype: a value **equal** to a limit is on the safer side. `K = 6.0` is `high`, `K = 6.1` is `critical_high`; `K = 3.5` is `normal`.

Grouping used by filters and counts:

| Group | Flags |
|---|---|
| `abnormal` | `low`, `high`, `critical_low`, `critical_high` |
| `critical` | `critical_low`, `critical_high` |
| `unknown` | `unknown` (no range; shown, but not counted as abnormal) |

### B4.4 CKD categories

```python
# domain/ckd.py  (KDIGO; thresholds are lower-inclusive, HLD §6.1)
EGFR_CATEGORIES = (("G1", 90), ("G2", 60), ("G3a", 45), ("G3b", 30), ("G4", 15))

def classify_egfr(v: Decimal) -> str:
    for code, lower in EGFR_CATEGORIES:
        if v >= lower:
            return code
    return "G5"

def classify_uacr(v: Decimal) -> str:          # mg/g
    if v < 30:   return "A1"
    if v <= 300: return "A2"
    return "A3"
```

Boundaries: `90 → G1`, `89.9 → G2`, `60 → G2`, `59.9 → G3a`, `45 → G3a`, `30 → G3b`, `15 → G4`, `14.9 → G5`; `29.9 → A1`, `30 → A2`, `300 → A2`, `300.1 → A3`.

The classification is applied to the **canonical stored value** (one extra decimal), so `59.95` entered as eGFR is stored as `60.0` and classified `G2`. That case is in the shared vectors.

### B4.5 Trend statistics

```python
# domain/trends.py
def direction_for(test_code: str, slope: float, cfg: TrendConfig) -> str:
    if test_code == "EGFR":                      # falling eGFR is worse
        if slope <= -cfg.egfr_stable_band: return "worsening"
        if slope >= cfg.egfr_stable_band:  return "improving"
        return "stable"
    if test_code == "CREAT":                     # rising creatinine is worse
        if slope > cfg.creat_stable_band:  return "worsening"
        if slope < -cfg.creat_stable_band: return "improving"
        return "stable"
    return "not_assessed"

def trend_stats(test_code: str, points: Sequence[Point], cfg: TrendConfig) -> TrendStats:
    n = len(points)
    if n == 0:
        return TrendStats(n=0, direction="no_data")
    first, last = points[0], points[-1]
    abs_change = last.value - first.value
    pct_change = None if first.value == 0 else round(float(abs_change / first.value * 100), 1)
    span_days = round((last.at - first.at).total_seconds() / 86400)

    xs = [(p.at - first.at).total_seconds() / (365.25 * 86400) for p in points]   # years
    ys = [float(p.value) for p in points]
    slope, direction, rapid = None, "insufficient_data", False
    if n >= cfg.min_points and len(set(xs)) >= 2:
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        direction = direction_for(test_code, slope, cfg)
        rapid = test_code == "EGFR" and slope <= cfg.egfr_rapid_decline
    return TrendStats(n=n, first=first.value, last=last.value, abs_change=abs_change,
                      pct_change=pct_change, slope_per_year=None if slope is None else round(slope, 2),
                      direction=direction, rapid_decline=rapid, span_days=span_days,
                      first_at=first.at, last_at=last.at)
```

The direction rule in a table (it matches the prototype, including which comparisons are inclusive):

| Test | Worsening | Improving | Stable |
|---|---|---|---|
| eGFR | slope **≤ −2** | slope **≥ +2** | otherwise |
| Creatinine | slope **> +0.1** | slope **< −0.1** | otherwise |
| Any other test | `not_assessed` (slope is still returned, for the AI tool `get_lab_trend`) | | |

Rapid decline: eGFR slope **≤ −5** per year (inclusive, as in the prototype).

Rules worth stating:
- Fewer than 3 points, or all points on the same timestamp → `insufficient_data`, `slope_per_year = null`. Two points never produce a direction (HLD §6.3).
- Slope is ordinary least squares over (years since first point, value). Floats are fine here: these are descriptive statistics, and no stored flag depends on them.
- Points are ordered by `(collected_at, created_at, id)`, so ties are deterministic.

### B4.6 Read-model builder

```python
# domain/status.py
def build_status(rows: Sequence[CurrentResult], cfg: TrendConfig, spark_points: int) -> StatusSnapshot:
    rows = sorted(rows, key=lambda r: (r.collected_at, r.created_at, r.id))
    latest: dict[str, CurrentResult] = {}
    for r in rows:
        latest[r.test_code] = r                          # last one wins

    egfr = [Point(r.collected_at, r.value) for r in rows if r.test_code == "EGFR"]
    creat = [Point(r.collected_at, r.value) for r in rows if r.test_code == "CREAT"]
    egfr_stats = trend_stats("EGFR", egfr, cfg)
    creat_stats = trend_stats("CREAT", creat, cfg)

    return StatusSnapshot(
        latest={code: LatestEntry.from_row(r) for code, r in latest.items()},
        egfr_category=classify_egfr(latest["EGFR"].value) if "EGFR" in latest else None,
        uacr_category=classify_uacr(latest["UACR"].value) if "UACR" in latest else None,
        egfr_stats=egfr_stats if egfr else None,
        creat_stats=creat_stats if creat else None,
        egfr_spark=[{"t": p.at, "v": p.value} for p in egfr[-spark_points:]],
        has_critical=any(r.flag.startswith("critical") for r in latest.values()),
        rapid_decline=bool(egfr_stats.rapid_decline),
        result_count=len(rows),
        last_result_at=rows[-1].collected_at if rows else None,
        rules_version=RULES_VERSION,
    )
```

`has_critical` looks only at the **latest** result per test (HLD §5.4): a critical potassium last year followed by a normal one today does not keep the patient on the worklist.

### B4.7 Rules version

```python
# domain/constants.py
RULES_VERSION = "lab-rules-1"   # bump when flag, category, trend or status logic or its config changes
```

The rebuild script (B11.3) recomputes rows whose `rules_version` differs.

## B5. Persistence layer

Repositories use SQLAlchemy Core (explicit SQL shape, no lazy loading) on an `AsyncSession` passed in by the service. Dynamic filters are built by adding `WHERE` clauses, not with `(:x IS NULL OR col = :x)`, so the planner always sees a simple predicate.

```python
# db/tables.py (excerpt)
lab_results = Table(
    "lab_results", metadata,
    Column("id", UUID, primary_key=True),
    Column("report_id", UUID, nullable=False),
    Column("patient_id", UUID, nullable=False),
    Column("collected_at", TIMESTAMP(timezone=True), nullable=False),
    Column("test_code", Text, nullable=False),
    Column("value", Numeric(12, 4), nullable=False),
    Column("unit", Text, nullable=False),
    Column("value_original", Numeric(14, 4), nullable=False),
    Column("unit_original", Text, nullable=False),
    Column("range_id", UUID), Column("ref_low", Numeric(12, 4)), Column("ref_high", Numeric(12, 4)),
    Column("crit_low", Numeric(12, 4)), Column("crit_high", Numeric(12, 4)),
    Column("flag", Text, nullable=False),
    Column("supersedes_id", UUID), Column("correction_reason", Text),
    Column("entered_by", UUID, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)
lab_results_current = Table("lab_results_current", metadata, *[c.copy() for c in lab_results.columns])
```

### Key queries

**Status recompute input** (one patient, all current results; uses `ix_results_patient_collected`):
```sql
SELECT id, report_id, test_code, collected_at, created_at, value, unit, flag, ref_low, ref_high
FROM lab_results_current
WHERE patient_id = :pid;
```

**Upsert status**:
```sql
INSERT INTO patient_lab_status AS s
    (patient_id, latest, egfr_category, uacr_category, egfr_stats, creat_stats, egfr_spark,
     has_critical, rapid_decline, result_count, last_result_at, rules_version, updated_at)
VALUES (:pid, :latest, :egfr_cat, :uacr_cat, :egfr_stats, :creat_stats, :spark,
        :has_critical, :rapid, :count, :last_at, :rules_version, now())
ON CONFLICT (patient_id) DO UPDATE SET
    latest = EXCLUDED.latest, egfr_category = EXCLUDED.egfr_category,
    uacr_category = EXCLUDED.uacr_category, egfr_stats = EXCLUDED.egfr_stats,
    creat_stats = EXCLUDED.creat_stats, egfr_spark = EXCLUDED.egfr_spark,
    has_critical = EXCLUDED.has_critical, rapid_decline = EXCLUDED.rapid_decline,
    result_count = EXCLUDED.result_count, last_result_at = EXCLUDED.last_result_at,
    rules_version = EXCLUDED.rules_version, version = s.version + 1, updated_at = now()
RETURNING version;
```

**Result history page** (filters added only when present):
```sql
SELECT r.id, r.report_id, r.test_code, t.name AS test_name, t.decimals, r.collected_at,
       r.value, r.unit, r.value_original, r.unit_original,
       r.ref_low, r.ref_high, r.crit_low, r.crit_high, r.flag,
       (r.supersedes_id IS NOT NULL) AS is_correction, rep.lab_name
FROM lab_results_current r
JOIN lab_reports rep ON rep.id = r.report_id
JOIN lab_tests   t   ON t.code = r.test_code
WHERE r.patient_id = :pid
  -- AND r.test_code = :test
  -- AND r.collected_at >= :from AND r.collected_at < :to
  -- AND r.flag IN ('low','high','critical_low','critical_high')      -- flag=abnormal
ORDER BY r.collected_at DESC, t.display_order, r.id
LIMIT :size OFFSET :offset;
-- total: same FROM/WHERE with count(*)
```

**Trend series**:
```sql
SELECT test_code, id, collected_at, created_at, value, flag, ref_low, ref_high
FROM lab_results_current
WHERE patient_id = :pid AND test_code = ANY(:tests)
  -- AND collected_at >= :from AND collected_at < :to
ORDER BY test_code, collected_at, created_at, id;
```

**Batch summary** and **bulk status** read only `patient_lab_status` (`= ANY(:ids)` and keyset `patient_id > :cursor ORDER BY patient_id LIMIT :limit`).

## B6. Service layer (use cases)

### B6.1 Create a lab report

`ReportService.create(patient_id, cmd, user, request_id) -> CreatedReport`

**Steps, in this order.** Cheap checks first; the network call happens before the transaction (LAB-ADR-5).

| # | Step | Failure |
|---|---|---|
| 1 | Pydantic: 1 to 8 results, each `test_code`, `value ≥ 0` (≤ 4 dp), `unit`; `collected_at` timezone-aware; `lab_name` ≤ 120; `notes` ≤ 500 | `422 VALIDATION_ERROR` |
| 2 | `collected_at ≤ now + CLOCK_SKEW_S` | `422 COLLECTED_AT_IN_FUTURE` |
| 3 | No test code twice in the request | `422 DUPLICATE_TEST_IN_REPORT` |
| 4 | Each test exists in the catalog | `422 UNKNOWN_TEST` |
| 5 | Each unit resolves for its test (B4.1) | `422 UNKNOWN_UNIT` (details list allowed units) |
| 6 | Convert to canonical; canonical ≤ `plausible_max` | `422 VALUE_IMPLAUSIBLE` ("check the value and unit") |
| 7 | `GET /internal/patients/{id}/basic` (B9) | `404 PATIENT_NOT_FOUND`, `502 UPSTREAM_UNAVAILABLE`, `504 UPSTREAM_TIMEOUT` |
| 8 | `collected_at ≥ date_of_birth` | `422 COLLECTED_BEFORE_BIRTH` |
| 9 | `age = age_on(dob, collected_at.date())`; per result: `select_range`, `flag_for`, snapshot | none |
| 10 | **Transaction:** `pg_advisory_xact_lock(patient)`; insert report; insert results; recompute status (B6.3); commit | `409`/`503` mapped from DB errors (B8) |
| 11 | Metrics + log (ids, counts, flags only) | none |
| 12 | Return `201` with report, results, counts; `Location: /labs/patients/{id}/results?report_id=…` | none |

All validation errors from steps 2 to 6 are collected and returned together in `details[]` with a `field` path such as `results[1].unit`, so the form can mark each row.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular (lab form)
    participant GW as Gateway
    participant L as lab-svc
    participant P as patient-svc
    participant DB as lab_db
    UI->>GW: POST /api/labs/patients/{id}/reports
    GW->>L: forward (JWT, X-Request-ID)
    L->>L: verify JWT, role clinician
    L->>L: validate, resolve units, convert, plausibility (no I/O)
    L->>P: GET /internal/patients/{id}/basic (JWT forwarded, timeout, retry)
    P-->>L: {id, sex, date_of_birth}
    L->>L: collected_at >= DOB, age, select range, flag, snapshot
    L->>DB: BEGIN
    L->>DB: SELECT pg_advisory_xact_lock(hash(patient_id))
    L->>DB: INSERT lab_reports
    L->>DB: INSERT lab_results (n rows)
    L->>DB: SELECT ... FROM lab_results_current WHERE patient_id
    L->>L: build_status (pure)
    L->>DB: INSERT ... ON CONFLICT DO UPDATE patient_lab_status
    L->>DB: COMMIT
    L-->>UI: 201 {report, results[], summary {n, abnormal, critical}}
```

### B6.2 Correct a result

`ReportService.correct(result_id, cmd {value, unit, reason}, user) -> Correction`

| # | Step | Failure |
|---|---|---|
| 1 | Load the target row from `lab_results` (base table) | `404 RESULT_NOT_FOUND` |
| 2 | Target must be current (no row supersedes it) | `409 RESULT_ALREADY_SUPERSEDED`, `details.current_id` = head of the chain |
| 3 | Resolve unit, convert, plausibility (test is the target's test) | `422 UNKNOWN_UNIT`, `422 VALUE_IMPLAUSIBLE` |
| 4 | New canonical value equal to the target's | `422 NO_CHANGE` |
| 5 | Flag against the **target's snapshot** (`range_id`, `ref_*`, `crit_*`), not a fresh range lookup | none |
| 6 | **Transaction:** advisory lock (target's patient); insert the new row with same `report_id`, `patient_id`, `collected_at`, `test_code`, `supersedes_id = target.id`, `correction_reason`; recompute status; commit | `409 RESULT_ALREADY_SUPERSEDED` if `ux_results_supersedes` fires (a concurrent correction won) |
| 7 | Return `201` with `{corrected: <old>, current: <new>}` | none |

Why the snapshot and not a new lookup: the correction fixes the **value**, not the interpretation context. The sample was taken on the same date from the same person, so the same range applies, and no patient-svc call is needed.

### B6.3 Recompute the read model

`StatusService.recompute(session, patient_id)` runs **inside the caller's transaction**, after the inserts and under the same advisory lock:

1. `SELECT` current results for the patient (B5).
2. `build_status(...)` (B4.6).
3. Upsert `patient_lab_status`.

If the patient has no current results (impossible after an insert, but possible during a rebuild), the row is upserted with empty values rather than deleted, so `/latest` can still answer.

### B6.4 Result history

`QueryService.results(patient_id, filters, page)`:
- `filters`: `test`, `from`, `to` (`[from, to)`), `flag` in `abnormal | critical | unknown | normal`, `report_id`, `include_superseded` (default false).
- `page` ≥ 1, `size` 1..`RESULTS_PAGE_MAX` (default 10, the Labs tab page size).
- Unknown patient → empty page (`200`). lab-svc does not ask patient-svc whether the patient exists on reads (LAB-ADR-6); the patient header call (`GET /patients/{id}`) already returns `404` for the screen.

### B6.5 Trends

`QueryService.trends(patient_id, tests, from, to)`:
- `tests`: comma-separated, 1 to 8 known codes (default `CREAT,EGFR`).
- Per test: points in the window, `trend_stats` over **those points** (so the chips under a chart describe what the chart shows, HLD §6.3), and a `reference` band taken from the snapshot on the **latest point in the window** (`ref_low`, `ref_high`). For creatinine this is automatically the patient's sex-specific band without asking patient-svc.
- For `EGFR`, the response also carries `stage_bands` (the KDIGO thresholds from `domain/ckd.py`), so the chart never hard-codes them.

### B6.6 Latest

`QueryService.latest(patient_id)` reads one `patient_lab_status` row and returns, in catalog `display_order`, one tile per test (null when no result), plus the CKD block. No row → every tile null, categories null, `200`.

### B6.7 Batch summary (patient list rows)

`StatusService.summary(ids)`: dedupe; 1..`SUMMARY_MAX_IDS`; one `= ANY(:ids)` read; returns one entry per requested id **in request order**, `has_results=false` for ids with no row.

### B6.8 Bulk status (ai-svc insights)

`StatusService.bulk(cursor, limit)`: keyset pagination over `patient_lab_status` by `patient_id`; `next_cursor` is the last id or null. ai-svc pages through it for the worklist and dashboard (HLD §10.12).

### B6.9 Catalog cache

`CatalogService` loads `lab_tests` and `lab_reference_ranges` at startup into immutable `TestDef` / `RangeDef` objects, builds the unit index, and reloads after `CATALOG_CACHE_TTL_S`. Ranges change only through a migration, so a short staleness window is harmless. `/ready` fails until the first load succeeds.

---

## B7. API specification

### B7.0 Conventions

| Item | Rule |
|---|---|
| Base path | Service serves `/labs/**` and `/internal/labs/**`. The gateway exposes `/api/labs/**` (prefix stripped) and blocks `/internal/**` |
| Auth | `Authorization: Bearer <JWT>` on every route except health. Role `clinician` |
| Request numbers | `value` accepts a JSON number or a numeric string (`"168"`), parsed as `Decimal` |
| Response numbers | JSON numbers, already rounded to stored precision. Conversion **factors** are strings so the client can use exact decimals |
| Timestamps | ISO-8601 with offset on input; UTC `Z` on output |
| Pagination | `page`, `size` → `{items, page, size, total}` (HLD §12). Bulk internal reads use keyset `cursor`, `limit` → `{items, next_cursor}` |
| Errors | HLD §12 envelope: `{"error": {"code", "message", "details", "request_id"}}` |
| Tracing | `X-Request-ID` is read, propagated to patient-svc, written to `lab_reports.request_id`, and echoed |

### Route summary

| Method | Path | Purpose | Writes | Calls patient-svc |
|---|---|---|---|---|
| GET | `/labs/tests?sex=&age=` | Catalog for the lab form preview | no | no |
| POST | `/labs/patients/{patient_id}/reports` | Add a report with 1 to 8 results | yes | **yes** |
| GET | `/labs/patients/{patient_id}/results` | Result history | no | no |
| GET | `/labs/patients/{patient_id}/trends` | Series and stats for charts | no | no |
| GET | `/labs/patients/{patient_id}/latest` | Latest per test + CKD categories | no | no |
| GET | `/labs/summary?patient_ids=` | Batch for patient list rows (≤ 50 ids) | no | no |
| POST | `/labs/results/{result_id}/correct` | Append a correction | yes | no |
| GET | `/internal/labs/patients/{patient_id}/results` · `/trends` · `/latest` | Same contracts, for ai-svc and its tools | no | no |
| GET | `/internal/labs/status?cursor=&limit=` | Bulk read model for insights | no | no |
| GET | `/health`, `/ready`, `/metrics` | Operations | no | no |

### B7.1 `GET /labs/tests`

Query: `sex` (`M | F | O`, optional), `age` (0–130, optional). With `sex`, each test carries the one range that applies today (for that sex and age). Without `sex`, each test carries all its ranges.

```json
{
  "rules_version": "lab-rules-1",
  "items": [
    {
      "code": "CREAT", "name": "Serum creatinine", "canonical_unit": "mg/dL",
      "decimals": 2, "plausible_max": 30, "display_order": 1,
      "units": [{"unit": "mg/dL", "factor": "1"}, {"unit": "µmol/L", "factor": "0.0113"}],
      "range": {"range_id": "8a1c…", "low": 0.7, "high": 1.3, "critical_low": null, "critical_high": 5.0, "text": "0.7–1.3"}
    },
    {
      "code": "EGFR", "name": "eGFR", "canonical_unit": "mL/min/1.73m²",
      "decimals": 0, "plausible_max": 200, "display_order": 2,
      "units": [{"unit": "mL/min/1.73m²", "factor": "1"}],
      "range": {"range_id": "c0d2…", "low": 90, "high": null, "critical_low": 10, "critical_high": null, "text": "≥ 90"}
    }
  ]
}
```

- `sex=O` → `range: null` for creatinine and hemoglobin (B4.2). The preview then shows "No range".
- `ETag` and `Cache-Control: private, max-age=300`. The Angular form loads it once per patient.

### B7.2 `POST /labs/patients/{patient_id}/reports`

Request:
```json
{
  "collected_at": "2026-10-21T09:30:00+05:30",
  "lab_name": "Metro Diagnostics Laboratory",
  "notes": "Fasting sample",
  "results": [
    {"test_code": "CREAT", "value": "168", "unit": "µmol/L"},
    {"test_code": "EGFR",  "value": 38,    "unit": "mL/min/1.73m²"},
    {"test_code": "K",     "value": 5.2,   "unit": "mEq/L"}
  ]
}
```

| Field | Rule |
|---|---|
| `collected_at` | Required, with offset; not more than `CLOCK_SKEW_S` in the future; not before DOB |
| `lab_name` | Optional; trimmed; 1–120 chars; default `"Unspecified laboratory"` (prototype) |
| `notes` | Optional; ≤ 500 chars (UI limits to 200) |
| `results` | 1–8 items; each test at most once |
| `results[].value` | ≥ 0, ≤ 4 decimal places, canonical value ≤ `plausible_max` |
| `results[].unit` | Must resolve for that test (aliases accepted) |

Response `201 Created`:
```json
{
  "report": {
    "id": "4e3f…", "patient_id": "9b1e…", "collected_at": "2026-10-21T04:00:00Z",
    "lab_name": "Metro Diagnostics Laboratory", "notes": "Fasting sample",
    "entered_by": "u-12…", "created_at": "2026-11-11T17:50:12Z"
  },
  "results": [
    {"id": "r1…", "test_code": "CREAT", "value": 1.898, "unit": "mg/dL",
     "value_original": 168, "unit_original": "µmol/L",
     "ref_low": 0.7, "ref_high": 1.3, "crit_low": null, "crit_high": 5.0, "flag": "high"},
    {"id": "r2…", "test_code": "EGFR", "value": 38, "unit": "mL/min/1.73m²",
     "value_original": 38, "unit_original": "mL/min/1.73m²",
     "ref_low": 90, "ref_high": null, "crit_low": 10, "crit_high": null, "flag": "low"},
    {"id": "r3…", "test_code": "K", "value": 5.2, "unit": "mmol/L",
     "value_original": 5.2, "unit_original": "mEq/L",
     "ref_low": 3.5, "ref_high": 5.0, "crit_low": 2.8, "crit_high": 6.0, "flag": "high"}
  ],
  "summary": {"n": 3, "abnormal": 3, "critical": 0}
}
```

The UI toast ("Lab report saved with 3 results. 3 abnormal.") is built from `summary`. Errors: B8.

### B7.3 `GET /labs/patients/{patient_id}/results`

| Query | Values | Default |
|---|---|---|
| `test` | a catalog code | all tests |
| `from`, `to` | ISO timestamps, half-open `[from, to)` | unbounded |
| `flag` | `abnormal`, `critical`, `unknown`, `normal` | all |
| `report_id` | uuid | none |
| `include_superseded` | `true`/`false` | `false` |
| `page`, `size` | `size` 1–100 | `1`, `10` |

```json
{
  "items": [
    {"id": "r1…", "report_id": "4e3f…", "test_code": "CREAT", "test_name": "Serum creatinine",
     "collected_at": "2026-10-21T04:00:00Z", "value": 1.898, "unit": "mg/dL",
     "value_original": 168, "unit_original": "µmol/L",
     "ref_low": 0.7, "ref_high": 1.3, "flag": "high",
     "lab_name": "Metro Diagnostics Laboratory", "is_correction": false, "superseded": false}
  ],
  "page": 1, "size": 10, "total": 57
}
```

The "Entered as" column shows `value_original unit_original` when `unit_original ≠ unit`, otherwise "Same unit" (prototype).

### B7.4 `GET /labs/patients/{patient_id}/trends`

Query: `tests` (default `CREAT,EGFR`), `from`, `to`. The Labs tab maps 6 months / 1 year / 2 years / all to `from`.

```json
{
  "patient_id": "9b1e…", "from": "2025-11-11T00:00:00Z", "to": null,
  "series": [
    {
      "test_code": "EGFR", "unit": "mL/min/1.73m²",
      "points": [{"result_id": "…", "collected_at": "2025-12-02T04:00:00Z", "value": 46, "flag": "low"}],
      "stats": {"n": 5, "first": 46, "last": 38, "abs_change": -8, "pct_change": -17.4,
                "slope_per_year": -8.9, "direction": "worsening", "rapid_decline": true,
                "span_days": 323, "first_at": "…", "last_at": "…"},
      "reference": {"low": 90, "high": null},
      "stage_bands": [{"code": "G1", "lower": 90}, {"code": "G2", "lower": 60}, {"code": "G3a", "lower": 45},
                      {"code": "G3b", "lower": 30}, {"code": "G4", "lower": 15}, {"code": "G5", "lower": 0}]
    },
    {
      "test_code": "CREAT", "unit": "mg/dL",
      "points": [], "stats": {"n": 0, "direction": "no_data"},
      "reference": null
    }
  ]
}
```

`reference` comes from the latest point's snapshot (B6.5); `null` when the window has no points.

### B7.5 `GET /labs/patients/{patient_id}/latest`

```json
{
  "patient_id": "9b1e…",
  "tests": [
    {"test_code": "CREAT", "name": "Serum creatinine", "canonical_unit": "mg/dL",
     "result": {"result_id": "…", "report_id": "…", "value": 1.82, "flag": "high",
                "collected_at": "2026-10-21T04:00:00Z", "ref_low": 0.7, "ref_high": 1.3}},
    {"test_code": "BUN", "name": "Blood urea nitrogen", "canonical_unit": "mg/dL", "result": null}
  ],
  "ckd": {
    "egfr_category": "G3b", "egfr_label": "Moderately to severely decreased",
    "egfr_value": 38, "egfr_collected_at": "2026-10-21T04:00:00Z",
    "uacr_category": "A3", "uacr_label": "Severely increased",
    "uacr_value": 480, "uacr_collected_at": "2026-10-21T04:00:00Z"
  },
  "has_critical": false, "rapid_decline": true,
  "last_result_at": "2026-10-21T04:00:00Z", "status_version": 14
}
```

Feeds the patient header (eGFR category chip and the mismatch chip, compared on the client with the established stage from patient-svc), the Labs tab CKD grid and the 8-tile latest grid, and the Overview CKD strip. `ETag: W/"status-14"`, so a re-poll returns `304` when nothing changed.

### B7.6 `GET /labs/summary?patient_ids=`

`patient_ids` is a comma-separated list of 1 to 50 UUIDs. Duplicates are removed. More than 50 → `422 TOO_MANY_IDS`.

```json
{
  "items": [
    {"patient_id": "9b1e…", "has_results": true,
     "latest_egfr": {"value": 38, "flag": "low", "collected_at": "2026-10-21T04:00:00Z"},
     "egfr_category": "G3b", "egfr_direction": "worsening",
     "spark": [{"t": "2024-12-01T04:00:00Z", "v": 54}, {"t": "2026-10-21T04:00:00Z", "v": 38}],
     "has_critical": false, "rapid_decline": true, "last_result_at": "2026-10-21T04:00:00Z"},
    {"patient_id": "77ac…", "has_results": false,
     "latest_egfr": null, "egfr_category": null, "egfr_direction": null, "spark": [],
     "has_critical": false, "rapid_decline": false, "last_result_at": null}
  ]
}
```

One entry per requested id, in request order, so the list can fill each row by index and show "No results" when `has_results` is false.

### B7.7 `POST /labs/results/{result_id}/correct`

```json
{"value": 1.6, "unit": "mg/dL", "reason": "Transcription error, value re-checked against the printed report"}
```

`reason` is 3 to 300 characters. Response `201`:

```json
{
  "corrected": {"id": "r1…", "value": 1.898, "flag": "high", "superseded": true},
  "current":   {"id": "r9…", "supersedes_id": "r1…", "value": 1.6, "unit": "mg/dL",
                "value_original": 1.6, "unit_original": "mg/dL",
                "ref_low": 0.7, "ref_high": 1.3, "flag": "high",
                "correction_reason": "Transcription error, value re-checked against the printed report"},
  "status_version": 15
}
```

There is no correction screen in the prototype. The endpoint exists because HLD v2 lists it and because append-only data needs a sanctioned way to fix a wrong entry. It can be wired to a "Correct" action in the results table later.

### B7.8 Internal per-patient mirrors

`GET /internal/labs/patients/{patient_id}/results`, `/trends`, `/latest` use the same handlers and response contracts as the public routes. Differences:

| Difference | Why |
|---|---|
| `results` accepts `limit` (≤ 50) instead of `page`/`size` | AI tool results are capped (HLD §10.4) |
| A `truncated: true` field is added when the cap cut rows | The model is told the data was cut |
| Mounted under `/internal` | Blocked at the gateway; reachable only on the private network |

### B7.9 `GET /internal/labs/status`

Query: `cursor` (uuid, optional), `limit` (1–200, default 200).

```json
{
  "items": [
    {"patient_id": "0b7f…", "latest": {"K": {"value": 6.2, "flag": "critical_high", "collected_at": "…"}, "EGFR": {"…": "…"}},
     "egfr_category": "G5", "uacr_category": "A3",
     "egfr_stats": {"n": 6, "slope_per_year": -7.3, "direction": "worsening", "rapid_decline": true, "…": "…"},
     "creat_stats": {"…": "…"},
     "has_critical": true, "rapid_decline": true, "result_count": 41,
     "last_result_at": "2026-11-05T04:00:00Z"}
  ],
  "next_cursor": "0b7f…"
}
```

The sparkline is left out: insights do not draw it.

### B7.10 Health

| Route | Returns |
|---|---|
| `GET /health` | `200 {"status":"ok"}` while the process is up |
| `GET /ready` | `200` when the DB answers `SELECT 1`, `alembic_version` equals the code's head revision, and the catalog is loaded; otherwise `503` with the failing check |
| `GET /metrics` | Prometheus text (B12) |

## B8. Error catalog

| Code | HTTP | When | `details` |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | Schema violations (types, lengths, missing fields) | `[{field, message}]` |
| `COLLECTED_AT_IN_FUTURE` | 422 | `collected_at` later than now + skew | `[{field: "collected_at"}]` |
| `COLLECTED_BEFORE_BIRTH` | 422 | `collected_at` earlier than DOB | `[{field: "collected_at"}]` |
| `DUPLICATE_TEST_IN_REPORT` | 422 | Same test twice in one request | `[{field: "results[i].test_code"}]` |
| `UNKNOWN_TEST` | 422 | Test code not in catalog | `[{field, allowed: [...]}]` |
| `UNKNOWN_UNIT` | 422 | Unit does not resolve for the test | `[{field, allowed: [...]}]` |
| `VALUE_IMPLAUSIBLE` | 422 | Canonical value > `plausible_max` | `[{field, max, unit}]` |
| `NO_CHANGE` | 422 | Correction equals the current value | none |
| `TOO_MANY_IDS` | 422 | Summary with > 50 ids | `{max: 50}` |
| `INVALID_CURSOR` | 400 | Malformed keyset cursor | none |
| `UNAUTHENTICATED` | 401 | Missing, invalid or expired JWT | none |
| `FORBIDDEN` | 403 | Role is not `clinician` | none |
| `PATIENT_NOT_FOUND` | 404 | patient-svc returned 404 (unknown or soft-deleted) | `{patient_id}` |
| `RESULT_NOT_FOUND` | 404 | Correction target does not exist | `{result_id}` |
| `RESULT_ALREADY_SUPERSEDED` | 409 | Target already corrected (pre-check or unique index) | `{current_id}` |
| `UPSTREAM_UNAVAILABLE` | 502 | patient-svc unreachable or 5xx after retries | `{upstream: "patient-svc"}` |
| `UPSTREAM_TIMEOUT` | 504 | patient-svc timed out after retries | `{upstream: "patient-svc"}` |
| `DB_UNAVAILABLE` | 503 | Pool timeout, connection error, statement timeout (`57014`) | none |
| `INTERNAL_ERROR` | 500 | Anything else, including the append-only trigger (`P0001`), which always means a bug | none |

Mapping of PostgreSQL errors:

| SQLSTATE / constraint | Mapped to |
|---|---|
| `23505` on `ux_results_supersedes` | `409 RESULT_ALREADY_SUPERSEDED` |
| `23505` on `ux_results_report_test_original` | `422 DUPLICATE_TEST_IN_REPORT` (normally caught earlier) |
| `23514` (check) | `422 VALIDATION_ERROR` |
| `23503` (foreign key) | `500 INTERNAL_ERROR` + error log (the service built an inconsistent row) |
| `P0001` (append-only) | `500 INTERNAL_ERROR` + error log |
| `57014`, connection errors | `503 DB_UNAVAILABLE` |

Example:

```json
{
  "error": {
    "code": "UNKNOWN_UNIT",
    "message": "Unit 'mmol/L' is not accepted for Blood urea nitrogen.",
    "details": [{"field": "results[2].unit", "allowed": ["mg/dL", "mmol/L (urea)"]}],
    "request_id": "req-7f2a91"
  }
}
```

## B9. patient-svc client

```python
# clients/patient.py
@dataclass(frozen=True)
class PatientBasic:
    id: UUID
    sex: Literal["M", "F", "O"]
    date_of_birth: date

class PatientClient:
    def __init__(self, http: ResilientClient, base_url: str):   # libs/common resilient httpx client
        self._http, self._base = http, base_url

    async def get_basic(self, patient_id: UUID, *, auth: str, request_id: str) -> PatientBasic:
        resp = await self._http.get(
            f"{self._base}/internal/patients/{patient_id}/basic",
            headers={"Authorization": auth, "X-Request-ID": request_id},
        )                                  # timeouts, 2 retries with backoff+jitter on connect/502/503/504
        if resp.status_code == 404:
            raise PatientNotFound(patient_id)
        resp.raise_for_status()            # other 4xx -> INTERNAL_ERROR (contract bug), logged
        body = resp.json()
        return PatientBasic(id=UUID(body["id"]), sex=body["sex"],
                            date_of_birth=date.fromisoformat(body["date_of_birth"]))
```

| Setting | Value |
|---|---|
| Timeouts | connect 1 s, read 3 s |
| Retries | 2, exponential backoff with jitter, GET only, connect errors and 502/503/504 |
| Connection pool | Bounded, 10 connections (bulkhead) |
| Headers forwarded | `Authorization` (user JWT), `X-Request-ID` |
| Contract test | The response shape `{id, sex, date_of_birth}` is asserted on both sides (B13.4) |

No caching of patient data: a report is created a few times a day per patient, and caching sex or DOB would risk using a stale value at the one moment it matters.

## B10. Transactions and concurrency

| Topic | Decision |
|---|---|
| Isolation level | `READ COMMITTED` (PostgreSQL default) |
| Transaction owner | Service layer. One transaction per write request |
| Per-patient serialization | `SELECT pg_advisory_xact_lock(hashtextextended(:patient_id::text, 0))` at the start of every write transaction. Released on commit or rollback |
| Network inside a transaction | Never (LAB-ADR-5) |
| Correction races | Advisory lock serializes them; the unique index is the backstop |

**Why the advisory lock is needed.** Two reports for the same patient committed at the same time, without the lock:

```mermaid
sequenceDiagram
    participant T1 as Tx 1 (report A)
    participant T2 as Tx 2 (report B)
    participant DB as lab_db
    T1->>DB: insert A results
    T2->>DB: insert B results
    T1->>DB: read current results (sees A, not B: B uncommitted)
    T2->>DB: read current results (sees B, not A)
    T1->>DB: upsert status built from A
    T1->>DB: commit
    T2->>DB: upsert status built from B (overwrites)
    T2->>DB: commit
    Note over DB: status misses report A, although A is committed
```

With the lock, Tx 2 waits until Tx 1 commits, then reads both. The lock is per patient (other patients are unaffected), is held for a few milliseconds, and each transaction takes exactly one lock, so deadlocks between lab-svc writes cannot happen. A hash collision between two patients only makes them wait for each other briefly.

**Double submit.** Two identical clicks create two reports. The form disables the button while saving (prototype). An `Idempotency-Key` header for POST is listed as future work in HLD §20; when added, it is a small `lab_idempotency(key, user_id, response, created_at)` table checked inside the same transaction.

## B11. Seed data and the status rebuild script

### B11.1 Shared identifiers without a network call

Lab data must reference patient UUIDs that patient-svc owns. Both seeds derive them the same way:

```python
# libs/common/seed_ids.py
SEED_NS = UUID("6f1c2d3e-0a4b-5c6d-8e9f-a0b1c2d3e4f5")      # fixed, committed
def patient_id(mrn: str) -> UUID:  return uuid5(SEED_NS, f"patient:{mrn}")
def user_id(email: str) -> UUID:   return uuid5(SEED_NS, f"user:{email}")
```

`libs/fixtures/patients.json` holds `mrn`, `sex` and `date_of_birth` for the ten synthetic patients (HLD §18). patient-svc seeds its rows from it; lab-svc reads the same file to get sex and DOB, so seeding needs no running patient-svc.

### B11.2 Synthetic results

`python -m app.seed` (refuses to run unless `SEED_ALLOW_RESET=true`):

1. `TRUNCATE patient_lab_status, lab_results, lab_reports` (row triggers do not fire on truncate).
2. For each lab profile below, generate `n` reports and feed each one through **`ReportService.create_with_basic(...)`**, the same code path as the API minus the HTTP call. Flags, snapshots and the read model are therefore produced by production code, not by seed SQL.
3. Dates are relative to today (`SEED_ANCHOR_DATE` overrides for tests), so the dashboard always looks current.

Generator, matching the prototype: report `k` of `n` is collected `last_days + span_days × (1 − k/(n−1))` days ago. eGFR moves linearly from `e0` to `e1` with ±1.5 noise (exact at both ends). Creatinine is derived from eGFR with CKD-EPI 2021 for the patient's age and sex at that date, so the two agree. BUN follows creatinine. K, Hb, Ca and Phos vary slightly around their base. UACR is recorded on every other report and the last one. Random generator seeded with `42`; the shape matches the prototype, the digits do not need to.

| MRN | Sex, age | Reports | eGFR first → last | Span / last result | Other base values | Special |
|---|---|---|---|---|---|---|
| PT-000101 | M 67 | 8 | 54 → 38 | 700 d / 20 d ago | K 5.2, Hb 11.6, Ca 9.0, Phos 4.4, UACR 480 | Creatinine of report 4 entered in µmol/L |
| PT-000102 | F 58 | 7 | 58 → 55 | 800 d / 35 d | K 4.6, Hb 12.6, Ca 9.4, Phos 3.8, UACR 120 | Stable baseline |
| PT-000103 | M 45 | 6 | 82 → 78 | 600 d / 50 d | K 4.3, Hb 14.5, Ca 9.6, Phos 3.4, UACR 210 | |
| PT-000104 | F 72 | 7 | 34 → 24 | 540 d / 12 d | K 5.4 (last 5.5), Hb 9.8, Ca 8.2, Phos 5.6, UACR 650 | |
| PT-000105 | M 39 | 4 | 30 → 74 | 150 d / 14 d | K 4.4, Hb 13.9, Ca 9.2, Phos 3.6, UACR 40 | Improving (post-AKI) |
| PT-000106 | F 63 | 6 | 44 → 38 | 700 d / 28 d | K 4.8, Hb 12.2, Ca 9.1, Phos 4.0, UACR 55 | |
| PT-000107 | M 55 | 5 | 76 → 72 | 500 d / 230 d | K 4.5, Hb 14.1, Ca 9.5, Phos 3.5, UACR 85 | Last eGFR reported +16 (discordance) |
| PT-000108 | F 50 | 0 | none | none | none | No labs at all |
| PT-000109 | M 61 | 6 | 19 → 11 | 400 d / 6 d | K 5.9 (last 6.2), Hb 9.1, Ca 7.9, Phos 6.4, UACR 900 | |
| PT-000110 | F 34 | 5 | 58 → 52 | 500 d / 25 d | K 4.2, Hb 11.5, Ca 9.0, Phos 3.9, UACR 320 | |

Lab-level outcomes asserted by the seed test (ai-svc asserts its own rule outcomes, HLD §18):

| Patient | Asserted in lab-svc |
|---|---|
| PT-000101 | `rapid_decline = true`; latest eGFR category `G3b`; UACR `A3`; one creatinine with `unit_original = µmol/L` |
| PT-000104 | `rapid_decline = true`; latest eGFR category `G4` |
| PT-000105 | eGFR `direction = improving` |
| PT-000106 | Latest eGFR category `G3b` (patient-svc has G4, so ai-svc finds the mismatch) |
| PT-000107 | `last_result_at` about 230 days ago |
| PT-000108 | No `patient_lab_status` row; summary returns `has_results = false` |
| PT-000109 | `has_critical = true` (K 6.2 `critical_high`, creatinine above 5.0 `critical_high`); category `G5`; `rapid_decline = true` |

### B11.3 Rebuild script

```
python -m app.scripts.rebuild_status            # all patients
python -m app.scripts.rebuild_status --patient-id 9b1e…
python -m app.scripts.rebuild_status --stale-only   # rows whose rules_version differs
python -m app.scripts.rebuild_status --check        # no writes; exit 1 and list ids on any difference
```

For each `patient_id` in `lab_reports` (streamed in id order): open a transaction, take the advisory lock, recompute (B6.3), commit. `--check` compares everything except `version` and `updated_at`. CI runs `--check` after the API test suite, which proves that the incremental path and a full rebuild always agree.

## B12. Observability

**Logs** (JSON, one line per request plus domain events):

| Field | Example |
|---|---|
| `service`, `route`, `method`, `status`, `latency_ms` | `lab-svc`, `/labs/patients/{patient_id}/reports`, `POST`, `201`, `84` |
| `request_id`, `user_id` | `req-7f2a91`, JWT `sub` |
| Domain event | `lab_report_created {report_id, patient_id, n, abnormal, critical, units_converted}` |

No lab values, names, notes or free text in logs.

**Metrics** (`/metrics`):

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | counter, histogram | `route`, `method`, `status` |
| `lab_results_created_total` | counter | `test_code`, `flag` |
| `lab_corrections_total` | counter | `test_code` |
| `lab_status_recompute_seconds` | histogram | none |
| `lab_patient_client_requests_total` | counter | `outcome` (`ok`, `not_found`, `retry`, `timeout`, `error`) |
| `lab_advisory_lock_wait_seconds` | histogram | none |
| `lab_catalog_reload_total` | counter | `result` |

**Alerts worth having in a real deployment:** any `INTERNAL_ERROR` from `P0001` or `23503`; `rebuild_status --check` failing; patient client error rate above 5% for 5 minutes; p95 of report creation above 500 ms.

## B13. Testing

### B13.1 Unit tests (domain, highest priority)

| Area | Cases |
|---|---|
| `unit_key` / `resolve_unit` | `µmol/L` (U+00B5), `μmol/L` (U+03BC), `umol/L`, `UMOL / L`; `mL/min/1.73m2`; ambiguous `mmol/L` for BUN rejected; unknown unit lists allowed units |
| `to_canonical` | Every factor in the catalog; half-up rounding at `decimals + 1`; the float-trap cases in B13.3 |
| `select_range` | Sex-specific over generic; age band over unbanded; `effective_from` on the collection date; sex `O` with sex-only ranges returns `None` |
| `flag_for` | Each limit exactly, just inside and just outside; `None` range → `unknown`; critical precedence |
| `classify_egfr`, `classify_uacr` | Every boundary listed in B4.4 |
| `trend_stats` | 0, 1, 2, 3 points; identical timestamps; known slope from a synthetic line; eGFR −2 exactly → worsening; creatinine +0.1 exactly → stable; −5 exactly → rapid; `pct_change` with first = 0 |
| `build_status` | Latest wins by `(collected_at, created_at, id)`; back-dated result does not replace latest; critical only from latest; spark keeps last 12 in time order |
| Import rule | `domain/` imports nothing from `fastapi`, `sqlalchemy`, `httpx` |

### B13.2 API tests (real PostgreSQL)

Setup: `lab_db_test` in the same container (B14.2); `alembic upgrade head` once per session; `TRUNCATE` between tests; JWTs signed by a test key with a stubbed JWKS; patient-svc mocked with `respx`.

| Area | Cases |
|---|---|
| Auth | No token 401; wrong audience 401; non-clinician role 403 |
| Create report | 201 with conversions and snapshots; `Location` header; status row created in the same transaction; `COLLECTED_AT_IN_FUTURE`; `COLLECTED_BEFORE_BIRTH`; duplicate test; unknown test; unknown unit; implausible value; patient 404 → 404; patient 503 then 200 (retry succeeds); patient down → 502 and **no rows written** |
| Append-only | Direct `UPDATE` and `DELETE` on both tables raise `P0001` |
| Integrity | Composite FK rejects a result whose `collected_at` differs from the report |
| Correction | 201; old row excluded from results; status recomputed; second correction of the same row 409 with `current_id`; two concurrent corrections → one 201, one 409; `NO_CHANGE` |
| Concurrency | Two concurrent reports for one patient → status contains both (advisory lock test) |
| Results | Filters `test`, `from`/`to`, `flag=abnormal` (excludes `unknown`), `include_superseded`; ordering; paging bounds |
| Trends | Window changes stats; reference from latest point; `stage_bands` only on eGFR; unknown test code 422 |
| Latest | Display order; null tiles; categories; ETag 304 |
| Summary | 51 ids → 422; unknown ids return `has_results=false`; request order kept |
| Bulk status | Keyset paging covers every row exactly once |
| Rebuild | `--check` passes after the whole suite |

### B13.3 Shared test vectors (server and browser)

`libs/test-vectors/lab_cases.json` is run by pytest against `domain/` and by Jest against the Angular preview (ADR-019). Expected values are strings to avoid float parsing in the fixture itself.

```json
[
  {"id": "creat-umol-high",    "test": "CREAT", "value": "150",  "unit": "µmol/L",        "sex": "M", "age": 67, "expect": {"canonical": "1.695", "flag": "high"}},
  {"id": "creat-umol-ascii",   "test": "CREAT", "value": "168",  "unit": "umol/L",        "sex": "M", "age": 67, "expect": {"canonical": "1.898", "flag": "high"}},
  {"id": "creat-sex-o",        "test": "CREAT", "value": "1.0",  "unit": "mg/dL",         "sex": "O", "age": 40, "expect": {"canonical": "1.000", "flag": "unknown"}},
  {"id": "egfr-round-up-g2",   "test": "EGFR",  "value": "59.95","unit": "mL/min/1.73m²", "sex": "F", "age": 50, "expect": {"canonical": "60.0",  "flag": "low", "category": "G2"}},
  {"id": "egfr-critical",      "test": "EGFR",  "value": "9",    "unit": "mL/min/1.73m2", "sex": "M", "age": 61, "expect": {"canonical": "9.0",   "flag": "critical_low", "category": "G5"}},
  {"id": "k-at-crit-limit",    "test": "K",     "value": "6.0",  "unit": "mmol/L",        "sex": "M", "age": 61, "expect": {"canonical": "6.00",  "flag": "high"}},
  {"id": "k-above-crit",       "test": "K",     "value": "6.1",  "unit": "mEq/L",         "sex": "M", "age": 61, "expect": {"canonical": "6.10",  "flag": "critical_high"}},
  {"id": "k-at-low",           "test": "K",     "value": "3.5",  "unit": "mmol/L",        "sex": "F", "age": 30, "expect": {"canonical": "3.50",  "flag": "normal"}},
  {"id": "hb-gl-low-female",   "test": "HB",    "value": "115",  "unit": "g/L",           "sex": "F", "age": 34, "expect": {"canonical": "11.50", "flag": "low"}},
  {"id": "ca-mmol",            "test": "CA",    "value": "2.2",  "unit": "mmol/L",        "sex": "F", "age": 72, "expect": {"canonical": "8.82",  "flag": "normal"}},
  {"id": "phos-mmol-high",     "test": "PHOS",  "value": "1.5",  "unit": "mmol/L",        "sex": "M", "age": 61, "expect": {"canonical": "4.65",  "flag": "high"}},
  {"id": "bun-urea",           "test": "BUN",   "value": "10",   "unit": "mmol/L (urea)", "sex": "M", "age": 55, "expect": {"canonical": "28.00", "flag": "high"}},
  {"id": "uacr-mgmmol-a2",     "test": "UACR",  "value": "30",   "unit": "mg/mmol",       "sex": "F", "age": 34, "expect": {"canonical": "265.2", "flag": "high", "uacr_category": "A2"}}
]
```

Checks on two of these: `150 × 0.0113 = 1.695` exactly in decimal, but `150 * 0.0113` in JavaScript is `1.6949999999999998`, so a naive `Math.round(x * 1000) / 1000` can land on `1.695` or `1.694` depending on the path; `2.2 × 4.008 = 8.8176 → 8.82`. The Angular preview therefore uses an exact decimal library (for example `big.js`) with half-up rounding. The vectors make any drift fail CI on both sides.

### B13.4 Contract tests

| Contract | Tested on |
|---|---|
| `GET /internal/patients/{id}/basic` → `{id, sex, date_of_birth}` | lab-svc (consumer stub) and patient-svc (provider response) |
| `/internal/labs/status` item shape | lab-svc (provider) and ai-svc (consumer) |
| `/internal/labs/patients/{id}/trends` and `/results` | lab-svc and ai-svc tool wrappers |

## B14. Running on the existing Postgres container

The project reuses a PostgreSQL container that is already running (HLD §17.2, last paragraph). lab-svc needs three things from it: a role, a database, and network reachability. Nothing else on the container changes.

### B14.1 Inspect the container

```bash
# find it
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Networks}}'

export PG_CONTAINER=<container-name>
export PG_SUPERUSER=$(docker exec "$PG_CONTAINER" printenv POSTGRES_USER || echo postgres)

# version: 13 or later is required (gen_random_uuid, partial indexes, EXECUTE FUNCTION)
docker exec "$PG_CONTAINER" psql -U "$PG_SUPERUSER" -d postgres -Atc 'SHOW server_version;'

# what already exists
docker exec "$PG_CONTAINER" psql -U "$PG_SUPERUSER" -d postgres -c '\l' -c '\du'
```

If the four databases from HLD §5.1 were already created by `init-databases.sh`, skip B14.2 and only verify. If not, B14.2 creates the lab part on its own, idempotently.

### B14.2 Create the role and the databases (idempotent)

`infra/postgres/lab-db.sql`:

```sql
\set ON_ERROR_STOP on

-- role (password passed in with -v lab_pw=...)
SELECT format('CREATE ROLE lab_svc LOGIN PASSWORD %L', :'lab_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_svc') \gexec
SELECT format('ALTER ROLE lab_svc PASSWORD %L', :'lab_pw') \gexec

-- databases
SELECT 'CREATE DATABASE lab_db OWNER lab_svc'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'lab_db') \gexec
SELECT 'CREATE DATABASE lab_db_test OWNER lab_svc'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'lab_db_test') \gexec

-- isolation: only lab_svc may connect (HLD §5.1 rule 1)
REVOKE CONNECT ON DATABASE lab_db      FROM PUBLIC;
REVOKE CONNECT ON DATABASE lab_db_test FROM PUBLIC;
GRANT  CONNECT ON DATABASE lab_db      TO lab_svc;
GRANT  CONNECT ON DATABASE lab_db_test TO lab_svc;

-- lab_svc owns the public schema in its databases (needed on PostgreSQL 15+)
\c lab_db
ALTER SCHEMA public OWNER TO lab_svc;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
\c lab_db_test
ALTER SCHEMA public OWNER TO lab_svc;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

Run it:

```bash
export LAB_DB_PW='change-me-locally'      # keep in .env, never in git
docker exec -i "$PG_CONTAINER" psql -U "$PG_SUPERUSER" -d postgres \
  -v lab_pw="$LAB_DB_PW" < infra/postgres/lab-db.sql
```

### B14.3 Network

The services reach Postgres by container name on a shared user-defined network. An existing container can join a network without being recreated:

```bash
docker network create nephro-net 2>/dev/null || true
docker network connect nephro-net "$PG_CONTAINER" 2>/dev/null || true   # no-op if already connected
docker network inspect nephro-net --format '{{range .Containers}}{{.Name}} {{end}}'
```

Inside the network the host is `$PG_CONTAINER` and the port is `5432`, whatever port the container publishes on the host.

### B14.4 Environment

`services/lab/.env` (gitignored; `.env.example` committed):

```
LAB_DATABASE_URL=postgresql+asyncpg://lab_svc:change-me-locally@<pg-container-name>:5432/lab_db
LAB_TEST_DATABASE_URL=postgresql+asyncpg://lab_svc:change-me-locally@<pg-container-name>:5432/lab_db_test
PATIENT_SVC_URL=http://patient-svc:8000
JWKS_URL=http://auth-svc:8000/.well-known/jwks.json
JWT_ISSUER=nephro-auth
JWT_AUDIENCE=nephro-api
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
LOG_LEVEL=INFO
```

If the password contains `@`, `:` or `/`, URL-encode it in the URL.

### B14.5 Dockerfile

Build context is the repository root, so `libs/common` can be copied in.

```dockerfile
# services/lab/Dockerfile
FROM python:3.12-slim AS build
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY libs/common ./libs/common
COPY services/lab/pyproject.toml ./services/lab/
RUN pip wheel --wheel-dir /wheels ./libs/common ./services/lab

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /srv
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY services/lab/alembic.ini ./
COPY services/lab/alembic ./alembic
COPY services/lab/app ./app
COPY libs/fixtures ./fixtures
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
```

### B14.6 Compose (existing Postgres variant)

`docker-compose.existing-pg.yml` replaces the `postgres` service of the main compose file with the external network:

```yaml
services:
  lab-svc:
    build:
      context: .
      dockerfile: services/lab/Dockerfile
    env_file: services/lab/.env
    expose: ["8000"]                 # internal only; the gateway is the public port
    networks: [nephro-net]
    restart: unless-stopped

networks:
  nephro-net:
    external: true
```

The other services and the gateway join `nephro-net` the same way.

### B14.7 Migrate, seed, run

```bash
# 1. schema + catalog + ranges
docker compose -f docker-compose.existing-pg.yml run --rm lab-svc alembic upgrade head

# 2. synthetic data (dev only)
docker compose -f docker-compose.existing-pg.yml run --rm -e SEED_ALLOW_RESET=true lab-svc python -m app.seed

# 3. start
docker compose -f docker-compose.existing-pg.yml up -d lab-svc

# 4. readiness from inside the network
docker compose -f docker-compose.existing-pg.yml exec lab-svc \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"
```

Makefile shortcuts:

| Target | Runs |
|---|---|
| `make lab-db` | B14.2 script against `$PG_CONTAINER` |
| `make lab-migrate` | `alembic upgrade head` |
| `make lab-seed` | Seed with reset |
| `make lab-up` | Start the service |
| `make lab-test` | `pytest` against `lab_db_test` |
| `make lab-check` | `rebuild_status --check` |

### B14.8 Verify

```bash
# lab_svc can connect and sees its tables
docker exec -it "$PG_CONTAINER" psql "postgresql://lab_svc:$LAB_DB_PW@localhost/lab_db" -c '\dt'

# seed counts
docker exec "$PG_CONTAINER" psql "postgresql://lab_svc:$LAB_DB_PW@localhost/lab_db" -Atc \
 "SELECT (SELECT count(*) FROM lab_reports), (SELECT count(*) FROM lab_results), (SELECT count(*) FROM patient_lab_status);"

# isolation: another service role is refused (expect: permission denied for database "lab_db")
docker exec "$PG_CONTAINER" psql "postgresql://patient_svc:$PATIENT_DB_PW@localhost/lab_db" -c 'select 1'

# append-only (expect: ERROR: table lab_results is append-only)
docker exec "$PG_CONTAINER" psql "postgresql://lab_svc:$LAB_DB_PW@localhost/lab_db" -c \
 "UPDATE lab_results SET value = value;"
```

`localhost` works here because `psql` runs inside the Postgres container.

### B14.9 Running lab-svc on the host instead (optional)

If the container publishes 5432 on the host (`docker ps` shows `0.0.0.0:5432->5432/tcp`), lab-svc can run with `uvicorn` directly:

```bash
cd services/lab
LAB_DATABASE_URL=postgresql+asyncpg://lab_svc:$LAB_DB_PW@localhost:5432/lab_db \
PATIENT_SVC_URL=http://localhost:8002 \
uvicorn app.main:app --reload --port 8003
```

If the port is not published, use the Docker network (B14.3); publishing a port requires recreating the container, which this setup avoids.

### B14.10 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `password authentication failed for user "lab_svc"` | Password in `.env` differs from the role | Re-run B14.2 (it resets the password) or fix `.env`; URL-encode special characters |
| `permission denied for schema public` during migration | PostgreSQL 15+ and schema not owned by `lab_svc` | The `ALTER SCHEMA public OWNER TO lab_svc` lines in B14.2 |
| `could not translate host name` | lab-svc and Postgres not on the same network | B14.3 |
| `function gen_random_uuid() does not exist` | PostgreSQL older than 13 | Upgrade, or `CREATE EXTENSION pgcrypto` in `lab_db` as superuser |
| `no pg_hba.conf entry` | Container restricts remote hosts | Official image allows all hosts with password auth by default; if customized, add a `host lab_db lab_svc samenet scram-sha-256` line |
| `/ready` says migrations not at head | Image updated, migration not run | `make lab-migrate` |
| `too many connections` | Shared instance limit | Lower pool sizes, or add PgBouncer (HLD §13) |

## B15. Performance and scaling notes

| Path | Cost |
|---|---|
| Create report | 1 patient-svc GET + 1 transaction: lock, 1 + n inserts, 1 indexed read of the patient's current results (tens to hundreds of rows), 1 upsert |
| Results page | Index range scan on `ix_results_patient_collected`, anti-join probes on `ux_results_supersedes`, 2 small joins, `LIMIT` |
| Trends | Index scan on `ix_results_trend` per test |
| Latest, summary | 1 primary-key read; `= ANY` over ≤ 50 keys |
| Bulk status | Keyset scan on the primary key, 200 rows per page |

**Growth path, in order of need:**

1. More replicas (stateless). Watch total connections: `services × replicas × (pool + overflow)` must stay under `max_connections`; add PgBouncer in transaction mode when it gets close.
2. Read replica for `results` and `trends` if reads dominate. `latest` and `summary` stay on the primary to keep the "never stale" property.
3. Time partitioning of `lab_results` by `collected_at`. Requirements already met by this design: unique indexes on a partitioned table must include the partition key, so `ux_results_supersedes` becomes `(supersedes_id, collected_at)`, which works because a correction carries its original's `collected_at`; the composite FK from results to reports already includes `collected_at`.
4. Analyzer or HL7/FHIR feed: the first point where an outbox and events are justified (ADR-005). lab-svc would then also publish `lab.report.created` for a materialized worklist in ai-svc.

## B16. Open items to confirm

| # | Item | Current assumption | Action |
|---|---|---|---|
| 1 | Reference ranges and critical limits | Prototype values (B3.2) | Replace with the **supplied ranges file** in migration 0002 before seeding; set `source` accordingly |
| 2 | CKD classification criteria | KDIGO thresholds (B4.4) | Align with the supplied classification file |
| 3 | Creatinine factor | `0.0113` (prototype); the exact value is `1/88.4 ≈ 0.011312` | Pick one; it is data in `lab_tests`, and the shared vectors follow it |
| 4 | eGFR critical low of 10 | From the prototype | Confirm it is wanted; it makes eGFR < 10 a "needs attention" trigger |
| 5 | `flag=abnormal` and `unknown` | Excludes `unknown` (the prototype's filter included it) | Confirm; `flag=unknown` is available separately |
| 6 | Sex `O` | No range for sex-specific tests → `unknown` | Confirm, or supply ranges for it |
| 7 | Age-banded ranges | Supported by the schema, none seeded | Add if the supplied file has them |

## B17. Build checklist

1. B14.1–B14.3: inspect the container, create `lab_svc`, `lab_db`, `lab_db_test`, join `nephro-net`.
2. Skeleton: settings, JWT dependency from `libs/common`, health routes, error envelope.
3. Migration 0001 (tables, indexes, triggers, view) and 0002 (catalog and ranges). Verify with B14.8.
4. `domain/` with unit tests and the shared vectors (B13.1, B13.3). Write these first.
5. Repositories and `StatusService.recompute`, then `ReportService.create` with the patient client mocked.
6. Read endpoints: results, trends, latest, summary, internal mirrors, bulk status.
7. Correction endpoint.
8. Seed and rebuild script; `rebuild_status --check` in CI.
9. API and contract tests green; export OpenAPI to `docs/api/lab-svc.json`.
10. Wire to the gateway and the Angular Labs tab, lab form preview and patient list summary.

