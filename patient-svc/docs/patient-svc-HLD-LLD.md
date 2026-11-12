# patient-svc — High-Level and Low-Level Design

**Project:** General Nephrology EMR (NephroCare)
**Service:** `patient-svc` — the clinical chart
**Parent document:** `HLD-v2.md` (system HLD). Every rule in HLD v2 §4.2, §5.3, §11.2 is binding here. This document adds the service-level design and the implementation detail.
**UI reference:** `nephrocare-emr-platform.html` (prototype). Field names, validation messages and behaviors below are taken from it.
**Database:** `patient_db` on the **existing PostgreSQL Docker container** (no new Postgres container is created).
**Stack:** Python 3.12 · FastAPI (async) · SQLAlchemy 2.x async + asyncpg · Alembic · Pydantic v2
**Data:** synthetic patients only.
**Version:** 1.0 · 11 Nov 2026

---

## Contents

**Part A — High-level design**
1. Purpose, scope and responsibilities
2. Requirements traceability
3. Context and dependencies
4. Module decomposition
5. Service-level design decisions
6. Main data flows
7. Non-functional targets

**Part B — Low-level design**
8. Runtime environment: the existing Docker PostgreSQL container
9. Physical data model (full DDL)
10. ORM mapping
11. API contracts (public)
12. API contracts (cross-patient and internal)
13. Service-layer algorithms
14. Encounter state machine and immutability
15. Search, sort and pagination
16. Concurrency and transactions
17. Security and authorization
18. Error handling and error catalog
19. Audit trail
20. Observability
21. Configuration
22. Code layout
23. Migrations and seed data
24. Container image and compose wiring
25. Testing plan
26. Performance and capacity
27. Deltas to HLD v2 and open questions
28. Build checklist

---

# Part A — High-level design

## 1. Purpose, scope and responsibilities

patient-svc owns **the patient chart**: everything a clinician writes about a patient except lab results and AI output. It is one consistency boundary (HLD v2 §3.3, ADR-002): a patient, their problem list, medications, allergies and encounters change together inside local ACID transactions.

### 1.1 What it owns

| Area | Data | Behaviour |
|---|---|---|
| Patients | Demographics, contact details, past medical / family / social history, `allergy_status`, `established_ckd_stage`, MRN | Register, edit (version-checked), soft delete, search, list with filters and sorting |
| Problem list | `patient_conditions` (nephrology diagnoses and comorbidities, one active primary) | Add, set primary, resolve, reactivate, soft delete |
| Medications | `medications` | Add, edit, discontinue (end date = today) |
| Allergies | `allergies` + derived `allergy_status` | Add, remove, confirm "no known allergies" |
| Encounters | `encounters`, `encounter_vitals`, `encounter_diagnoses` | Draft, edit draft, finalize, delete draft, view history; diagnoses can be added to the problem list on finalize |
| Dashboard queries it can answer alone | Draft encounters, upcoming follow-ups | Cross-patient encounter queries |
| Internal reads | Patient basics, full chart, tool-sized chart slices, bulk chart export | For lab-svc (basics) and ai-svc (chart, tools, worklist) |
| Audit | `audit_events` | Every chart read and every mutation |

### 1.2 What it does not do

| Not here | Where it lives | Why |
|---|---|---|
| Lab results, reference ranges, eGFR category, trends | lab-svc | Different domain rules and access pattern |
| Gap rules, "needs attention", dashboard KPIs | ai-svc `insights/` | One rule engine for every screen (ADR-016) |
| AI summaries | ai-svc | Separate failure domain and store |
| Users, passwords, tokens | auth-svc | Security boundary |
| Sorting the list by latest eGFR | Not supported | Cross-service value (ADR-020) |

### 1.3 Position in the dependency graph

patient-svc makes **no outbound calls**. lab-svc and ai-svc depend on it; it depends on nothing but its own database and the JWKS public keys. That makes it the root of the read graph, so it must be the most available service and the cheapest to call.

---

## 2. Requirements traceability

| PS / prototype requirement | Design element | Section |
|---|---|---|
| A. List patients with ID, name, age, gender, primary diagnosis | `GET /patients` row shape; age from DOB; primary from `is_primary` | 11.2, 15 |
| Search by name or patient ID | Token trigram search on `search_name`, MRN prefix/exact | 15.1 |
| Demographics and medical history | `patients` columns; `GET /patients/{id}` | 9, 11.3 |
| Comorbidities and established diagnoses | `patient_conditions` (`category`, `is_primary`, `status`) + `established_ckd_stage` | 9, 11.5 |
| Current medications and allergies | `medications`, `allergies`, `allergy_status` | 11.6, 11.7 |
| Previous encounters | `GET /patients/{id}/encounters` | 11.8 |
| B. Create encounter: date, vitals, complaint, symptoms, exam, assessment, diagnoses, plan, follow-up | `POST /patients/{id}/encounters` | 11.8, 13.4 |
| Save and retrieve encounters | Draft/final lifecycle, list and detail | 14 |
| Prototype: list filters (sex, stage incl. none, needs attention) and sorts (name, ID, age, diagnosis, last visit) | `sex`, `stage`, `ids`, `sort`, `dir` params | 15 |
| Prototype: "Needs attention" filter | `ids=` from ai-svc worklist | 15.3 |
| Prototype: established CKD stage dropdown G1…G5 incl. G3a/G3b | `PATCH /patients/{id}`, CHECK constraint | 9.2, 11.3 |
| Prototype: diagnosis "Add to problem list" | Problem-list linkage on finalize, same transaction | 13.5 |
| Prototype: delete draft, edit draft, final read-only | State machine + DB trigger | 14 |
| Prototype: discontinue medication, show discontinued | `PATCH .../medications/{mid}`, `status` filter | 11.6 |
| Prototype: remove last allergy returns status to unknown; confirm no known allergies | Allergy rules | 13.7 |
| Prototype: "This record was changed by someone else" | Optimistic locking (`version`) → `409 VERSION_CONFLICT` | 16.2 |
| Prototype dashboard: drafts and upcoming follow-ups | `GET /encounters?status=draft`, `?upcoming_followups=true` | 12.1 |
| lab-svc needs sex and DOB for range selection | `GET /internal/patients/{id}/basic` | 12.2 |
| ai-svc summary context and tools | `/internal/patients/{id}/chart` and tool endpoints | 12.3, 12.4 |
| ai-svc worklist and dashboard | `/internal/patients/charts` bulk export | 12.5 |
| Audit "who looked at / changed this chart" | `audit_events`, same transaction | 19 |
| Use the existing Docker Postgres | Idempotent provisioning script, external network | 8 |

---

## 3. Context and dependencies

```mermaid
flowchart LR
    UI[Angular SPA] -->|"HTTPS /api/patients/**, /api/encounters/**"| GW[API Gateway]
    GW -->|"JWT + X-Request-ID forwarded"| PS

    subgraph PS[patient-svc]
        R[routers] --> S[services] --> REPO[repositories]
    end

    LAB[lab-svc] -->|"GET /internal/patients/{id}/basic"| PS
    AI[ai-svc] -->|"GET /internal/patients/{id}/chart · tool endpoints · /internal/patients/charts"| PS

    REPO -->|"asyncpg pool, role patient_svc"| DB[("patient_db<br/>on the existing<br/>Postgres container")]
    PS -.->|"JWKS fetched and cached"| AUTH[auth-svc /.well-known/jwks.json]
```

| Dependency | Direction | Failure impact | Mitigation |
|---|---|---|---|
| `patient_db` | outbound | Service cannot serve anything | `/ready` fails, gateway returns `502/503`; connection retry at start-up; statement timeout |
| auth-svc JWKS | outbound, rare | New `kid` cannot be verified | JWKS cached (TTL 5 min) and kept on fetch failure; existing tokens keep working |
| lab-svc, ai-svc | inbound only | None for patient-svc | — |

---

## 4. Module decomposition

Modules follow the HLD v2 split (`patients/`, `conditions/`, `medications/`, `allergies/`, `encounters/`, `internal/`). Each module has its own router, service and repository; they share the database session and the audit writer.

| Module | Tables it writes | Public routes | Internal routes |
|---|---|---|---|
| `patients` | `patients` | `GET/POST /patients`, `GET/PATCH/DELETE /patients/{id}` | `GET /internal/patients/{id}/basic` |
| `conditions` | `patient_conditions` | `GET/POST /patients/{id}/conditions`, `PATCH/DELETE .../{cid}` | `GET /internal/patients/{id}/conditions` |
| `medications` | `medications` | `GET/POST /patients/{id}/medications`, `PATCH .../{mid}` | via `medications-allergies` |
| `allergies` | `allergies`, `patients.allergy_status` | `GET/POST /patients/{id}/allergies`, `DELETE .../{aid}` | `GET /internal/patients/{id}/medications-allergies` |
| `encounters` | `encounters`, `encounter_vitals`, `encounter_diagnoses`, `patient_conditions` (problem-list linkage) | `/patients/{id}/encounters/**`, `GET /encounters` | `GET /internal/patients/{id}/encounters` |
| `internal` | none (reads) | — | `/internal/patients/{id}/chart`, `/internal/patients/charts` |
| `audit` | `audit_events` | — | — |

Module rule: a module may **read** another module's repository (for example, encounters reads conditions during finalize) but all writes to a table go through that table's owning module service. The single exception is the problem-list linkage, which calls `ConditionService.link_or_create(...)` inside the encounter transaction.

---

## 5. Service-level design decisions

These are decisions HLD v2 leaves open. Each is short; deltas to HLD v2 are collected in §27.

| ID | Decision | Reason |
|---|---|---|
| **P-01** | The **patient row is the aggregate lock**. Any write that touches a patient-level invariant (primary diagnosis, `allergy_status`, problem-list linkage) first runs `SELECT … FROM patients WHERE id = $1 FOR UPDATE`. | Serializes per-patient invariants without SERIALIZABLE isolation or retries. Contention is one clinician on one chart. |
| **P-02** | MRN comes from a **database sequence** (`PT-` + 6-digit zero-padded), assigned by a column default. | No "max+1" race (the prototype computes max+1 in memory, which breaks with two concurrent registrations). |
| **P-03** | Seeded patients and clinicians use **deterministic UUIDv5** ids derived from the MRN or email. | lab-svc's seed and auth-svc's seed can reference the same ids without calling patient-svc (cross-service seed with no runtime coupling). |
| **P-04** | **Problem-list linkage happens at finalize**, not on draft save. | Draft diagnoses are tentative; the prototype adds conditions only on finalize. Linkage runs in the finalize transaction. |
| **P-05** | Encounters store `clinician_id` (JWT `sub`) **and** `clinician_name` (JWT `name` claim) as a snapshot. | The encounter list shows the clinician name; patient-svc must not call auth-svc to render history. Requires the `name` claim (see §27). |
| **P-06** | **Final encounters are immutable at the database level** (trigger), not only in the service. | Defence in depth for a medical-record invariant. |
| **P-07** | **Audit rows are written in the same transaction** as the change they describe. | No change without its audit row; no audit row for a rolled-back change. |
| **P-08** | `allergy_status = has_allergies` is **derived** from allergy rows; clients can only set `unknown` or `nka`, and only when no active allergies exist. | Keeps the "unknown vs none" distinction trustworthy, which the gap rules depend on. |
| **P-09** | "Today" for date-only rules (DOB not future, onset, follow-up ≥ today, `next_follow_up`) is computed in **`CLINIC_TZ`** (default `Asia/Kolkata`). Timestamps are stored in UTC. | A follow-up "today" in IST must not flip at 05:30 local time because the server runs in UTC. |
| **P-10** | The existing container is provisioned by an **idempotent script run with `docker exec`**, not by `/docker-entrypoint-initdb.d`. | initdb scripts only run on an empty data volume, which the existing container does not have. |
| **P-11** | Schema migrations run on start-up **under a Postgres advisory lock**. | Safe with more than one replica starting at once. |
| **P-12** | Internal `/chart` responses **exclude name, MRN and contact details** at the source. | Data minimization before the data leaves the service; ai-svc's minimizer is a second layer, not the only one. |

---

## 6. Main data flows

### 6.1 Patient list with search (first of the two list calls)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant GW as Gateway
    participant PS as patient-svc
    participant DB as patient_db
    UI->>GW: GET /api/patients?q=kul&stage=G3b&sort=visit&dir=desc&page=1&size=8
    GW->>PS: GET /patients?... (JWT, X-Request-ID)
    PS->>PS: verify JWT, require clinician, parse q → name tokens
    PS->>DB: filtered CTE + LATERAL primary dx + LATERAL last final visit, count(*) OVER ()
    DB-->>PS: ≤ 8 rows + total
    PS-->>UI: 200 {items, page, size, total}
    Note over UI: then GET /api/labs/summary?patient_ids=… fills eGFR and sparkline (lab-svc)
```

### 6.2 Create and finalize an encounter with problem-list linkage

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant PS as patient-svc
    participant DB as patient_db
    UI->>PS: POST /patients/{id}/encounters {status:"final", diagnoses:[{icd10_code:"N18.32", add_to_problem_list:true}], vitals:{…}}
    PS->>PS: Pydantic validation (vitals ranges, sys > dia, finalize fields)
    PS->>DB: BEGIN
    PS->>DB: SELECT … FROM patients WHERE id=$1 AND deleted_at IS NULL FOR UPDATE
    PS->>DB: INSERT encounters (status='draft') RETURNING id
    PS->>DB: INSERT encounter_vitals, INSERT encounter_diagnoses
    loop each diagnosis with add_to_problem_list
        PS->>DB: find active condition (same ICD) → link, or resolved → reactivate, or INSERT
        PS->>DB: UPDATE encounter_diagnoses SET condition_id=…
    end
    PS->>DB: UPDATE encounters SET status='final', finalized_at=now()
    PS->>DB: INSERT audit_events (encounter.finalize)
    PS->>DB: COMMIT
    PS-->>UI: 201 {encounter, problem_list_changes:{added:1, reactivated:0, linked:0}}
```

### 6.3 lab-svc checks the patient before saving a lab report

```mermaid
sequenceDiagram
    participant LAB as lab-svc
    participant PS as patient-svc
    participant DB as patient_db
    LAB->>PS: GET /internal/patients/{id}/basic (user JWT, X-Request-ID)
    PS->>DB: SELECT id, sex, date_of_birth FROM patients WHERE id=$1 AND deleted_at IS NULL
    alt found
        PS-->>LAB: 200 {id, sex, date_of_birth}
    else missing or soft-deleted
        PS-->>LAB: 404 NOT_FOUND
    end
```

### 6.4 ai-svc pages through all charts for the worklist

```mermaid
sequenceDiagram
    participant AI as ai-svc insights
    participant PS as patient-svc
    loop until next_cursor is null
        AI->>PS: GET /internal/patients/charts?cursor=<last id>&limit=200
        PS-->>AI: 200 {items:[rule fields per patient], next_cursor}
    end
```

---

## 7. Non-functional targets

| Attribute | Target (clinic scale: ≤ 10,000 patients, ≤ 200,000 encounters) |
|---|---|
| Latency p95 | List/search ≤ 150 ms · patient detail ≤ 80 ms · encounter create/finalize ≤ 200 ms · `/internal/.../basic` ≤ 20 ms · one bulk page of 200 ≤ 300 ms |
| Throughput | 50 req/s per replica sustained (I/O bound, async) |
| Availability | Stateless; restart-safe; any replica can serve any request |
| Consistency | Every write is one local ACID transaction; no eventual consistency inside the service |
| Durability | Soft delete only for clinical rows; audit is append-only |
| Security | JWT verified on every request; DB role can connect only to `patient_db`; no PHI in logs |
| Operability | `/health`, `/ready`, `/metrics`, JSON logs with `request_id` |

---

# Part B — Low-level design

## 8. Runtime environment: the existing Docker PostgreSQL container

The system HLD (v2 §17.2) notes that an existing Postgres container can be reused. This section is the exact procedure for patient-svc. The same pattern applies to the other three services.

### 8.1 Topology

```mermaid
flowchart LR
    subgraph HOST[Docker host]
        subgraph PGNET["external network: nephro-pgnet"]
            PG[("existing Postgres container<br/>alias: nephro-pg<br/>databases: patient_db, patient_db_test (+ others)")]
        end
        subgraph COMPOSE["compose project: nephro-emr (network: backend)"]
            GW[gateway :8080]
            PS[patient-svc :8000]
            LAB[lab-svc]
            AI[ai-svc]
        end
        PS -- "joined to both networks" --- PGNET
        GW --- PS
        LAB --- PS
        AI --- PS
    end
    DEV[uvicorn on the host, dev only] -. "localhost:<published port>" .-> PG
```

- The Postgres container is **not** part of the compose project, so compose cannot start it, wait for it or delete its volume.
- The compose project and the existing container share an **external Docker network** (`nephro-pgnet`). The Postgres container joins it with the alias `nephro-pg`, so connection strings do not depend on the container's real name.
- Running patient-svc directly on the host during development uses the container's published port instead.

### 8.2 Prerequisites and discovery

Run these once and note the answers. `<pg>` is the container name.

```bash
# 1. Find the container, its image tag and published ports
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' | grep -i postgres

# 2. Server version and connection budget (version must be >= 13 for gen_random_uuid and trusted pg_trgm)
docker exec -it <pg> psql -U postgres -c 'select version();' -c 'show max_connections;'

# 3. Superuser name used by the image (POSTGRES_USER, default "postgres")
docker exec <pg> printenv POSTGRES_USER

# 4. Networks the container is already on
docker inspect <pg> --format '{{json .NetworkSettings.Networks}}'
```

| Check | Requirement | If not met |
|---|---|---|
| Major version | ≥ 13 | On 12 or older, add `CREATE EXTENSION IF NOT EXISTS pgcrypto;` to the provisioning script (for `gen_random_uuid()`) |
| `max_connections` | ≥ 100 (default) | Pool sizes in §21 assume 100; budget below |
| Superuser access | Needed once, for provisioning only | Ask whoever owns the container to run §8.3 |
| Encoding | UTF8 | The script creates the database with `ENCODING 'UTF8' TEMPLATE template0` regardless |

**Connection budget on one instance (100 connections):**

| Consumer | Per replica | Replicas (dev) | Total |
|---|---|---|---|
| auth-svc | 5 + 5 overflow | 1 | 10 |
| **patient-svc** | **5 + 5 overflow** | **1** | **10** |
| lab-svc | 5 + 5 | 1 | 10 |
| ai-svc | 5 + 5 | 1 | 10 |
| Tests, psql, migrations | — | — | ~10 |
| Headroom (superuser reserved: 3) | | | ~50 |

`patient_svc` is given `CONNECTION LIMIT 25` so a leak in this service cannot starve the others.

### 8.3 Provisioning script (idempotent)

`infra/postgres/provision-patient-db.sql` — safe to run any number of times. It creates or updates the role, creates the two databases if missing, locks them down and installs `pg_trgm`.

```sql
-- infra/postgres/provision-patient-db.sql
-- Run as the container superuser, connected to the "postgres" database.
-- Required psql variable: patient_pw
\set ON_ERROR_STOP on

-- 1. Role (create if missing, then always re-assert attributes and password)
SELECT format('CREATE ROLE patient_svc LOGIN PASSWORD %L', :'patient_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patient_svc')
\gexec
ALTER ROLE patient_svc WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    CONNECTION LIMIT 25 PASSWORD :'patient_pw';

-- 2. Databases (CREATE DATABASE cannot run inside DO blocks, hence \gexec)
SELECT 'CREATE DATABASE patient_db OWNER patient_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'patient_db')
\gexec
SELECT 'CREATE DATABASE patient_db_test OWNER patient_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'patient_db_test')
\gexec

-- 3. Only the owning role may connect (engine-enforced isolation, HLD v2 §5.1)
REVOKE CONNECT, TEMPORARY ON DATABASE patient_db      FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE patient_db_test FROM PUBLIC;
GRANT  CONNECT, TEMPORARY ON DATABASE patient_db      TO patient_svc;
GRANT  CONNECT, TEMPORARY ON DATABASE patient_db_test TO patient_svc;

-- 4. Per-database session defaults for the service role
ALTER ROLE patient_svc IN DATABASE patient_db SET statement_timeout = '5s';
ALTER ROLE patient_svc IN DATABASE patient_db SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE patient_svc IN DATABASE patient_db SET lock_timeout = '3s';
ALTER ROLE patient_svc IN DATABASE patient_db SET timezone = 'UTC';

-- 5. Extensions and schema ownership, inside each database
\connect patient_db
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER SCHEMA public OWNER TO patient_svc;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

\connect patient_db_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER SCHEMA public OWNER TO patient_svc;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

Notes:
- `pg_trgm` is installed by the superuser so the migration does not need elevated rights. The baseline migration still runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`, which is a no-op when present.
- The password is passed as a psql variable and never written into the file.
- Nothing here touches other services' databases. The equivalent scripts for auth, lab and ai follow the same template.

### 8.4 Running the provisioning

```bash
# From the repository root. PATIENT_DB_PW comes from .env (never committed).
set -a; source .env; set +a

docker exec -i <pg> \
  psql -U "${PG_SUPERUSER:-postgres}" -d postgres \
       -v patient_pw="${PATIENT_DB_PW}" -f - \
  < infra/postgres/provision-patient-db.sql
```

`make db-provision-patient` wraps this command.

### 8.5 Networking options

| Option | When | How | `PATIENT_DATABASE_URL` host |
|---|---|---|---|
| **A. External network (recommended)** | patient-svc runs in compose | `docker network create nephro-pgnet` (once), then `docker network connect --alias nephro-pg nephro-pgnet <pg>`. Compose declares `nephro-pgnet` as `external: true` (§24.2) | `nephro-pg:5432` |
| B. Host gateway | The container must not join another network | Postgres must publish a port; in compose add `extra_hosts: ["host.docker.internal:host-gateway"]` | `host.docker.internal:<published port>` |
| C. Service on the host (dev) | Running `uvicorn` locally | Uses the published port | `localhost:<published port>` |

Option A keeps Postgres off the host's public interfaces and gives a stable DNS name. If the container is recreated, re-run the `docker network connect` command (`make db-network`).

### 8.6 Connection settings

```text
PATIENT_DATABASE_URL=postgresql+asyncpg://patient_svc:${PATIENT_DB_PW}@nephro-pg:5432/patient_db
PATIENT_TEST_DATABASE_URL=postgresql+asyncpg://patient_svc:${PATIENT_DB_PW}@nephro-pg:5432/patient_db_test
```

Engine creation (`app/core/db.py`):

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,            # 5
    max_overflow=settings.db_max_overflow,      # 5
    pool_timeout=settings.db_pool_timeout_s,    # 5 s waiting for a free connection
    pool_recycle=1800,                          # recycle after 30 min
    pool_pre_ping=True,                         # survive a Postgres restart
    connect_args={
        "server_settings": {
            "application_name": "patient-svc",
            "timezone": "UTC",
            "statement_timeout": str(settings.db_statement_timeout_ms),  # 3000
        },
        "command_timeout": settings.db_statement_timeout_ms / 1000 + 1,
    },
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
```

Because Postgres is outside compose, `depends_on: service_healthy` cannot be used. The entrypoint therefore **waits for the database** itself (`app/scripts/wait_for_db.py`: up to `DB_CONNECT_RETRIES` attempts, 1 s apart, `SELECT 1`), then runs migrations, then starts uvicorn.

### 8.7 Verifying isolation

```bash
# patient_svc can use its own database (forces password auth over TCP)
docker exec -it <pg> psql "postgresql://patient_svc:${PATIENT_DB_PW}@localhost/patient_db" -c 'select current_user, current_database();'

# ...and is refused everywhere else (expected: FATAL: permission denied for database "lab_db")
docker exec -it <pg> psql "postgresql://patient_svc:${PATIENT_DB_PW}@localhost/lab_db" -c 'select 1;'
```

The second command must fail. It is also an automated check in the API test suite (§25.3).

### 8.8 Backup, restore and reset (development)

```bash
# Backup (custom format)
docker exec <pg> pg_dump -U postgres -d patient_db -Fc > backups/patient_db_$(date +%F).dump

# Restore into an empty patient_db
docker exec -i <pg> pg_restore -U postgres -d patient_db --no-owner --role=patient_svc < backups/patient_db_2026-11-11.dump

# Full reset (PG 13+: WITH (FORCE) disconnects sessions), then re-provision and migrate
docker exec <pg> psql -U postgres -c 'DROP DATABASE IF EXISTS patient_db WITH (FORCE);'
make db-provision-patient && make migrate-patient && make seed-patient
```

---

## 9. Physical data model

### 9.1 Entity-relationship diagram

```mermaid
erDiagram
    PATIENTS ||--o{ PATIENT_CONDITIONS : has
    PATIENTS ||--o{ MEDICATIONS : takes
    PATIENTS ||--o{ ALLERGIES : has
    PATIENTS ||--o{ ENCOUNTERS : visits
    ENCOUNTERS ||--o| ENCOUNTER_VITALS : records
    ENCOUNTERS ||--o{ ENCOUNTER_DIAGNOSES : lists
    ENCOUNTERS ||--o{ PATIENT_CONDITIONS : "source of"
    PATIENT_CONDITIONS ||--o{ ENCOUNTER_DIAGNOSES : "linked from"
    PATIENTS ||--o{ AUDIT_EVENTS : "subject of"

    PATIENTS {
        uuid id PK
        text mrn UK "PT-000101, from sequence"
        text first_name
        text last_name
        text search_name "generated, lower(first last)"
        date date_of_birth
        text sex "M F O"
        text phone
        text email
        text address
        text past_medical_history
        text family_history
        text social_history
        text allergy_status "unknown nka has_allergies"
        text established_ckd_stage "G1 G2 G3a G3b G4 G5 or null"
        int version
        timestamptz created_at
        timestamptz updated_at
        uuid created_by
        uuid updated_by
        timestamptz deleted_at
    }
    PATIENT_CONDITIONS {
        uuid id PK
        uuid patient_id FK
        text icd10_code
        text description
        text category "nephrology comorbidity"
        bool is_primary
        text status "active resolved"
        date onset_date
        date resolved_date
        uuid source_encounter_id FK
        timestamptz deleted_at
    }
    MEDICATIONS {
        uuid id PK
        uuid patient_id FK
        text name
        text dose
        text route "oral sc iv topical inhaled other"
        text frequency
        date start_date
        date end_date
        text status "active discontinued"
        timestamptz deleted_at
    }
    ALLERGIES {
        uuid id PK
        uuid patient_id FK
        text allergen
        text reaction
        text severity "mild moderate severe"
        timestamptz deleted_at
    }
    ENCOUNTERS {
        uuid id PK
        uuid patient_id FK
        timestamptz encounter_date
        text encounter_type "new follow_up emergency"
        uuid clinician_id "JWT sub"
        text clinician_name "JWT name snapshot"
        text chief_complaint
        text_array symptoms
        text examination_notes
        text assessment
        text plan
        date follow_up_date
        text status "draft final"
        int version
        timestamptz finalized_at
        uuid finalized_by
        timestamptz deleted_at "drafts only"
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
        smallint seq
        text icd10_code
        text description
        bool add_to_problem_list
        uuid condition_id FK
    }
    AUDIT_EVENTS {
        bigint id PK
        uuid actor_id
        uuid patient_id
        text action
        text resource
        uuid resource_id
        timestamptz at
        text request_id
        jsonb details
    }
```

### 9.2 Baseline migration DDL (`alembic/versions/0001_baseline.py`)

The migration executes this SQL. Tables are created in dependency order: patients → encounters → patient_conditions → children → audit.

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- shared trigger functions ----------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ---------- MRN sequence ----------
CREATE SEQUENCE patient_mrn_seq START WITH 101 INCREMENT BY 1 NO CYCLE;

-- ---------- patients ----------
CREATE TABLE patients (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mrn                    text NOT NULL DEFAULT ('PT-' || lpad(nextval('patient_mrn_seq')::text, 6, '0')),
  first_name             text NOT NULL,
  last_name              text NOT NULL,
  search_name            text GENERATED ALWAYS AS (lower(first_name || ' ' || last_name)) STORED,
  date_of_birth          date NOT NULL,
  sex                    text NOT NULL,
  phone                  text,
  email                  text,
  address                text,
  past_medical_history   text,
  family_history         text,
  social_history         text,
  allergy_status         text NOT NULL DEFAULT 'unknown',
  established_ckd_stage  text,
  version                integer NOT NULL DEFAULT 1,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  created_by             uuid,
  updated_by             uuid,
  deleted_at             timestamptz,

  CONSTRAINT patients_mrn_format     CHECK (mrn ~ '^PT-[0-9]{6,}$'),
  CONSTRAINT patients_first_len      CHECK (char_length(btrim(first_name)) BETWEEN 1 AND 60),
  CONSTRAINT patients_last_len       CHECK (char_length(btrim(last_name))  BETWEEN 1 AND 60),
  CONSTRAINT patients_dob_floor      CHECK (date_of_birth >= DATE '1900-01-01'),
  CONSTRAINT patients_sex            CHECK (sex IN ('M','F','O')),
  CONSTRAINT patients_phone          CHECK (phone IS NULL OR phone ~ '^[+0-9 ()-]{7,20}$'),
  CONSTRAINT patients_email_len      CHECK (email IS NULL OR char_length(email) <= 254),
  CONSTRAINT patients_address_len    CHECK (address IS NULL OR char_length(address) <= 300),
  CONSTRAINT patients_pmh_len        CHECK (past_medical_history IS NULL OR char_length(past_medical_history) <= 4000),
  CONSTRAINT patients_fh_len         CHECK (family_history IS NULL OR char_length(family_history) <= 4000),
  CONSTRAINT patients_sh_len         CHECK (social_history IS NULL OR char_length(social_history) <= 4000),
  CONSTRAINT patients_allergy_status CHECK (allergy_status IN ('unknown','nka','has_allergies')),
  CONSTRAINT patients_ckd_stage      CHECK (established_ckd_stage IS NULL
                                            OR established_ckd_stage IN ('G1','G2','G3a','G3b','G4','G5')),
  CONSTRAINT patients_version        CHECK (version >= 1)
);
ALTER SEQUENCE patient_mrn_seq OWNED BY patients.mrn;

CREATE UNIQUE INDEX patients_mrn_uq        ON patients (mrn text_pattern_ops);
CREATE INDEX patients_search_trgm          ON patients USING gin (search_name gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX patients_name_sort            ON patients (lower(last_name), lower(first_name)) WHERE deleted_at IS NULL;
CREATE INDEX patients_dob                  ON patients (date_of_birth) WHERE deleted_at IS NULL;
CREATE INDEX patients_stage                ON patients (established_ckd_stage) WHERE deleted_at IS NULL;
CREATE TRIGGER patients_updated_at BEFORE UPDATE ON patients FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- encounters ----------
CREATE TABLE encounters (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id         uuid NOT NULL REFERENCES patients(id),
  encounter_date     timestamptz NOT NULL,
  encounter_type     text NOT NULL DEFAULT 'follow_up',
  clinician_id       uuid NOT NULL,
  clinician_name     text NOT NULL,
  chief_complaint    text,
  symptoms           text[] NOT NULL DEFAULT '{}',
  examination_notes  text,
  assessment         text,
  plan               text,
  follow_up_date     date,
  status             text NOT NULL DEFAULT 'draft',
  version            integer NOT NULL DEFAULT 1,
  finalized_at       timestamptz,
  finalized_by       uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  created_by         uuid NOT NULL,
  updated_by         uuid,
  deleted_at         timestamptz,

  CONSTRAINT encounters_type         CHECK (encounter_type IN ('new','follow_up','emergency')),
  CONSTRAINT encounters_status       CHECK (status IN ('draft','final')),
  CONSTRAINT encounters_cc_len       CHECK (chief_complaint IS NULL OR char_length(chief_complaint) <= 200),
  CONSTRAINT encounters_exam_len     CHECK (examination_notes IS NULL OR char_length(examination_notes) <= 4000),
  CONSTRAINT encounters_assess_len   CHECK (assessment IS NULL OR char_length(assessment) <= 4000),
  CONSTRAINT encounters_plan_len     CHECK (plan IS NULL OR char_length(plan) <= 4000),
  CONSTRAINT encounters_symptoms_n   CHECK (cardinality(symptoms) <= 30),
  CONSTRAINT encounters_final_stamp  CHECK ((status = 'final') = (finalized_at IS NOT NULL)),
  CONSTRAINT encounters_final_fields CHECK (status <> 'final' OR (
        coalesce(btrim(chief_complaint), '') <> ''
    AND coalesce(btrim(assessment), '')      <> ''
    AND coalesce(btrim(plan), '')            <> '')),
  CONSTRAINT encounters_delete_draft CHECK (deleted_at IS NULL OR status = 'draft'),
  CONSTRAINT encounters_version      CHECK (version >= 1)
);
CREATE INDEX encounters_patient_date    ON encounters (patient_id, encounter_date DESC) WHERE deleted_at IS NULL;
CREATE INDEX encounters_patient_final   ON encounters (patient_id, encounter_date DESC) WHERE status = 'final' AND deleted_at IS NULL;
CREATE INDEX encounters_status_date     ON encounters (status, encounter_date DESC) WHERE deleted_at IS NULL;
CREATE INDEX encounters_followup        ON encounters (follow_up_date) WHERE status = 'final' AND deleted_at IS NULL;
CREATE TRIGGER encounters_updated_at BEFORE UPDATE ON encounters FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- patient_conditions (problem list) ----------
CREATE TABLE patient_conditions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id           uuid NOT NULL REFERENCES patients(id),
  icd10_code           text,
  description          text NOT NULL,
  category             text NOT NULL,
  is_primary           boolean NOT NULL DEFAULT false,
  status               text NOT NULL DEFAULT 'active',
  onset_date           date,
  resolved_date        date,
  source_encounter_id  uuid REFERENCES encounters(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  created_by           uuid,
  updated_by           uuid,
  deleted_at           timestamptz,

  CONSTRAINT conditions_icd10      CHECK (icd10_code IS NULL OR icd10_code ~ '^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$'),
  CONSTRAINT conditions_desc_len   CHECK (char_length(btrim(description)) BETWEEN 1 AND 160),
  CONSTRAINT conditions_category   CHECK (category IN ('nephrology','comorbidity')),
  CONSTRAINT conditions_status     CHECK (status IN ('active','resolved')),
  CONSTRAINT conditions_primary    CHECK (NOT is_primary OR status = 'active'),
  CONSTRAINT conditions_resolved   CHECK ((status = 'resolved') = (resolved_date IS NOT NULL)),
  CONSTRAINT conditions_dates      CHECK (resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date)
);
-- At most one active primary diagnosis per patient (HLD v2 §5.3)
CREATE UNIQUE INDEX conditions_one_primary ON patient_conditions (patient_id)
  WHERE is_primary AND status = 'active' AND deleted_at IS NULL;
CREATE INDEX conditions_patient     ON patient_conditions (patient_id, status) WHERE deleted_at IS NULL;
CREATE INDEX conditions_patient_icd ON patient_conditions (patient_id, icd10_code) WHERE deleted_at IS NULL;
CREATE TRIGGER conditions_updated_at BEFORE UPDATE ON patient_conditions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- encounter_vitals (1:1) ----------
CREATE TABLE encounter_vitals (
  encounter_id   uuid PRIMARY KEY REFERENCES encounters(id),
  systolic_bp    integer,
  diastolic_bp   integer,
  heart_rate     integer,
  temperature_c  numeric(4,1),
  weight_kg      numeric(5,1),
  CONSTRAINT vitals_sys    CHECK (systolic_bp   IS NULL OR systolic_bp   BETWEEN 50 AND 300),
  CONSTRAINT vitals_dia    CHECK (diastolic_bp  IS NULL OR diastolic_bp  BETWEEN 20 AND 200),
  CONSTRAINT vitals_hr     CHECK (heart_rate    IS NULL OR heart_rate    BETWEEN 20 AND 300),
  CONSTRAINT vitals_temp   CHECK (temperature_c IS NULL OR temperature_c BETWEEN 30 AND 45),
  CONSTRAINT vitals_wt     CHECK (weight_kg     IS NULL OR weight_kg     BETWEEN 1 AND 500),
  CONSTRAINT vitals_bp     CHECK (systolic_bp IS NULL OR diastolic_bp IS NULL OR systolic_bp > diastolic_bp),
  CONSTRAINT vitals_any    CHECK (num_nonnulls(systolic_bp, diastolic_bp, heart_rate, temperature_c, weight_kg) >= 1)
);

-- ---------- encounter_diagnoses ----------
CREATE TABLE encounter_diagnoses (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encounter_id         uuid NOT NULL REFERENCES encounters(id),
  seq                  smallint NOT NULL,
  icd10_code           text,
  description          text NOT NULL,
  add_to_problem_list  boolean NOT NULL DEFAULT false,
  condition_id         uuid REFERENCES patient_conditions(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT dx_icd10    CHECK (icd10_code IS NULL OR icd10_code ~ '^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$'),
  CONSTRAINT dx_desc_len CHECK (char_length(btrim(description)) BETWEEN 1 AND 160),
  CONSTRAINT dx_seq_uq   UNIQUE (encounter_id, seq)
);
CREATE INDEX dx_condition ON encounter_diagnoses (condition_id) WHERE condition_id IS NOT NULL;

-- ---------- medications ----------
CREATE TABLE medications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES patients(id),
  name        text NOT NULL,
  dose        text NOT NULL,
  route       text NOT NULL DEFAULT 'oral',
  frequency   text NOT NULL,
  start_date  date,
  end_date    date,
  status      text NOT NULL DEFAULT 'active',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  updated_by  uuid,
  deleted_at  timestamptz,
  CONSTRAINT meds_name_len     CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
  CONSTRAINT meds_dose_len     CHECK (char_length(btrim(dose)) BETWEEN 1 AND 40),
  CONSTRAINT meds_freq_len     CHECK (char_length(btrim(frequency)) BETWEEN 1 AND 80),
  CONSTRAINT meds_route        CHECK (route IN ('oral','sc','iv','topical','inhaled','other')),
  CONSTRAINT meds_status       CHECK (status IN ('active','discontinued')),
  CONSTRAINT meds_dates        CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
  CONSTRAINT meds_disc_has_end CHECK (status <> 'discontinued' OR end_date IS NOT NULL)
);
CREATE INDEX meds_patient        ON medications (patient_id) WHERE deleted_at IS NULL;
CREATE INDEX meds_patient_active ON medications (patient_id) WHERE status = 'active' AND deleted_at IS NULL;
CREATE TRIGGER meds_updated_at BEFORE UPDATE ON medications FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- allergies ----------
CREATE TABLE allergies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES patients(id),
  allergen    text NOT NULL,
  reaction    text,
  severity    text NOT NULL DEFAULT 'moderate',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  deleted_at  timestamptz,
  deleted_by  uuid,
  CONSTRAINT allergies_allergen_len CHECK (char_length(btrim(allergen)) BETWEEN 1 AND 80),
  CONSTRAINT allergies_reaction_len CHECK (reaction IS NULL OR char_length(reaction) <= 200),
  CONSTRAINT allergies_severity     CHECK (severity IN ('mild','moderate','severe'))
);
CREATE UNIQUE INDEX allergies_one_per_allergen ON allergies (patient_id, lower(btrim(allergen))) WHERE deleted_at IS NULL;
CREATE TRIGGER allergies_updated_at BEFORE UPDATE ON allergies FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- audit_events (append-only) ----------
CREATE TABLE audit_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id     uuid NOT NULL,
  patient_id   uuid,
  action       text NOT NULL,
  resource     text NOT NULL,
  resource_id  uuid,
  at           timestamptz NOT NULL DEFAULT now(),
  request_id   text,
  details      jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_patient_at ON audit_events (patient_id, at DESC);
CREATE INDEX audit_actor_at   ON audit_events (actor_id, at DESC);

-- ---------- immutability guards ----------
CREATE OR REPLACE FUNCTION encounters_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'encounters are never hard-deleted' USING ERRCODE = 'P0001', HINT = 'NO_HARD_DELETE';
  END IF;
  IF OLD.status = 'final' THEN
    RAISE EXCEPTION 'encounter % is final and immutable', OLD.id USING ERRCODE = 'P0001', HINT = 'ENCOUNTER_FINAL';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER encounters_guard BEFORE UPDATE OR DELETE ON encounters
  FOR EACH ROW EXECUTE FUNCTION encounters_guard();

CREATE OR REPLACE FUNCTION encounter_children_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
  SELECT status INTO s FROM encounters
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.encounter_id ELSE NEW.encounter_id END;
  IF s = 'final' THEN
    RAISE EXCEPTION 'children of a final encounter are immutable' USING ERRCODE = 'P0001', HINT = 'ENCOUNTER_FINAL';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vitals_guard BEFORE INSERT OR UPDATE OR DELETE ON encounter_vitals
  FOR EACH ROW EXECUTE FUNCTION encounter_children_guard();
CREATE TRIGGER dx_guard BEFORE INSERT OR UPDATE OR DELETE ON encounter_diagnoses
  FOR EACH ROW EXECUTE FUNCTION encounter_children_guard();

CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'P0001', HINT = 'AUDIT_APPEND_ONLY';
END $$;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();

CREATE OR REPLACE FUNCTION no_hard_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows are soft-deleted only', TG_TABLE_NAME USING ERRCODE = 'P0001', HINT = 'NO_HARD_DELETE';
END $$;
CREATE TRIGGER patients_no_delete   BEFORE DELETE ON patients           FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
CREATE TRIGGER conditions_no_delete BEFORE DELETE ON patient_conditions FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
CREATE TRIGGER meds_no_delete       BEFORE DELETE ON medications        FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
CREATE TRIGGER allergies_no_delete  BEFORE DELETE ON allergies          FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
```

### 9.3 Notes on the schema

| Item | Detail |
|---|---|
| `search_name` | Generated stored column, `lower(first last)`. Both `lower` and `||` on text are immutable, so it is allowed. Token search (§15.1) makes "Kulkarni Ramesh" match as well as "Ramesh Kulkarni" |
| MRN uniqueness | One unique btree index with `text_pattern_ops` gives both uniqueness and `LIKE 'PT-0001%'` prefix scans |
| DOB "not in the future" | Enforced in the service using `CLINIC_TZ`, not in a CHECK. A CHECK using `current_date` is evaluated only at write time and in the server time zone, so it would mislead. The DB keeps a floor of 1900-01-01 |
| Vitals row | Present only if at least one value is recorded (`vitals_any`). "No vitals" is the absence of the row, which is what the `ENCOUNTER_NO_VITALS` gap rule tests |
| Vitals units | BP mmHg, HR bpm, temperature °C (1 decimal), weight kg (1 decimal). Incoming values are rounded half-up to 1 decimal, not rejected |
| Final-encounter invariant | Three layers: the service refuses (409), CHECK constraints refuse incomplete finals, and the trigger refuses any change to a final row or its children |
| Finalize ordering | Because children of a final encounter are frozen by trigger, the finalize transaction writes `encounter_diagnoses.condition_id` **before** it flips `status` to `final` (§13.5) |
| Draft children | Vitals and diagnoses of a **draft** may be replaced (deleted and re-inserted). They are working copy, not a record. Encounters themselves are never hard-deleted |
| Soft delete | `patients`, `patient_conditions`, `medications`, `allergies` cannot be hard-deleted (trigger). `TRUNCATE` (tests only) does not fire row triggers |
| `audit_events` | `bigint` identity (append-heavy, ordered). Append-only by trigger. `patient_id` has no FK so audit rows survive any future archival of patients |
| Allergy uniqueness | One active row per allergen per patient (case-insensitive). A duplicate returns `409 DUPLICATE_ALLERGY` |
| `route` codes | Stored as codes (`oral`, `sc`, `iv`, `topical`, `inhaled`, `other`); the UI maps them to labels ("Oral", "SC", …) |
| Active medication with a past end date | Allowed on purpose. It is a real data-quality state that the `ACTIVE_MED_PAST_END_DATE` rule must be able to detect (seed patient Kavita Joshi) |

### 9.4 Enumerations

| Column | Values | UI label |
|---|---|---|
| `patients.sex` | `M`, `F`, `O` | Male, Female, Other |
| `patients.allergy_status` | `unknown`, `nka`, `has_allergies` | Allergy status unknown, No known allergies, Allergies: … |
| `patients.established_ckd_stage` | `G1`, `G2`, `G3a`, `G3b`, `G4`, `G5`, `NULL` | Not set when null |
| `patient_conditions.category` | `nephrology`, `comorbidity` | Nephrology diagnoses, Comorbidities |
| `patient_conditions.status` | `active`, `resolved` | Active, Resolved |
| `medications.status` | `active`, `discontinued` | Active, Discontinued {date} |
| `allergies.severity` | `mild`, `moderate`, `severe` | Mild, Moderate, Severe |
| `encounters.encounter_type` | `new`, `follow_up`, `emergency` | New visit, Follow-up, Emergency |
| `encounters.status` | `draft`, `final` | Draft, Final |

---

## 10. ORM mapping

SQLAlchemy 2.x typed declarative models in `app/models/`. The DDL in §9.2 is the source of truth (it is what the migration runs); the models mirror it and are never used to generate migrations automatically for constraints and triggers.

```python
# app/models/patient.py
class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    mrn: Mapped[str] = mapped_column(server_default=text("'PT-' || lpad(nextval('patient_mrn_seq')::text, 6, '0')"))
    first_name: Mapped[str]
    last_name: Mapped[str]
    search_name: Mapped[str] = mapped_column(Computed("lower(first_name || ' ' || last_name)", persisted=True))
    date_of_birth: Mapped[date]
    sex: Mapped[str]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    address: Mapped[str | None]
    past_medical_history: Mapped[str | None]
    family_history: Mapped[str | None]
    social_history: Mapped[str | None]
    allergy_status: Mapped[str] = mapped_column(server_default="unknown")
    established_ckd_stage: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]


# app/models/encounter.py
class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    encounter_date: Mapped[datetime]
    encounter_type: Mapped[str]
    clinician_id: Mapped[uuid.UUID]
    clinician_name: Mapped[str]
    chief_complaint: Mapped[str | None]
    symptoms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    examination_notes: Mapped[str | None]
    assessment: Mapped[str | None]
    plan: Mapped[str | None]
    follow_up_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="draft")
    version: Mapped[int] = mapped_column(server_default="1")
    finalized_at: Mapped[datetime | None]
    finalized_by: Mapped[uuid.UUID | None]
    created_by: Mapped[uuid.UUID]
    updated_by: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    vitals: Mapped["EncounterVitals | None"] = relationship(lazy="raise", uselist=False)
    diagnoses: Mapped[list["EncounterDiagnosis"]] = relationship(lazy="raise", order_by="EncounterDiagnosis.seq")
```

Rules for ORM use:
- Relationships are `lazy="raise"`. Every load is explicit (`selectinload`), so no hidden N+1 query can appear in an async handler.
- SQLAlchemy's `version_id_col` is **not** used: it compares against the version the ORM loaded, while this API must compare against the version the **client** sent. Version checks are explicit `UPDATE … WHERE version = :v` statements (§16.2).
- List, search, bulk and dashboard queries use SQLAlchemy Core (not ORM entities) and return Pydantic models directly.

---

## 11. API contracts (public)

### 11.1 Conventions

| Item | Rule |
|---|---|
| Base path | Service paths below; the gateway serves them under `/api` (prefix stripped) |
| Auth | `Authorization: Bearer <access JWT>` on every route; role `clinician` |
| Content | `application/json; charset=utf-8`; unknown request fields are rejected (`extra="forbid"`) |
| IDs | UUID strings; a malformed id returns `422 VALIDATION_ERROR` |
| Dates | `date` = `YYYY-MM-DD`; `datetime` = ISO-8601 with offset; responses in UTC (`Z`) |
| Strings | Trimmed server-side; empty string after trimming is stored as `NULL` for optional fields |
| Lists | `{items, page, size, total}`; `page` ≥ 1, `size` 1–100 (default 20) |
| Errors | HLD v2 envelope `{"error": {code, message, details, request_id}}` (§18) |
| Versioned writes | `PATCH /patients/{id}` and `PATCH .../encounters/{eid}` require `version` in the body |
| Created resources | `201` with `Location` header |

### 11.2 `GET /patients` — list and search

**Query parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | string ≤ 100 | — | Name tokens or MRN (§15.1) |
| `sex` | `M` \| `F` \| `O` | — | |
| `stage` | `G1`…`G5`, `G3a`, `G3b`, `none` | — | Established stage; `none` = not set |
| `ids` | comma-separated UUIDs, ≤ 500 | — | From `GET /insights/worklist` (Needs attention filter) |
| `sort` | `name` \| `mrn` \| `age` \| `dx` \| `visit` | `name` (or relevance when `q` is a name) | `egfr` is rejected with 422 (ADR-020) |
| `dir` | `asc` \| `desc` | `asc` (`visit` defaults to `desc`) | |
| `page`, `size` | int | 1, 20 | UI uses `size=8` |

**200 response**

```json
{
  "items": [
    {
      "id": "0b7c…",
      "mrn": "PT-000101",
      "first_name": "Ramesh",
      "last_name": "Kulkarni",
      "age": 67,
      "sex": "M",
      "phone": "+91 98…",
      "primary_diagnosis": {"icd10_code": "E11.21", "description": "Type 2 diabetes mellitus with diabetic nephropathy"},
      "established_ckd_stage": "G3b",
      "allergy_status": "has_allergies",
      "last_visit": "2026-10-21T04:45:00Z"
    }
  ],
  "page": 1, "size": 8, "total": 10
}
```

`primary_diagnosis` is `null` when none is recorded (UI: "None recorded"). `last_visit` is the latest **final** encounter (`null` → "No visits"). Not audited per row (lists show minimal data); the detail view is audited.

### 11.3 Patient resource

**`POST /patients`** — register

```json
{
  "first_name": "Ramesh", "last_name": "Kulkarni",
  "date_of_birth": "1959-04-17", "sex": "M",
  "phone": "+91 9876543210", "email": "ramesh.k@example.test", "address": null,
  "past_medical_history": "Type 2 diabetes for 18 years…",
  "family_history": "Father had end-stage kidney disease.",
  "social_history": "Retired bank manager. Non-smoker.",
  "allergy_status": "unknown"
}
```

| Field | Rule (message shown by the prototype) |
|---|---|
| `first_name`, `last_name` | Required, 1–60 chars ("First name is required.") |
| `date_of_birth` | Required; not after today in `CLINIC_TZ` ("Date of birth cannot be in the future."); age ≤ 120 ("Check the date of birth. Age would exceed 120.") |
| `sex` | `M`, `F` or `O` |
| `phone` | Optional; `^[+0-9 ()-]{7,20}$` ("Use digits, spaces and + only (7 to 20 characters).") |
| `email` | Optional; basic email shape, ≤ 254 ("Enter a valid email address.") |
| `address` | Optional, ≤ 300 |
| histories | Optional, ≤ 4000 each |
| `allergy_status` | `unknown` (default) or `nka`. Specific allergies are added afterwards from the chart |
| `established_ckd_stage` | Not accepted on create (set from the Conditions tab) |

`201` → the patient detail object (below), with the generated `mrn`.

**`GET /patients/{id}`** — detail (audited as `patient.view`)

```json
{
  "id": "0b7c…", "mrn": "PT-000101",
  "first_name": "Ramesh", "last_name": "Kulkarni",
  "date_of_birth": "1959-04-17", "age": 67, "sex": "M",
  "phone": "+91 98…", "email": "ramesh.kulkarni@example.test", "address": null,
  "past_medical_history": "…", "family_history": "…", "social_history": "…",
  "allergy_status": "has_allergies",
  "allergy_summary": [{"id": "…", "allergen": "Penicillin", "severity": "moderate"}],
  "established_ckd_stage": "G3b",
  "primary_diagnosis": {"id": "…", "icd10_code": "E11.21", "description": "Type 2 diabetes mellitus with diabetic nephropathy"},
  "counts": {"conditions": 4, "active_conditions": 4, "active_medications": 4, "encounters": 4},
  "last_visit": "2026-10-21T04:45:00Z",
  "next_follow_up": "2026-12-02",
  "version": 7,
  "created_at": "…", "updated_at": "…"
}
```

- `allergy_summary` feeds the header chip ("Allergies: Penicillin") without a second call.
- `counts` feed the tab badges and the Overview "At a glance" panel. `counts.encounters` includes drafts (the prototype badge does).
- `next_follow_up` = earliest `follow_up_date ≥ today` among final encounters; `null` → "Not set".

**`PATCH /patients/{id}`** — partial update, version-checked

```json
{ "version": 7, "phone": "+91 9000000000", "established_ckd_stage": "G4" }
```

| Field | Rule |
|---|---|
| `version` | Required. Mismatch → `409 VERSION_CONFLICT` ("This record was changed by someone else. Reload and try again.") |
| Demographic and history fields | Same rules as create; send `null` to clear an optional field |
| `established_ckd_stage` | One of G1…G5 or `null` |
| `allergy_status` | Only `nka` or `unknown`, and only when the patient has **no active allergies** → else `409 ALLERGIES_PRESENT`. `has_allergies` is never accepted (it is derived) |
| `mrn`, `id`, audit columns | Read-only; rejected with 422 |

`200` → updated detail (new `version`). Any change to the patients row increments `version`, including stage and allergy status changes, so the UI must send the current version for the stage dropdown as well.

**`DELETE /patients/{id}`** — soft delete. `204`. Child rows are kept; every route that takes `{id}` treats a soft-deleted patient as `404`. The patient disappears from lists, bulk exports and internal reads.

### 11.4 Response for sub-resource writes

All sub-resource mutations return the changed object and, where the patient row changed (allergy status), a `patient_version` field so the UI can keep its `version` current without a refetch.

### 11.5 Conditions (problem list)

| Method | Path | Body / query | Result |
|---|---|---|---|
| GET | `/patients/{id}/conditions` | `?status=active|resolved` (default both) | `{items:[…]}` ordered: primary first, then category, then `onset_date` desc |
| POST | `/patients/{id}/conditions` | `{icd10_code?, description, category, onset_date?, is_primary?}` | `201` condition |
| PATCH | `/patients/{id}/conditions/{cid}` | any of `{is_primary: true, status, description, icd10_code, onset_date, category}` | `200` condition (+ `primary_cleared` flag) |
| DELETE | `/patients/{id}/conditions/{cid}` | — | `204` soft delete (entered in error) |

Condition object:

```json
{
  "id": "…", "icd10_code": "N18.32", "description": "Chronic kidney disease, stage 3b",
  "category": "nephrology", "is_primary": false, "status": "active",
  "onset_date": "2023-11-10", "resolved_date": null, "source_encounter_id": null,
  "created_at": "…", "updated_at": "…"
}
```

Rules: description required 1–160 ("Description is required."); ICD-10 optional, uppercased, pattern `A00`–`Z99` with optional `.xxxx`; onset not in the future ("Onset cannot be in the future."). `is_primary: true` on create or PATCH clears any other primary in the same transaction. `is_primary: false` via PATCH is rejected (choose another primary or resolve instead). Setting `status: resolved` sets `resolved_date = today`, clears `is_primary` and returns `"primary_cleared": true` if it was primary. `status: active` (reactivate) clears `resolved_date`. Making a resolved condition primary → `409 CONDITION_NOT_ACTIVE`.

### 11.6 Medications

| Method | Path | Body / query | Result |
|---|---|---|---|
| GET | `/patients/{id}/medications` | `?status=active` (default) or `?status=all` | `{items:[…]}` active first, then `start_date` desc |
| POST | `/patients/{id}/medications` | `{name, dose, route, frequency, start_date?, end_date?}` | `201` medication |
| PATCH | `/patients/{id}/medications/{mid}` | `{action:"discontinue"}` or field edits `{dose?, frequency?, route?, end_date?}` | `200` medication |

Rules: name 1–80 ("Medication name is required."), dose 1–40 ("Dose is required."), frequency 1–80 ("Frequency is required."), route code. `start_date` defaults to today. `action: discontinue` sets `status = discontinued`, `end_date = today` (or keeps an earlier existing end date); discontinuing twice → `409 MEDICATION_ALREADY_DISCONTINUED`. Discontinued medications cannot be edited (409).

### 11.7 Allergies

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/patients/{id}/allergies` | — | `{allergy_status, items:[…]}` |
| POST | `/patients/{id}/allergies` | `{allergen, reaction?, severity}` | `201 {allergy, allergy_status:"has_allergies", patient_version}` |
| DELETE | `/patients/{id}/allergies/{aid}` | — | `200 {allergy_status, patient_version}` (soft delete; last one → `unknown`) |

"Confirm no known allergies" is `PATCH /patients/{id} {"version": n, "allergy_status": "nka"}` (§11.3), allowed only with zero active allergies.

### 11.8 Encounters (per patient)

**`GET /patients/{id}/encounters?page=&size=&status=`** — history, newest first, drafts included.

```json
{
  "items": [{
    "id": "…", "encounter_date": "2026-10-21T04:45:00Z", "encounter_type": "follow_up",
    "clinician_name": "Dr. Anita Rao", "chief_complaint": "Review of recent laboratory results",
    "assessment": "Persistent eGFR decline over two years…",
    "vitals_brief": {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74},
    "follow_up_date": "2026-12-02", "status": "final"
  }],
  "page": 1, "size": 20, "total": 4
}
```

**`POST /patients/{id}/encounters`** — create as draft or final

```json
{
  "encounter_date": "2026-11-11T10:15:00+05:30",
  "encounter_type": "follow_up",
  "chief_complaint": "Review of recent laboratory results",
  "symptoms": ["Fatigue"],
  "examination_notes": "BP 138/82. Mild pallor.",
  "assessment": "Persistent eGFR decline; UACR in the severely increased range.",
  "plan": "Discuss progression at next visit. Follow-up in 6 weeks.",
  "follow_up_date": "2026-12-23",
  "vitals": {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74, "temperature_c": 36.6, "weight_kg": 72.9},
  "diagnoses": [
    {"icd10_code": "N18.32", "description": "Chronic kidney disease, stage 3b", "add_to_problem_list": true, "category": null}
  ],
  "status": "final"
}
```

Validation (all with field-level `details`):

| Field | Rule | Message |
|---|---|---|
| `encounter_date` | Required; ≤ now + 60 s; ≥ patient DOB | "Visit date cannot be in the future." |
| `encounter_type` | `new`, `follow_up`, `emergency` | |
| `vitals.*` | Ranges in §9.2; each optional; `null` or all-empty object = no vitals | "Enter 50 to 300 mmHg." etc. |
| `vitals` BP | systolic > diastolic when both present | "Systolic must be higher than diastolic." |
| `symptoms` | ≤ 30 items, each 1–60 chars, de-duplicated case-insensitively | |
| `follow_up_date` | ≥ visit date (in `CLINIC_TZ`) | "Follow-up cannot be before the visit." |
| `diagnoses[]` | ≤ 20; each needs a description; ICD pattern; no duplicate ICD within one encounter | "Each diagnosis needs a description." |
| `status = final` | `chief_complaint`, `assessment`, `plan` non-blank | "Chief complaint is required to finalize." etc. |

`clinician_id` and `clinician_name` come from the JWT, never from the body.

`201` response:

```json
{
  "encounter": { "...": "full encounter detail, see below" },
  "problem_list_changes": {"added": 1, "reactivated": 0, "linked": 0}
}
```

The UI toast "Encounter finalized. 1 condition added to the problem list." uses `problem_list_changes.added`.

**`GET /patients/{id}/encounters/{eid}`** — detail (audited as `encounter.view`)

```json
{
  "id": "…", "patient_id": "…", "encounter_date": "…", "encounter_type": "follow_up",
  "clinician_id": "…", "clinician_name": "Dr. Anita Rao",
  "chief_complaint": "…", "symptoms": ["Fatigue"], "examination_notes": "…",
  "assessment": "…", "plan": "…", "follow_up_date": "2026-12-23",
  "vitals": {"systolic_bp": 138, "diastolic_bp": 82, "heart_rate": 74, "temperature_c": 36.6, "weight_kg": 72.9},
  "diagnoses": [{"seq": 1, "icd10_code": "N18.32", "description": "…", "add_to_problem_list": true, "condition_id": "…"}],
  "status": "final", "version": 1, "finalized_at": "…", "finalized_by": "…",
  "created_at": "…", "updated_at": "…"
}
```

**`PATCH /patients/{id}/encounters/{eid}`** — edit a draft. Body = `version` + any editable field. `vitals` and `diagnoses`, when present, **replace** the whole set. `status: "final"` in the same body finalizes in the same transaction ("Finalize encounter" pressed on an edited draft). Final encounter → `409 ENCOUNTER_FINAL` ("Final encounters cannot be edited."). Returns the same shape as POST.

**`POST /patients/{id}/encounters/{eid}/finalize`** — body `{"version": n}`. Finalizes a draft as it stands (same validation as above). Already final → `409 ENCOUNTER_FINAL`.

**`DELETE /patients/{id}/encounters/{eid}`** — soft-delete a draft. `204`. Final → `409 ENCOUNTER_FINAL` ("Final encounters cannot be deleted.").

### 11.9 Pydantic schemas (core)

```python
# app/schemas/common.py
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

ICD10 = Annotated[str, StringConstraints(pattern=r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$", to_upper=True)]
Stage = Literal["G1", "G2", "G3a", "G3b", "G4", "G5"]


# app/schemas/encounter.py
class VitalsIn(Strict):
    systolic_bp: int | None = Field(None, ge=50, le=300)
    diastolic_bp: int | None = Field(None, ge=20, le=200)
    heart_rate: int | None = Field(None, ge=20, le=300)
    temperature_c: Decimal | None = Field(None, ge=30, le=45)
    weight_kg: Decimal | None = Field(None, ge=1, le=500)

    @field_validator("temperature_c", "weight_kg")
    @classmethod
    def one_decimal(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    @model_validator(mode="after")
    def bp_order(self) -> "VitalsIn":
        if self.systolic_bp is not None and self.diastolic_bp is not None and self.systolic_bp <= self.diastolic_bp:
            raise PydanticCustomError("bp_order", "Systolic must be higher than diastolic.")
        return self

    def is_empty(self) -> bool:
        return all(v is None for v in self.model_dump().values())


class DiagnosisIn(Strict):
    icd10_code: ICD10 | None = None
    description: str = Field(min_length=1, max_length=160)
    add_to_problem_list: bool = False
    category: Literal["nephrology", "comorbidity"] | None = None   # inferred when null (§13.6)


class EncounterBase(Strict):
    encounter_date: AwareDatetime
    encounter_type: Literal["new", "follow_up", "emergency"] = "follow_up"
    chief_complaint: str | None = Field(None, max_length=200)
    symptoms: list[Annotated[str, StringConstraints(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=30)
    examination_notes: str | None = Field(None, max_length=4000)
    assessment: str | None = Field(None, max_length=4000)
    plan: str | None = Field(None, max_length=4000)
    follow_up_date: date | None = None
    vitals: VitalsIn | None = None
    diagnoses: list[DiagnosisIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def no_duplicate_icd(self) -> "EncounterBase":
        codes = [d.icd10_code for d in self.diagnoses if d.icd10_code]
        if len(codes) != len(set(codes)):
            raise PydanticCustomError("dx_duplicate", "The same ICD-10 code appears twice.")
        return self


class EncounterCreate(EncounterBase):
    status: Literal["draft", "final"] = "draft"


class EncounterPatch(Strict):
    version: int = Field(ge=1)
    encounter_date: AwareDatetime | None = None
    encounter_type: Literal["new", "follow_up", "emergency"] | None = None
    chief_complaint: str | None = None
    symptoms: list[str] | None = None
    examination_notes: str | None = None
    assessment: str | None = None
    plan: str | None = None
    follow_up_date: date | None = None
    vitals: VitalsIn | None = None
    diagnoses: list[DiagnosisIn] | None = None
    status: Literal["draft", "final"] | None = None
```

Rules that need "today", the patient's DOB or the stored row (date not in future in `CLINIC_TZ`, follow-up ≥ visit date, finalize completeness after merging a PATCH) live in `app/domain/encounter_rules.py` as pure functions, so they are unit-tested without HTTP or a database.

---

## 12. API contracts (cross-patient and internal)

### 12.1 `GET /encounters` — dashboard queries

Exactly one mode per call; both or neither → `422`.

| Mode | Query | Returns | Order |
|---|---|---|---|
| Drafts | `status=draft&limit=10` | Draft encounters of non-deleted patients | `encounter_date` desc |
| Follow-ups | `upcoming_followups=true&limit=5` | Per patient, the follow-up of their **most recent final encounter**, when that date is today or later | `follow_up_date` asc |

```json
{
  "items": [{
    "encounter_id": "…", "patient_id": "…", "mrn": "PT-000101", "patient_name": "Ramesh Kulkarni",
    "encounter_date": "…", "encounter_type": "follow_up",
    "chief_complaint": "Dietitian referral discussion",
    "plan": null, "follow_up_date": null
  }],
  "total": 1
}
```

`total` is the full count in that mode (the draft KPI on the dashboard reads it). Using only the latest final encounter per patient for follow-ups avoids showing a stale date that a later visit replaced.

```sql
-- follow-ups
SELECT * FROM (
  SELECT DISTINCT ON (e.patient_id)
         e.id AS encounter_id, e.patient_id, p.mrn, p.first_name || ' ' || p.last_name AS patient_name,
         e.encounter_date, e.encounter_type, e.chief_complaint, e.plan, e.follow_up_date
  FROM encounters e
  JOIN patients p ON p.id = e.patient_id AND p.deleted_at IS NULL
  WHERE e.status = 'final' AND e.deleted_at IS NULL
  ORDER BY e.patient_id, e.encounter_date DESC
) latest
WHERE latest.follow_up_date >= :today
ORDER BY latest.follow_up_date, latest.patient_name
LIMIT :limit;
```

### 12.2 `GET /internal/patients/{id}/basic`

Caller: lab-svc, once per lab report. Not audited (no clinical content).

```json
{"id": "…", "sex": "M", "date_of_birth": "1959-04-17"}
```

`404 NOT_FOUND` when missing or soft-deleted. One primary-key lookup; target p95 ≤ 20 ms.

### 12.3 `GET /internal/patients/{id}/chart?encounters=2`

Caller: ai-svc summary pipeline (baseline context). Audited as `chart.read_internal` with the forwarded user as actor. `encounters` 1–5 (default 2) controls how many recent encounters carry full notes.

```json
{
  "patient": {
    "id": "…", "age": 67, "sex": "M", "date_of_birth": "1959-04-17",
    "allergy_status": "has_allergies", "established_ckd_stage": "G3b",
    "past_medical_history": "…", "family_history": "…", "social_history": "…"
  },
  "conditions": [{"id": "…", "icd10_code": "E11.21", "description": "…", "category": "nephrology", "is_primary": true, "status": "active", "onset_date": "…"}],
  "medications": [{"id": "…", "name": "Losartan", "dose": "50 mg", "route": "oral", "frequency": "Once daily", "start_date": "…", "end_date": null, "status": "active"}],
  "allergies": [{"id": "…", "allergen": "Penicillin", "reaction": "Rash", "severity": "moderate"}],
  "recent_encounters": [{
    "id": "…", "encounter_date": "…", "encounter_type": "follow_up", "status": "final",
    "chief_complaint": "…", "symptoms": ["…"], "examination_notes": "…", "assessment": "…", "plan": "…",
    "follow_up_date": "…", "vitals": {"…": 0}, "diagnoses": [{"icd10_code": "…", "description": "…"}]
  }],
  "encounter_index": [{"id": "…", "encounter_date": "…", "status": "final", "has_vitals": true, "has_assessment_and_plan": true}],
  "counts": {"encounters": 4, "final_encounters": 3, "drafts": 1}
}
```

- **No name, MRN, phone, email or address** (P-12).
- `encounter_index` covers **all** encounters, so the gap rules (`ENCOUNTER_NO_VITALS`, `ENCOUNTER_NO_ASSESSMENT`) see every final encounter, not only the recent ones.
- Medications include discontinued ones with `status`, because the AI context lists active ones and the rules need end dates.

### 12.4 Tool endpoints (ai-svc tool calling, HLD v2 §10.4)

All are read-only and size-capped. `patient_id` is in the path and bound by ai-svc from the request, never chosen by the model.

| Tool | Endpoint | Caps |
|---|---|---|
| `get_conditions(status?)` | `GET /internal/patients/{id}/conditions?status=` | ≤ 50 rows |
| `get_medications_and_allergies()` | `GET /internal/patients/{id}/medications-allergies` | ≤ 50 + 50 rows |
| `get_recent_encounters(limit ≤ 5, include_notes)` | `GET /internal/patients/{id}/encounters?limit=&include_notes=` | Notes truncated to 1,500 chars each with `"truncated": true` |

Each response carries `"truncated": false|true` at the top level.

### 12.5 `GET /internal/patients/charts?cursor=&limit=200`

Caller: ai-svc insights (worklist, dashboard). Keyset pagination by `id`, `limit` ≤ 200. Returns only the fields the rules and the dashboard need. Names and MRN are included because dashboard rows show them; these responses are never put into any LLM context (HLD v2 §10.12).

```json
{
  "items": [{
    "id": "…", "mrn": "PT-000110", "first_name": "Kavita", "last_name": "Joshi",
    "date_of_birth": "1992-04-20", "age": 34, "sex": "F",
    "allergy_status": "nka", "established_ckd_stage": null,
    "has_active_primary": true,
    "medication_count": 3,
    "active_meds_past_end": [{"id": "…", "name": "Hydroxychloroquine", "end_date": "2026-10-02"}],
    "final_encounters": [{"id": "…", "encounter_date": "…", "has_vitals": true, "has_assessment_and_plan": true}]
  }],
  "next_cursor": "c3a1…"
}
```

```sql
SELECT p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex,
       p.allergy_status, p.established_ckd_stage,
       EXISTS (SELECT 1 FROM patient_conditions c
               WHERE c.patient_id = p.id AND c.is_primary AND c.status = 'active' AND c.deleted_at IS NULL) AS has_active_primary,
       (SELECT count(*) FROM medications m WHERE m.patient_id = p.id AND m.deleted_at IS NULL) AS medication_count,
       COALESCE((SELECT json_agg(json_build_object('id', m.id, 'name', m.name, 'end_date', m.end_date))
                 FROM medications m
                 WHERE m.patient_id = p.id AND m.status = 'active' AND m.end_date < :today AND m.deleted_at IS NULL), '[]') AS active_meds_past_end,
       COALESCE((SELECT json_agg(json_build_object(
                          'id', e.id, 'encounter_date', e.encounter_date,
                          'has_vitals', v.encounter_id IS NOT NULL,
                          'has_assessment_and_plan', coalesce(btrim(e.assessment), '') <> '' AND coalesce(btrim(e.plan), '') <> '')
                        ORDER BY e.encounter_date DESC)
                 FROM encounters e LEFT JOIN encounter_vitals v ON v.encounter_id = e.id
                 WHERE e.patient_id = p.id AND e.status = 'final' AND e.deleted_at IS NULL), '[]') AS final_encounters
FROM patients p
WHERE p.deleted_at IS NULL
  AND (CAST(:cursor AS uuid) IS NULL OR p.id > CAST(:cursor AS uuid))
ORDER BY p.id
LIMIT :limit + 1;   -- the extra row tells us whether next_cursor is needed
```

Not audited per patient (system-wide aggregate); one `chart.bulk_export` audit row per page with the actor and the count.

---

## 13. Service-layer algorithms

Services own transactions. Repositories take an `AsyncSession` and never commit. Every write method follows the same skeleton:

```python
async def <write>(...):
    async with session.begin():                    # one ACID transaction
        patient = await patients_repo.lock_active(pid)   # SELECT … FOR UPDATE, 404 if missing/deleted
        domain.validate(...)                       # pure rules (today in CLINIC_TZ)
        ...                                        # repository writes
        await audit.record(...)                    # same transaction
    return ...
```

### 13.1 Register a patient

1. Validate (Pydantic + `domain.patient_rules.validate_dob(dob, today)`).
2. `INSERT INTO patients (...) RETURNING id, mrn, version` (MRN from the sequence default).
3. On `23505` against `patients_mrn_uq` (only possible if someone inserted explicit MRNs past the sequence): advance the sequence with `setval` to the max and retry once.
4. Audit `patient.create` with `details.fields` = names of non-null fields.

### 13.2 Update a patient (optimistic lock)

```python
async def update_patient(pid, patch: PatientPatch, user):
    async with session.begin():
        changes = patch.model_dump(exclude_unset=True, exclude={"version"})
        if "allergy_status" in changes:
            await allergy_rules.assert_can_set_status(pid, changes["allergy_status"])   # 409 ALLERGIES_PRESENT
        row = await session.execute(
            update(Patient)
            .where(Patient.id == pid, Patient.version == patch.version, Patient.deleted_at.is_(None))
            .values(**changes, version=Patient.version + 1, updated_by=user.id)
            .returning(Patient.version)
        )
        new_version = row.scalar_one_or_none()
        if new_version is None:
            raise NotFound() if not await patients_repo.exists(pid) else VersionConflict()
        await audit.record(user, "patient.update", pid, details={"fields": sorted(changes)})
    return await get_patient(pid)
```

### 13.3 Problem-list operations

| Operation | Steps (inside one transaction, patient row locked) |
|---|---|
| Add condition with `is_primary` | `UPDATE patient_conditions SET is_primary=false WHERE patient_id=$1 AND is_primary` → `INSERT … is_primary=true` |
| Set primary | Load condition (404 if not this patient's); 409 if not active; clear other primaries; set this one |
| Resolve | `status='resolved', resolved_date=today, is_primary=false`; report `primary_cleared` |
| Reactivate | `status='active', resolved_date=NULL` |
| Delete | `deleted_at=now()`; if it was primary the patient now has none (the gap rule will show it) |

Clearing before setting matters: the partial unique index is checked per statement, so setting the new primary first would fail.

### 13.4 Create or edit an encounter

```python
async def create_encounter(pid, body: EncounterCreate, user) -> EncounterResult:
    async with session.begin():
        patient = await patients_repo.lock_active(pid)
        today = clock.today()                                   # CLINIC_TZ
        encounter_rules.validate_common(body, patient.date_of_birth, now=clock.now(), today=today)
        if body.status == "final":
            encounter_rules.validate_finalizable(body)          # cc, assessment, plan
        enc_id = await enc_repo.insert(pid, body, status="draft",
                                       clinician_id=user.id, clinician_name=user.name, created_by=user.id)
        await enc_repo.replace_vitals(enc_id, body.vitals)      # no row if vitals empty
        await enc_repo.replace_diagnoses(enc_id, body.diagnoses)
        changes = ProblemListChanges()
        if body.status == "final":
            changes = await finalize_in_tx(patient, enc_id, user, today)
        await audit.record(user, "encounter.finalize" if body.status == "final" else "encounter.create_draft", pid,
                           resource="encounter", resource_id=enc_id)
    return EncounterResult(encounter=await enc_repo.get_detail(enc_id), problem_list_changes=changes)
```

Editing a draft (`PATCH`):
1. Lock patient, then `SELECT … FROM encounters WHERE id=$eid AND patient_id=$pid AND deleted_at IS NULL FOR UPDATE`.
2. `status = final` → `409 ENCOUNTER_FINAL`. `version` ≠ body version → `409 VERSION_CONFLICT`.
3. Merge the patch over the stored row; validate the merged result (common rules; finalizable rules if `status: final`).
4. `UPDATE encounters SET … , version = version + 1`; replace vitals and/or diagnoses only if those keys were sent.
5. If `status: final` → `finalize_in_tx`.

### 13.5 Finalize (shared by POST, PATCH and `/finalize`)

```python
async def finalize_in_tx(patient, enc_id, user, today) -> ProblemListChanges:
    enc = await enc_repo.get_for_update(enc_id)                 # already locked by caller in PATCH flow
    encounter_rules.validate_finalizable(enc)                   # re-check on the stored state
    changes = ProblemListChanges()
    local_visit_date = to_clinic_date(enc.encounter_date)

    # 1. Link diagnoses to the problem list FIRST (children are frozen once status = final)
    for dx in await enc_repo.diagnoses(enc_id):
        if not dx.add_to_problem_list:
            continue
        cond, kind = await conditions.link_or_create(
            patient_id=patient.id, icd10=dx.icd10_code, description=dx.description,
            category=dx.category or infer_category(dx.icd10_code),
            onset=local_visit_date, source_encounter_id=enc_id, user=user)
        await enc_repo.set_diagnosis_condition(dx.id, cond.id)
        changes.count(kind)                                     # added | reactivated | linked

    # 2. Then flip the status (trigger allows it because OLD.status = 'draft')
    await enc_repo.mark_final(enc_id, finalized_by=user.id)     # status, finalized_at, version+1
    return changes
```

`link_or_create` resolution order (all scoped to the patient, non-deleted rows):

| Step | Match | Action | Counted as |
|---|---|---|---|
| 1 | ICD present and an **active** condition has the same ICD | Link to it | `linked` |
| 2 | ICD present and a **resolved** condition has the same ICD | Reactivate (`status=active`, `resolved_date=NULL`), link | `reactivated` |
| 3 | No ICD and an active condition has the same description (case-insensitive) | Link | `linked` |
| 4 | Otherwise | Insert a new active, non-primary condition with `source_encounter_id` and `onset_date` = visit date | `added` |

An encounter never sets or changes the primary diagnosis.

### 13.6 Category inference for new problem-list entries

Used only when the diagnosis row does not carry an explicit `category`.

```python
NEPHROLOGY_PREFIXES = ("N", "Q61", "M32.1", "E10.2", "E11.2", "E13.2", "I12", "I13")

def infer_category(icd10: str | None) -> Literal["nephrology", "comorbidity"]:
    if icd10 and icd10.upper().startswith(NEPHROLOGY_PREFIXES):
        return "nephrology"
    return "comorbidity"
```

The prototype used `^(N|Q61|M32)`. That classifies E11.21 (diabetic nephropathy) as a comorbidity while the seed data files it as nephrology, so the list adds the diabetic-kidney (E1x.2) and hypertensive-CKD (I12, I13) blocks and narrows M32 to M32.1x (lupus with organ involvement). The encounter form may also send `category` explicitly.

### 13.7 Allergy operations

| Operation | Steps (patient row locked) |
|---|---|
| Add | `INSERT allergies` (409 `DUPLICATE_ALLERGY` on the unique index) → `UPDATE patients SET allergy_status='has_allergies', version=version+1` (only if it was not already) |
| Remove | `UPDATE allergies SET deleted_at=now(), deleted_by=$user` → if no active allergies remain, `UPDATE patients SET allergy_status='unknown', version=version+1` |
| Confirm none | Via `PATCH /patients/{id}` with `allergy_status:'nka'`; rejected with `409 ALLERGIES_PRESENT` if any active allergy exists |

Removing the last allergy returns status to `unknown`, not `nka`: removing an entry is not the same as confirming the patient has none (matches the prototype's dialog text).

### 13.8 Discontinue a medication

`UPDATE medications SET status='discontinued', end_date = LEAST(coalesce(end_date, :today), :today) WHERE id=$mid AND patient_id=$pid AND status='active' AND deleted_at IS NULL RETURNING …`. Zero rows → 404 or `409 MEDICATION_ALREADY_DISCONTINUED`.

---

## 14. Encounter state machine and immutability

```mermaid
stateDiagram-v2
    [*] --> draft: POST status=draft
    [*] --> final: POST status=final
    draft --> draft: PATCH (version check)
    draft --> final: POST /finalize, or PATCH status=final
    draft --> deleted: DELETE (soft)
    final --> final: any edit or delete → 409 ENCOUNTER_FINAL
    deleted --> [*]
```

| From | Action | To | Guard | Error |
|---|---|---|---|---|
| — | create draft | draft | common rules | 422 |
| — | create final | final | common + finalizable | 422 |
| draft | edit | draft | version match | 409 `VERSION_CONFLICT` |
| draft | finalize | final | finalizable; version match (if PATCH/finalize body) | 422 / 409 |
| draft | delete | deleted | — | — |
| final | edit / finalize / delete | — | never allowed | 409 `ENCOUNTER_FINAL` |

Enforcement layers:

| Layer | Mechanism |
|---|---|
| Service | Status checked after `SELECT … FOR UPDATE` |
| Constraint | `encounters_final_stamp`, `encounters_final_fields`, `encounters_delete_draft` |
| Trigger | `encounters_guard` (no update of a final row, no hard delete), `encounter_children_guard` (vitals and diagnoses of a final encounter frozen) |
| Error mapping | Trigger `HINT='ENCOUNTER_FINAL'` → `409 ENCOUNTER_FINAL` (a trigger hit means a service bug and is logged at ERROR) |

Corrections to a final encounter are recorded as a **new** encounter (prototype text: "Corrections are recorded as a new encounter."). Addenda as a first-class concept are future work.

---

## 15. Search, sort and pagination

### 15.1 Parsing `q`

```python
MRN_FULL = re.compile(r"^pt-?(\d{1,9})$", re.I)
DIGITS = re.compile(r"^\d{1,9}$")

def parse_query(q: str) -> SearchSpec:
    q = " ".join(q.split())[:100]
    if m := MRN_FULL.match(q):
        return SearchSpec(kind="mrn_prefix", value=f"PT-{m.group(1)}")              # 'PT-0001' → prefix
    if DIGITS.match(q):
        return SearchSpec(kind="mrn_digits", value=q)                                 # '101' → exact padded or prefix
    tokens = [escape_like(t.lower()) for t in q.split(" ")][:5]
    return SearchSpec(kind="name", tokens=tokens)
```

| Kind | Predicate | Index |
|---|---|---|
| `mrn_prefix` | `mrn LIKE 'PT-0001%'` | `patients_mrn_uq` (text_pattern_ops) |
| `mrn_digits` | `mrn = 'PT-' || lpad(:d, 6, '0') OR mrn LIKE 'PT-' || :d || '%'` | same |
| `name` | every token: `search_name ILIKE '%' || :tok || '%'` | `patients_search_trgm` (GIN). Tokens shorter than 3 characters cannot use trigrams and fall back to a filtered scan, which is fine at clinic scale |

`escape_like` escapes `%`, `_` and `\`. For name searches with no explicit `sort`, results are ordered by `similarity(search_name, :q) DESC`, then name.

### 15.2 List query

Built with SQLAlchemy Core; optional filters are added only when present (avoids `:param IS NULL` patterns, which asyncpg cannot type-infer).

```sql
WITH filtered AS (
  SELECT p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex, p.phone,
         p.established_ckd_stage, p.allergy_status, p.search_name
  FROM patients p
  WHERE p.deleted_at IS NULL
    -- AND p.sex = :sex
    -- AND p.established_ckd_stage = :stage          (or IS NULL for stage=none)
    -- AND p.id = ANY(:ids)
    -- AND <search predicate from 15.1>
)
SELECT f.id, f.mrn, f.first_name, f.last_name, f.sex, f.phone,
       f.established_ckd_stage, f.allergy_status,
       date_part('year', age(:today, f.date_of_birth))::int AS age,
       pc.icd10_code AS primary_icd10, pc.description AS primary_description,
       lv.last_visit,
       count(*) OVER () AS total
FROM filtered f
LEFT JOIN LATERAL (
  SELECT c.icd10_code, c.description
  FROM patient_conditions c
  WHERE c.patient_id = f.id AND c.is_primary AND c.status = 'active' AND c.deleted_at IS NULL
  LIMIT 1
) pc ON true
LEFT JOIN LATERAL (
  SELECT max(e.encounter_date) AS last_visit
  FROM encounters e
  WHERE e.patient_id = f.id AND e.status = 'final' AND e.deleted_at IS NULL
) lv ON true
ORDER BY <sort expression>, f.id
LIMIT :size OFFSET (:page - 1) * :size;
```

If a page past the end is requested, no rows come back and therefore no `total`; the repository then runs a separate `count(*)` so the response still reports the true total.

### 15.3 Sort keys

| `sort` | Expression (asc) | Notes |
|---|---|---|
| `name` | `lower(f.last_name), lower(f.first_name)` | Default |
| `mrn` | `f.mrn` | Zero-padded, so text order = numeric order |
| `age` | `f.date_of_birth DESC` | Youngest first for ascending age |
| `dx` | `lower(pc.description) NULLS LAST` | |
| `visit` | `lv.last_visit NULLS LAST` | Default direction `desc` |
| `egfr` | rejected, `422` | ADR-020 |

`f.id` is always the final tie-breaker so paging is stable. Sorting by `dx` or `visit` evaluates the lateral joins for every filtered row before `LIMIT`; at ≤ 10,000 patients this stays well inside the latency target (§26).

**Needs attention filter:** the UI first calls ai-svc `GET /insights/worklist?attention=true`, then calls `GET /patients?ids=…` with those ids plus any other filters. patient-svc pages and sorts within them. More than 500 ids → `422` (the worklist is far smaller at clinic scale; a POST search endpoint is the upgrade path).

---

## 16. Concurrency and transactions

### 16.1 Isolation and locking

| Setting | Value | Why |
|---|---|---|
| Isolation level | READ COMMITTED (default) | Each write is short and locks what it touches |
| Aggregate lock | `SELECT … FROM patients WHERE id=$1 AND deleted_at IS NULL FOR UPDATE` at the start of every write that touches patient-level invariants | Serializes primary changes, allergy status, problem-list linkage |
| Lock order | patients → encounters → patient_conditions / allergies / medications | One global order prevents deadlocks |
| `lock_timeout` | 3 s (role setting) | A stuck lock becomes a fast `503` instead of a hung request |
| `statement_timeout` | 3 s (connection) / 5 s (role) | Upper bound on any query |

### 16.2 Optimistic locking

| Resource | Column | Checked on |
|---|---|---|
| Patient | `patients.version` | `PATCH /patients/{id}` (all fields, including stage and allergy status) |
| Encounter | `encounters.version` | `PATCH` draft, `POST /finalize` |

Sub-resources (conditions, medications, allergies) are not versioned; they are small, single-purpose edits protected by the patient row lock. Allergy add/remove bump `patients.version` because they change `allergy_status`, and return `patient_version`.

### 16.3 Race scenarios and outcomes

| Race | Outcome |
|---|---|
| Two clinicians edit demographics | The second `PATCH` gets `409 VERSION_CONFLICT`; UI shows "This record was changed by someone else" with Reload |
| Two "Set as primary" clicks on different conditions | Serialized by the patient lock; last one wins; exactly one primary (also guaranteed by the partial unique index) |
| Remove last allergy while another clinician adds one | Serialized; the final `allergy_status` matches the remaining rows |
| Finalize while someone edits the same draft | Second request waits on the encounter row lock, then sees `final` → `409 ENCOUNTER_FINAL` |
| Two registrations at once | Distinct MRNs from the sequence |
| Lab report created while the patient is being deleted | lab-svc's `basic` call returns 404 after the delete commits; before it, the report is accepted (soft delete keeps the reference valid) |

---

## 17. Security and authorization

### 17.1 Request authentication (every route except health)

```python
# app/api/deps.py
async def current_user(authorization: str = Header(...), jwks: JwksCache = Depends(get_jwks)) -> User:
    token = parse_bearer(authorization)                         # 401 UNAUTHENTICATED if absent/malformed
    claims = jwt.decode(token, key=await jwks.key_for(token),   # RS256 only; refresh JWKS once on unknown kid
                        algorithms=["RS256"], audience=settings.jwt_audience, issuer=settings.jwt_issuer,
                        options={"require": ["exp", "iat", "sub", "role"]}, leeway=30)
    return User(id=UUID(claims["sub"]), role=claims["role"], name=claims.get("name") or "Unknown clinician")

def require_role(*roles: str):
    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user
    return dep

Clinician = Annotated[User, Depends(require_role("clinician"))]
```

JWT verification lives in `libs/common` (shared infra) and is the same code in every service.

### 17.2 Authorization model

| Route group | Requirement |
|---|---|
| `/patients/**`, `/encounters` | Valid JWT, role `clinician` |
| `/internal/**` | Valid JWT, role `clinician` (user-initiated calls forward the user's JWT, HLD v2 §9); **blocked at the gateway** so they are unreachable from outside the private network |
| `/health`, `/ready`, `/metrics` | No auth; not routed by the gateway |

Care-team (per-patient) authorization is future work (HLD v2 §20). Every clinician can see every patient, and every access is audited.

### 17.3 Data protection

| Concern | Measure |
|---|---|
| SQL injection | Bound parameters only; `LIKE` input escaped; no string-built SQL |
| Mass assignment | `extra="forbid"`; read-only fields rejected |
| PHI in logs | Logs carry ids, route templates and request ids only; request bodies, names and notes are never logged; validation errors log field names, not values |
| PHI in errors | Error messages never echo stored values |
| Data minimization | `/internal/.../chart` omits name, MRN and contact details (P-12) |
| DB privileges | `patient_svc` owns only `patient_db`; no superuser, no CREATEDB; cannot connect to other databases (§8.7) |
| Container | Non-root user, read-only root filesystem, no published port |
| Secrets | `PATIENT_DB_PW` from env or Docker secret; never in images or git |

---

## 18. Error handling and error catalog

### 18.1 Envelope (HLD v2 §12)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Some fields need attention.",
    "details": [
      {"field": "vitals.systolic_bp", "issue": "Systolic must be higher than diastolic."},
      {"field": "chief_complaint", "issue": "Chief complaint is required to finalize."}
    ],
    "request_id": "req-7f3a9c"
  }
}
```

### 18.2 Catalog

| HTTP | `code` | When |
|---|---|---|
| 400 | `MALFORMED_REQUEST` | Body is not JSON |
| 401 | `UNAUTHENTICATED` | Missing, expired or invalid token |
| 403 | `FORBIDDEN` | Role is not `clinician` |
| 404 | `NOT_FOUND` | Patient (or soft-deleted patient), encounter, condition, medication or allergy not found under this patient; `details.resource` names which |
| 409 | `VERSION_CONFLICT` | `version` mismatch on patient or encounter |
| 409 | `ENCOUNTER_FINAL` | Edit, finalize or delete of a final encounter |
| 409 | `ALLERGIES_PRESENT` | Setting `nka`/`unknown` while active allergies exist |
| 409 | `DUPLICATE_ALLERGY` | Same allergen already active |
| 409 | `CONDITION_NOT_ACTIVE` | Making a resolved condition primary |
| 409 | `MEDICATION_ALREADY_DISCONTINUED` | Discontinue or edit a discontinued medication |
| 409 | `PRIMARY_CONFLICT` | Partial unique index hit (should be impossible under the patient lock; logged as ERROR) |
| 422 | `VALIDATION_ERROR` | Schema or rule failure, unsupported sort, too many ids, both list modes |
| 503 | `DB_UNAVAILABLE` | Pool exhausted, connection refused, `lock_timeout` or `statement_timeout` hit |
| 500 | `INTERNAL_ERROR` | Anything else (logged with stack trace; message is generic) |

### 18.3 Database error mapping

| SQLSTATE / source | Mapped to |
|---|---|
| `23505` unique violation on `conditions_one_primary` | 409 `PRIMARY_CONFLICT` |
| `23505` on `allergies_one_per_allergen` | 409 `DUPLICATE_ALLERGY` |
| `23505` on `patients_mrn_uq` | Sequence advanced, retried once (§13.1) |
| `23514` check violation | 422 `VALIDATION_ERROR` (logged at ERROR: the service should have caught it) |
| `23503` foreign key violation | 404 `NOT_FOUND` |
| `P0001` with hint `ENCOUNTER_FINAL` | 409 `ENCOUNTER_FINAL` (logged at ERROR) |
| `P0001` with hint `NO_HARD_DELETE` / `AUDIT_APPEND_ONLY` | 500 (a code path tried to hard-delete; logged at ERROR) |
| `55P03` lock not available, `57014` query cancelled | 503 `DB_UNAVAILABLE` |
| Connection errors, pool timeout | 503 `DB_UNAVAILABLE` |

The mapping lives in one exception handler (`app/core/errors.py`). The constraint name comes from `asyncpg` (`exc.constraint_name`); the trigger hint from `exc.hint`.

---

## 19. Audit trail

### 19.1 What is recorded

| Action | Resource | Trigger |
|---|---|---|
| `patient.create`, `patient.update`, `patient.delete` | patient | Writes |
| `patient.view` | patient | `GET /patients/{id}` |
| `condition.add`, `condition.update`, `condition.delete` | condition | Writes |
| `medication.add`, `medication.update`, `medication.discontinue` | medication | Writes |
| `allergy.add`, `allergy.remove` | allergy | Writes |
| `encounter.create_draft`, `encounter.update_draft`, `encounter.finalize`, `encounter.delete_draft` | encounter | Writes |
| `encounter.view` | encounter | `GET .../encounters/{eid}` |
| `chart.read_internal` | patient | `/internal/patients/{id}/chart` and tool endpoints (actor = forwarded user) |
| `chart.bulk_export` | — | Each page of `/internal/patients/charts` (`details.count`) |

Not audited: list and search pages, `basic`, dashboard encounter queries (they show minimal fields and would flood the table).

### 19.2 Row content

`details` holds **field names**, never values: for example `{"fields": ["phone", "established_ckd_stage"]}`, or for finalize `{"problem_list": {"added": 1, "reactivated": 0, "linked": 0}}`. `request_id` links the row to logs across services.

### 19.3 Transaction rule

Audit rows for writes are inserted in the same transaction as the change (P-07). For `GET` endpoints the audit insert is the only write in a short transaction; if it fails, the read fails with `503`, because an unaudited chart read is not acceptable.

### 19.4 Retention

Kept indefinitely in this project. For a real deployment, partition `audit_events` by month and archive per policy.

---

## 20. Observability

### 20.1 Logs

Structured JSON on stdout via the shared middleware in `libs/common`:

```json
{"ts":"2026-11-11T17:45:02.113Z","level":"INFO","service":"patient-svc","request_id":"req-7f3a9c",
 "user_id":"5b1e…","method":"POST","route":"/patients/{id}/encounters","status":201,"latency_ms":63,
 "db_ms":21,"event":"request.completed"}
```

Business events at INFO: `encounter.finalized` (with counts), `version_conflict`, `problem_list.linked`. Never names, notes or values.

### 20.2 Metrics (`/metrics`, Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | counter | `route`, `method`, `status` |
| `http_request_duration_seconds` | histogram | `route`, `method` |
| `db_query_duration_seconds` | histogram | `repo_method` |
| `db_pool_checked_out` | gauge | — |
| `encounters_finalized_total` | counter | — |
| `problem_list_changes_total` | counter | `kind` (added, reactivated, linked) |
| `optimistic_conflicts_total` | counter | `resource` |
| `db_trigger_rejections_total` | counter | `hint` (should stay at 0) |

### 20.3 Health

| Endpoint | Checks | Used by |
|---|---|---|
| `GET /health` | Process is up | Docker healthcheck, liveness |
| `GET /ready` | `SELECT 1` within 1 s, and Alembic revision in DB = code head | Gateway `/ready`, readiness |

---

## 21. Configuration

All settings via `pydantic-settings`, prefixed per service in `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `PATIENT_DATABASE_URL` | — (required) | `postgresql+asyncpg://patient_svc:…@nephro-pg:5432/patient_db` |
| `PATIENT_TEST_DATABASE_URL` | — | Test database in the same container |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 5 / 5 | Per replica (budget §8.2) |
| `DB_POOL_TIMEOUT_S` | 5 | Wait for a free connection before `503` |
| `DB_STATEMENT_TIMEOUT_MS` | 3000 | Per statement |
| `DB_CONNECT_RETRIES` | 30 | Start-up wait for the external container |
| `RUN_MIGRATIONS_ON_START` | `true` | Entrypoint runs `alembic upgrade head` under an advisory lock |
| `SEED_ON_START` | `false` | Dev convenience; seed is idempotent |
| `JWKS_URL` | `http://auth-svc:8000/.well-known/jwks.json` | Public keys |
| `JWKS_CACHE_TTL_S` | 300 | Refresh interval; stale keys kept on fetch failure |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `nephro-auth` / `nephro-api` | Token checks |
| `CLINIC_TZ` | `Asia/Kolkata` | "Today" for date-only rules (P-09) |
| `LIST_DEFAULT_PAGE_SIZE` / `LIST_MAX_PAGE_SIZE` | 20 / 100 | Pagination |
| `LIST_MAX_IDS` | 500 | `ids` filter cap |
| `INTERNAL_BULK_MAX_LIMIT` | 200 | `/internal/patients/charts` page cap |
| `INTERNAL_NOTE_MAX_CHARS` | 1500 | Tool endpoint truncation |
| `LOG_LEVEL` | `INFO` | |
| `PORT` | 8000 | Inside the container only |

---

## 22. Code layout

```
services/patient/
  pyproject.toml
  Dockerfile
  docker-entrypoint.sh
  alembic.ini
  alembic/
    env.py                    async env, advisory lock, uses PATIENT_DATABASE_URL
    versions/
      0001_baseline.py        DDL of §9.2
  app/
    main.py                   app factory, routers, middleware, exception handlers
    core/
      config.py               Settings
      db.py                   engine, session factory, session dependency
      clock.py                now(), today() in CLINIC_TZ (injectable for tests)
      errors.py               domain exceptions + DB error mapping (§18)
      audit.py                AuditWriter.record(...)
    api/
      deps.py                 current_user, require_role, pagination params
      routers/
        patients.py           /patients, /patients/{id}
        conditions.py         /patients/{id}/conditions
        medications.py        /patients/{id}/medications
        allergies.py          /patients/{id}/allergies
        encounters.py         /patients/{id}/encounters/**
        encounter_queries.py  /encounters
        internal.py           /internal/patients/**
        health.py             /health, /ready
    domain/                   pure functions, no I/O
      patient_rules.py        dob, age, allergy-status transitions
      encounter_rules.py      common + finalizable validation, follow-up vs visit date
      problem_list.py         infer_category, link resolution order
      search.py               parse_query, escape_like, sort map
    schemas/                  Pydantic request/response models
    models/                   SQLAlchemy models (§10)
    repositories/
      patients.py  conditions.py  medications.py  allergies.py  encounters.py  internal.py  audit.py
    services/
      patients.py  conditions.py  medications.py  allergies.py  encounters.py  internal.py
    scripts/
      wait_for_db.py
  seed/
    seed.py                   idempotent loader (§23.3)
    patients.json             the ten scenario patients
  tests/
    unit/  api/  db/  contract/  conftest.py
```

Layering is enforced by an import test (`tests/unit/test_layers.py`): `domain` imports nothing from `api`, `services`, `repositories` or `models`; routers never import repositories directly.

---

## 23. Migrations and seed data

### 23.1 Alembic

- One baseline revision (`0001_baseline`) containing §9.2 verbatim via `op.execute`. Later changes are additive revisions.
- `env.py` uses the async engine and wraps the upgrade in an advisory lock so concurrent replicas do not race:

```python
async def run_migrations_online():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(hashtext('patient_db.migrations'))"))
        try:
            await conn.run_sync(do_run_migrations)
            await conn.commit()
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(hashtext('patient_db.migrations'))"))
```

- Migrations run as `patient_svc` (database owner). Nothing in them needs superuser, because `pg_trgm` is pre-installed by the provisioning script.
- Policy: forward-only in practice; every revision has a `downgrade()` for local use, never run against shared data.

### 23.2 Deterministic ids (P-03)

```python
# libs/common/seed_ids.py  (infrastructure constant, no domain logic)
SEED_NAMESPACE = uuid.UUID("9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10")

def patient_id(mrn: str) -> uuid.UUID:        # used by patient seed and lab seed
    return uuid.uuid5(SEED_NAMESPACE, f"patient:{mrn}")

def user_id(email: str) -> uuid.UUID:         # used by auth seed and patient seed (clinician_id)
    return uuid.uuid5(SEED_NAMESPACE, f"user:{email.lower()}")
```

### 23.3 Seed loader

`python -m seed.seed [--reset]`

1. If `--reset`: `TRUNCATE audit_events, encounter_diagnoses, encounter_vitals, patient_conditions, medications, allergies, encounters, patients RESTART IDENTITY` (TRUNCATE bypasses the no-delete triggers; the flag is refused unless `APP_ENV=dev`).
2. For each patient in `seed/patients.json`: skip if the MRN exists; otherwise insert with `id = patient_id(mrn)` and the explicit MRN.
3. Dates are stored as **offsets in days** in the JSON and resolved against today at load time, so the dashboard always has recent visits and upcoming follow-ups.
4. Encounters are inserted as drafts with their children, then finalized through the same repository calls the API uses, so seed data obeys every trigger and constraint.
5. After loading: `SELECT setval('patient_mrn_seq', (SELECT max(substring(mrn FROM 4)::int) FROM patients))` so the next registration gets `PT-000111`.
6. Clinician ids/names: `user_id("dr.rao@nephrocare.demo")` "Dr. Anita Rao" and `user_id("dr.malhotra@nephrocare.demo")` "Dr. Karan Malhotra", matching auth-svc's seed.

### 23.4 Seed scenarios this service must carry (HLD v2 §18)

| MRN | Patient | What patient-svc data makes the scenario work |
|---|---|---|
| PT-000101 | Ramesh Kulkarni | Stage G3b; penicillin allergy; 4 conditions (E11.21 primary); 4 meds; 3 final encounters + **1 draft** |
| PT-000102 | Sunita Verma | Stage G3a; clean record; 2 final encounters |
| PT-000103 | Arjun Mehta | **`allergy_status = unknown`**; a final encounter **without vitals** |
| PT-000104 | Fatima Sheikh | Stage G4; two allergies (one severe); 5 conditions |
| PT-000105 | Vikram Rao | **No medications**; no stage; `nka` |
| PT-000106 | Lakshmi Iyer | Established **G4** (lab-svc's latest eGFR is G3b → mismatch) |
| PT-000107 | Mohan Das | Last encounter ~230 days ago (lab-svc carries the "no recent labs" part) |
| PT-000108 | Priya Nair | **Near-empty chart**: PMH only, no conditions, no meds, no encounters, `unknown` allergies |
| PT-000109 | Aditya Singh | Stage G5; latex allergy; latest encounter 6 days ago with follow-up in 7 days |
| PT-000110 | Kavita Joshi | No stage; lupus nephritis primary; **active medication past its end date** |

Seed test asserts each bold item, so a seed change that breaks a demo scenario fails CI.

---

## 24. Container image and compose wiring

### 24.1 Dockerfile

```dockerfile
FROM python:3.12-slim AS build
WORKDIR /build
COPY libs/common /build/libs/common
COPY services/patient /build/services/patient
# Installs libs/common and the service package with its pinned dependencies into /install
RUN pip install --no-cache-dir --prefix=/install ./libs/common ./services/patient

FROM python:3.12-slim
RUN useradd --system --uid 10001 app
WORKDIR /app
COPY --from=build /install /usr/local
COPY services/patient/ /app/
USER app
ENV PYTHONUNBUFFERED=1 PORT=8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health',timeout=2)"
ENTRYPOINT ["./docker-entrypoint.sh"]
```

Multi-stage build, non-root user, no build tools in the runtime image. The build context is the repository root so `libs/common` is available.

```bash
#!/usr/bin/env sh
# services/patient/docker-entrypoint.sh
set -eu
python -m app.scripts.wait_for_db                     # up to DB_CONNECT_RETRIES
if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then alembic upgrade head; fi
if [ "${SEED_ON_START:-false}" = "true" ]; then python -m seed.seed; fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --no-server-header
```

### 24.2 Compose excerpt (existing Postgres on an external network)

```yaml
services:
  patient-svc:
    build:
      context: .
      dockerfile: services/patient/Dockerfile
    environment:
      PATIENT_DATABASE_URL: postgresql+asyncpg://patient_svc:${PATIENT_DB_PW}@${PG_HOST:-nephro-pg}:5432/patient_db
      JWKS_URL: http://auth-svc:8000/.well-known/jwks.json
      JWT_ISSUER: nephro-auth
      JWT_AUDIENCE: nephro-api
      CLINIC_TZ: Asia/Kolkata
      RUN_MIGRATIONS_ON_START: "true"
      SEED_ON_START: ${SEED_ON_START:-false}
    networks: [backend, pgnet]
    read_only: true
    tmpfs: [/tmp]
    restart: unless-stopped
    # no "ports:" — only the gateway publishes a port

networks:
  backend: {}
  pgnet:
    external: true
    name: ${PG_NETWORK:-nephro-pgnet}
```

### 24.3 Make targets

| Target | Does |
|---|---|
| `make db-network` | `docker network create nephro-pgnet` (if missing) and `docker network connect --alias nephro-pg nephro-pgnet $PG_CONTAINER` (if not connected) |
| `make db-provision-patient` | §8.4 |
| `make migrate-patient` | `docker compose run --rm patient-svc alembic upgrade head` |
| `make seed-patient` | `docker compose run --rm patient-svc python -m seed.seed` |
| `make test-patient` | Unit + API + DB tests against `patient_db_test` |
| `make psql-patient` | Opens psql as `patient_svc` on `patient_db` |

---

## 25. Testing plan

### 25.1 Unit (pure, fast, no I/O)

| Area | Cases |
|---|---|
| `patient_rules` | Age on birthday and the day before; 29 Feb DOB in non-leap years; DOB "today" in IST at 00:30 IST (UTC still yesterday); age > 120 rejected |
| `encounter_rules` | Future visit by 59 s accepted, by 61 s rejected; follow-up equal to visit date accepted, day before rejected (IST); finalize requires cc, assessment and plan; whitespace-only counts as empty |
| `VitalsIn` | Every bound (49/50, 300/301, …); sys = dia rejected; 36.65 → 36.7; all-null = empty |
| `problem_list` | `infer_category` for N18.32, Q61.2, M32.14, E11.21, I12.9 (nephrology) and I10, E78.5, D63.1 (comorbidity); resolution order table §13.5 |
| `search` | `PT-000101`, `pt101`, `101`, `Kulkarni Ramesh`, `%_\` escaping, > 5 tokens truncated |
| Layering | `domain` has no forbidden imports |

### 25.2 API tests (real Postgres: `patient_db_test` on the existing container)

Fixture strategy: run `alembic upgrade head` once per session; `TRUNCATE … RESTART IDENTITY` between tests; JWTs signed by a test key served from a stub JWKS; `clock` overridden to a fixed IST date.

| Area | Cases |
|---|---|
| Auth | No token 401; wrong audience 401; role other than clinician 403; internal routes also require a token |
| Patients | Create returns `PT-000101` then `PT-000102`; list filters (sex, stage, `none`, ids); each sort key and direction; paging stability; search by name tokens in either order and by MRN forms; page past end returns correct `total`; soft-deleted patient → 404 everywhere and absent from list |
| Optimistic lock | `PATCH` with stale version → 409; stage change bumps version |
| Conditions | Second primary clears the first; resolve primary → `primary_cleared`; making resolved primary → 409; ICD uppercased |
| Allergies | Add sets `has_allergies`; remove last → `unknown`; `nka` with allergies → 409; duplicate allergen → 409 |
| Medications | Discontinue sets today; discontinue twice → 409; `status=all` shows discontinued |
| Encounters | Draft with no vitals stores no vitals row; finalize without plan → 422; create final with `add_to_problem_list` → `added: 1`; same ICD again → `linked`; resolved ICD → `reactivated`; edit final → 409; delete final → 409; delete draft → hidden from history; PATCH with `status: final` is atomic (a forced failure in linkage leaves the draft unchanged) |
| Dashboard | Drafts mode total; follow-ups take only the latest final encounter per patient; past follow-ups excluded; both modes → 422 |
| Internal | `basic` 404 for deleted; `chart` has no name/MRN/contact fields; `encounter_index` lists all finals; tool endpoint truncation flag; bulk paging covers every patient exactly once |
| Audit | Each write produces exactly one row with field names and no values; failed write produces none |

### 25.3 Database tests

| Case | Expectation |
|---|---|
| `UPDATE encounters SET plan='x'` on a final row (raw SQL) | Exception with hint `ENCOUNTER_FINAL` |
| `INSERT encounter_vitals` for a final encounter | Exception |
| `DELETE FROM patients` | Exception `NO_HARD_DELETE` |
| `UPDATE audit_events` | Exception `AUDIT_APPEND_ONLY` |
| Two primaries via raw SQL | Unique violation |
| Connect as `patient_svc` to `lab_db` | Permission denied (isolation check, §8.7) |

### 25.4 Concurrency tests

Run two sessions with `asyncio.gather`: concurrent set-primary (exactly one primary), concurrent stale `PATCH` (one 200, one 409), concurrent finalize + edit (one 409), 20 concurrent registrations (20 distinct MRNs).

### 25.5 Contract tests

JSON Schemas for `/internal/patients/{id}/basic`, `/chart`, tool endpoints and `/internal/patients/charts` are committed under `contracts/patient/`. patient-svc tests validate its responses against them; lab-svc and ai-svc tests validate their fakes against the same files, so a breaking change fails on both sides.

### 25.6 Seed test

Load the seed into the test database and assert the scenario facts in §23.4.

---

## 26. Performance and capacity

| Query | Plan target | Estimated cost at 10k patients / 200k encounters |
|---|---|---|
| List, name sort, page 1 | `count(*) OVER ()` and the two lateral joins run for every filtered row before `LIMIT`; each lateral is an index probe | ~10k probe pairs unfiltered → tens of ms; a search or filter cuts this to a handful |
| Name search (3+ char token) | Bitmap scan on `patients_search_trgm` | < 10 ms |
| MRN search | Index range scan on `patients_mrn_uq` | < 2 ms |
| Sort by `visit` | Lateral `max()` via `encounters_patient_final` (index-only top-1 per patient) | ~10k probes, < 60 ms |
| Patient detail | PK lookup + 4 small aggregates | < 10 ms |
| Encounter history | `encounters_patient_date` | < 5 ms |
| Follow-ups | `DISTINCT ON` over final encounters | ~200k rows scanned worst case → the first query to watch; add a `patient_followups` projection if p95 > 150 ms |
| Bulk page of 200 | PK range + correlated sub-selects per patient | < 300 ms |

Measurement plan: seed a 10k / 200k synthetic set in `patient_db_test` (`seed --scale 10000`) and record `EXPLAIN (ANALYZE, BUFFERS)` for each query above in `docs/db/explain/`. Scaling steps, in order: read replica for list/search; PgBouncer when replicas grow (transaction pooling is compatible because no session state is used); keyset pagination for deep pages; a `last_visit` column maintained in the finalize transaction if the lateral `max()` becomes the bottleneck.

---

## 27. Deltas to HLD v2 and open questions

### 27.1 Additions and clarifications (to fold into HLD v3)

| # | Item | HLD v2 says | This document | Action |
|---|---|---|---|---|
| 1 | Clinician name on encounters | `clinician_id` only; JWT claims list has no `name` | Store `clinician_name` snapshot from a `name` claim | **auth-svc must add `name` to the access token** (HLD v2 §7.2) |
| 2 | When diagnoses join the problem list | "same transaction as the encounter save" and "finalizing … inserts" | At **finalize** only; insert, reactivate or link (§13.5) | Clarify §5.3 |
| 3 | Category of auto-added conditions | Not specified | `infer_category` with E1x.2/I12/I13 added (§13.6) | Note in §5.3 |
| 4 | `allergy_status` transitions | Field exists | `has_allergies` derived; `nka`/`unknown` only with zero allergies; last removal → `unknown` | Add to §5.3 |
| 5 | Version bump scope | "PATCH requires version" | Any change to the patients row bumps `version` (incl. allergy status via allergy routes) | Add to §5.3 |
| 6 | `next_follow_up` on detail | Not specified (prototype shows last final's date even if past) | Earliest future follow-up among final encounters | Confirm with UI |
| 7 | Upcoming follow-ups list | "follow-up date today or later" | Only from each patient's **latest** final encounter | Update §11.2 |
| 8 | Internal tool endpoints | Tools named, endpoints not | `/conditions`, `/medications-allergies`, `/encounters` under `/internal/patients/{id}` (§12.4) | Add to §11.2 |
| 9 | Internal chart minimization | ai-svc minimizes | patient-svc also omits name, MRN, contact details (P-12) | Add to §10.3 |
| 10 | Encounter immutability | Service rule | Also a DB trigger, plus no-hard-delete triggers on clinical tables | Add to §5.3 |
| 11 | Existing Postgres container | "run `init-databases.sh` against it once" | initdb scripts do not run on a non-empty volume; use the idempotent `docker exec` script and an external network (§8) | Update §17.2 |
| 12 | Encounter field naming | ER uses `encounter_type` | API uses `encounter_type` too (prototype's `type`) | None |
| 13 | Medication route | Free text | Codes `oral`, `sc`, `iv`, `topical`, `inhaled`, `other` | Note in §5.3 |
| 14 | Deterministic seed ids | Not specified | UUIDv5 by MRN / email shared by all seeds (§23.2) | Add to §18 |

### 27.2 Open questions

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Exact name and published port of the existing Postgres container, and its major version | Assume ≥ 13, alias `nephro-pg` on `nephro-pgnet`; confirm with §8.2 commands |
| Q2 | Should a patient soft delete be possible when lab results exist? | Allowed; lab data stays and is hidden because `basic` returns 404 |
| Q3 | Addenda for final encounters | Out of scope; corrections are new encounters |
| Q4 | Should list rows carry `allergy_status` (not shown in the prototype list)? | Included; cheap, and useful for a future column |
| Q5 | Care-team scoping of patient access | Out of scope (HLD v2 §20) |

---

## 28. Build checklist

Ordered so each step is testable before the next.

| # | Step | Done when |
|---|---|---|
| 1 | Run §8.2 discovery on the existing container; record name, port, version | Values in `.env` (`PG_CONTAINER`, `PG_HOST`, `PATIENT_DB_PW`) |
| 2 | `make db-network` and `make db-provision-patient` | §8.7 checks pass (own DB yes, `lab_db` refused) |
| 3 | Service skeleton: config, db, health, error envelope, JWT dependency | `/health` 200, `/ready` 200, unauthenticated call 401 |
| 4 | Migration `0001_baseline` | `alembic upgrade head` clean; DB tests §25.3 pass |
| 5 | Patients: create, get, patch, delete, list, search, sort | §25.2 patient cases pass |
| 6 | Conditions, medications, allergies | Sub-resource cases pass |
| 7 | Encounters: draft, edit, finalize, delete, problem-list linkage | Encounter cases + concurrency tests pass |
| 8 | `/encounters` dashboard modes | Dashboard cases pass |
| 9 | Internal endpoints + JSON Schema contracts | Contract tests pass |
| 10 | Audit on every route in §19.1 | Audit cases pass |
| 11 | Seed with deterministic ids | Seed test §25.6 passes; dashboard shows drafts and follow-ups |
| 12 | Dockerfile, entrypoint, compose wiring, make targets | `docker compose up patient-svc` reaches ready against the existing container |
| 13 | Export OpenAPI to `docs/api/patient-svc.json`; capture `EXPLAIN` plans | Files committed |
