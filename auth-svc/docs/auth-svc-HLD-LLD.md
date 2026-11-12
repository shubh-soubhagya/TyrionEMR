# auth-svc — High-Level and Low-Level Design

**Project:** General Nephrology EMR (NephroCare)
**Service:** `auth-svc` (identity, credentials, sessions, token signing keys)
**Parent design:** `HLD-v2.md` — this document expands §4.1, §5.1–5.2, §7, §8 (auth parts), §11.1, §12, §17 and ADR-004 / ADR-018 for one service.
**Database:** `auth_db` on the **existing PostgreSQL Docker container** (one instance, one database per service).
**Data:** Synthetic only. Demo clinicians come from the seed.
**Status:** Ready to implement. Build order step 2 of HLD-v2 §21 ("auth-svc + gateway end to end").

---

## Table of Contents

**Part A — High-Level Design**

1. [Purpose and scope](#1-purpose-and-scope)
2. [Requirements](#2-requirements)
3. [Context and position in the system](#3-context-and-position-in-the-system)
4. [Responsibilities and boundaries](#4-responsibilities-and-boundaries)
5. [Session and token model](#5-session-and-token-model)
6. [Key flows (overview)](#6-key-flows-overview)
7. [Data ownership and storage](#7-data-ownership-and-storage)
8. [Security design and threat model](#8-security-design-and-threat-model)
9. [Failure modes and availability](#9-failure-modes-and-availability)
10. [Scalability and sizing](#10-scalability-and-sizing)
11. [Design decisions (auth-specific)](#11-design-decisions-auth-specific)
12. [Refinements to HLD-v2](#12-refinements-to-hld-v2)

**Part B — Low-Level Design**

13. [Tech stack and dependencies](#13-tech-stack-and-dependencies)
14. [Code layout](#14-code-layout)
15. [Database design (DDL, indexes, migrations)](#15-database-design-ddl-indexes-migrations)
16. [Using the existing Docker Postgres container](#16-using-the-existing-docker-postgres-container)
17. [API specification](#17-api-specification)
18. [Error codes](#18-error-codes)
19. [Detailed flows and algorithms](#19-detailed-flows-and-algorithms)
20. [Component design (classes and key code)](#20-component-design-classes-and-key-code)
21. [Configuration](#21-configuration)
22. [Contracts with the gateway, other services and Angular](#22-contracts-with-the-gateway-other-services-and-angular)
23. [Containerization and runtime](#23-containerization-and-runtime)
24. [Observability](#24-observability)
25. [Testing](#25-testing)
26. [Runbooks](#26-runbooks)
27. [Implementation checklist](#27-implementation-checklist)

---

# Part A — High-Level Design

## 1. Purpose and scope

auth-svc is the **security boundary** of the platform. It is the only component that:

- stores credentials (argon2id password hashes),
- holds the **private** signing key,
- mints access tokens (JWT, RS256) and refresh tokens (opaque, rotated),
- publishes the public keys (JWKS) that the gateway and every other service use to verify tokens **locally**.

It knows nothing about patients, labs or AI. No other service reads `auth_db`.

### In scope
- Sign up (feature-flagged), sign in, silent refresh, sign out, current user.
- Account lockout after repeated failed sign-ins.
- Refresh-token rotation with theft detection (family revocation).
- JWKS and key rotation.
- Seed and invite scripts for creating clinicians.

### Out of scope (deliberate, per HLD-v2 ADR-018 and §20)
- Admin role, admin screens, user-management API.
- Password reset by email, email verification, MFA, SSO/federation (listed as future work).
- Authorization decisions for clinical data (each service owns its own authorization from the JWT claims).

---

## 2. Requirements

### 2.1 Functional

| # | Requirement | Source |
|---|---|---|
| F1 | A user can create a clinician account with full name, email and password, when public signup is enabled | HLD-v2 §7.1, prototype "Create account" tab |
| F2 | Password rules: at least 10 characters, contains a letter and a number, not a commonly used password | HLD-v2 §7.1, prototype password checklist |
| F3 | A user can sign in with email and password and receives an access token and a refresh cookie | HLD-v2 §7.1 |
| F4 | Five consecutive failed sign-ins lock the account for 15 minutes | HLD-v2 §7.1, prototype lockout text |
| F5 | Wrong email and wrong password produce the same message ("Invalid email or password.") | HLD-v2 §7.1 |
| F6 | The SPA can obtain a new access token without user action while the refresh token is valid | HLD-v2 §7.2, §15.2 |
| F7 | Presenting an already-used refresh token revokes the whole session family | HLD-v2 §7.1 |
| F8 | Sign-out revokes the session family and clears the cookie | HLD-v2 §7.1, §7.3b |
| F9 | The top bar can show the signed-in clinician's name and role | HLD-v2 §7.3b, `GET /auth/me` |
| F10 | Gateway and services verify tokens without calling auth-svc per request | HLD-v2 §7.2, ADR-004 |
| F11 | One role, `clinician`, carried as a claim | HLD-v2 §7.3, ADR-018 |

### 2.2 Non-functional

| Area | Target |
|---|---|
| Latency (p95, single replica, warm) | login and signup ≤ 400 ms (dominated by argon2), refresh ≤ 50 ms, me ≤ 30 ms, JWKS ≤ 10 ms |
| Availability impact | If auth-svc is down, already-issued access tokens keep working until expiry (≤ 15 min) because verification is local |
| Security | Private key never leaves auth-svc; refresh tokens stored only as hashes; no tokens, passwords or emails in logs |
| Statelessness | No in-process session state; any replica can serve any request |
| Portability | `auth_db` can move to another server by changing `AUTH_DATABASE_URL` |
| Operability | `/health`, `/ready`, `/metrics`, JSON logs with `request_id` |

---

## 3. Context and position in the system

```mermaid
flowchart LR
    U([Nephrologist]) --> SPA[Angular SPA]
    SPA -- "POST /api/auth/login, /signup, /refresh, /logout<br/>GET /api/auth/me" --> GW[API Gateway]
    GW -- "prefix /api stripped<br/>Cookie and Set-Cookie passed through" --> AUTH[auth-svc]
    AUTH --- DB[("auth_db<br/>on existing Postgres container<br/>role auth_svc")]

    GW -. "GET /.well-known/jwks.json<br/>(cached, refetch on unknown kid)" .-> AUTH
    PAT[patient-svc] -. JWKS .-> AUTH
    LAB[lab-svc] -. JWKS .-> AUTH
    AI[ai-svc] -. JWKS .-> AUTH

    SPA -- "Bearer JWT on every clinical call" --> GW
    GW --> PAT & LAB & AI
```

- **Solid arrows**: user-initiated auth traffic through the gateway.
- **Dotted arrows**: background JWKS fetches over the private Docker network. They happen at startup, on cache expiry (5 min) and when an unknown `kid` is seen. They are not on the request path.
- auth-svc **depends on nothing** except its own database.

---

## 4. Responsibilities and boundaries

| auth-svc does | auth-svc does not |
|---|---|
| Hash and verify passwords (argon2id) | Know about patients, labs, encounters or AI |
| Enforce password policy and account lockout | Run rate limiting per IP (gateway does, HLD-v2 §8) |
| Issue RS256 access tokens with `sub`, `role`, `iss`, `aud`, `iat`, `exp`, `jti`, `kid` | Decide what a clinician may do with a patient record |
| Issue, rotate and revoke opaque refresh tokens | Store anything in the browser other than the refresh cookie |
| Publish JWKS, support two keys during rotation | Expose user-management or admin routes |
| Serve `GET /auth/me` | Call any other service |

Shared infrastructure it uses from `libs/common` (infra-only, no domain models): error envelope, request-id and logging middleware, JWT verification helper (the same code the gateway and services use), pagination is not needed here.

---

## 5. Session and token model

```mermaid
flowchart LR
    subgraph Browser
      M["Access token<br/>in memory (Angular signal)<br/>15 min"]
      C["Refresh token<br/>httpOnly cookie<br/>Path=/api/auth<br/>SameSite=Strict, Secure"]
    end
    subgraph auth_db
      F["refresh_tokens rows<br/>one family per sign-in<br/>only sha256 stored"]
    end
    M -- "Authorization: Bearer" --> APIs[Gateway and services]
    C -- "sent only to /api/auth/*" --> AUTHS[auth-svc]
    AUTHS --> F
```

| Token | Format | Lifetime | Where it lives | How it is checked |
|---|---|---|---|---|
| Access | JWT, RS256, `kid` header | 15 min (`ACCESS_TOKEN_TTL_MIN`) | Memory only (never localStorage) | Signature with JWKS public key, `iss`, `aud`, `exp` — locally in gateway and each service |
| Refresh | 256-bit random, base64url (43 chars) | 7 days idle (`REFRESH_TOKEN_TTL_DAYS`), capped by a 30-day absolute session limit | httpOnly cookie | sha256 lookup in `refresh_tokens`, single use |
| Session family | `family_id` (UUID) shared by every refresh token in one sign-in | Until logout, reuse detection, idle expiry or absolute cap | `refresh_tokens.family_id` | Revoking a family ends that sign-in everywhere |

**Rotation chain.** Each refresh consumes the presented token and issues a new one in the same family:

```
login ─► RT1 ──refresh──► RT2 ──refresh──► RT3 (active)
          revoked,          revoked,
          replaced_by=RT2   replaced_by=RT3
```

If RT1 or RT2 is presented again outside the short race window, someone kept a copy: the whole family is revoked (RT3 included) and the user must sign in again.

---

## 6. Key flows (overview)

| Flow | Summary | Detail |
|---|---|---|
| Signup | Validate, check flag, hash, insert user, start a session (same as login) → `201` | §19.1 |
| Login | Look up by email (citext), check lock, verify hash (dummy hash if no user), update counters, start session → `200` | §19.2 |
| Refresh | Read cookie, lock the row, detect reuse or race, rotate, issue new access token → `200` | §19.3 |
| Logout | Revoke the family of the presented cookie if any, clear cookie → `204` (idempotent) | §19.4 |
| Me | Verify JWT, load user, check active → `200` | §19.5 |
| App reload | Access token is lost on reload; Angular calls `/auth/refresh` at boot to restore the session silently | §22.3 |
| Key rotation | Publish new key, wait, switch signer, wait, retire old key | §26.2 |

---

## 7. Data ownership and storage

- One database, `auth_db`, owned by role `auth_svc`, on the existing Postgres container. `CONNECT` is revoked from `PUBLIC`, so no other service role can open it (HLD-v2 §5.1).
- Two tables: `users`, `refresh_tokens`. Extension `citext` for case-insensitive unique email.
- No foreign keys point into `auth_db` from other databases. Other services store the user's UUID (`sub`) in `created_by` / `clinician_id` columns as a plain UUID.
- Users are never hard-deleted (deactivate with `is_active = false`), so those UUIDs never dangle.

Full DDL in §15.

---

## 8. Security design and threat model

### 8.1 Controls

| Area | Control |
|---|---|
| Password storage | argon2id (`argon2-cffi`), per-hash salt, cost from config, rehash on login when parameters change |
| Password input | 10–128 characters, letter and digit, not in the bundled common-password list, not equal to the email local part; upper bound prevents hashing-cost abuse |
| Brute force | Gateway rate limit on `/api/auth/login` and `/signup` (per IP) + account lockout (5 failures → 15 min) |
| User enumeration | Same `401 INVALID_CREDENTIALS` for unknown email and wrong password; a dummy argon2 verify runs for unknown emails so timing matches |
| Token forgery | RS256 only; verifiers pin `algorithms=["RS256"]` and reject `none`/HS*; private key file readable only by the service user |
| Token theft (access) | 15 min lifetime, memory-only storage on the client |
| Token theft (refresh) | httpOnly (no JS access), `SameSite=Strict`, `Secure`, `Path=/api/auth`, single use, reuse revokes the family, stored as sha256 |
| CSRF on cookie endpoints | `SameSite=Strict` + `Origin` header allow-list check on `/auth/refresh` and `/auth/logout` |
| Replay of access token after logout | Accepted risk up to 15 min (stateless JWT); documented trade-off (ADR-A3) |
| Transport | TLS terminates at the gateway or proxy in real deployments; auth-svc has no published port |
| Logging | Log `user_id`, outcome and `request_id`; never the email, password, tokens or cookie values |
| Containers | Non-root user, read-only key mount, minimal base image |

### 8.2 Threat model (STRIDE, focused)

| Threat | Example | Mitigation |
|---|---|---|
| **S**poofing | Password guessing | Lockout, gateway rate limit, argon2 cost, password policy |
| **S**poofing | Stolen refresh cookie used later | Rotation + family revocation on reuse, idle and absolute expiry |
| **T**ampering | Edited JWT claims (`role`) | RS256 signature; services re-verify (defense in depth, HLD-v2 §7.3) |
| **T**ampering | Algorithm confusion (`alg: HS256` signed with the public key) | Verifiers allow only RS256 and use the key matched by `kid` |
| **R**epudiation | "I never signed in" | Structured auth event logs with `user_id`, `request_id`, outcome, user agent class |
| **I**nformation disclosure | DB dump leaks sessions | Only sha256 of refresh tokens and argon2 hashes are stored |
| **I**nformation disclosure | Enumeration via signup | `409 EMAIL_TAKEN` reveals existence; accepted for the demo because signup is flag-gated; production uses invites (signup off) |
| **D**enial of service | Many logins with huge passwords | 128-char cap, argon2 semaphore (bulkhead), gateway body size limit and rate limit |
| **D**enial of service | Attacker locks a victim's account | Lockout is temporary (15 min); gateway per-IP limit slows it; accepted trade-off for a single-clinic tool |
| **E**levation of privilege | Self-signup as admin | No admin role exists; `role` is server-assigned, never read from the request |

---

## 9. Failure modes and availability

| Failure | Effect | Handling |
|---|---|---|
| auth-svc down | No new sign-ins or refreshes. Existing access tokens keep working ≤ 15 min | Gateway returns `502 UPSTREAM_UNAVAILABLE` for `/api/auth/*`; Angular shows sign-in error state |
| `auth_db` unreachable | Same as above; `/ready` returns `503` | `pool_pre_ping`, connect timeout 3 s, gateway timeout 5 s |
| JWKS fetch fails at a verifier | Verifier keeps using its cached keys | Cached keys survive fetch failures; unknown `kid` → `401` until fetch succeeds |
| Private key missing or unreadable at startup | Service refuses to start (fail fast) | `/health` never goes green; logs name the path |
| Concurrent refresh from two tabs | Second request carries the old cookie | Race window → `409 REFRESH_RACE`, cookie untouched, client retries once (§19.3) |
| argon2 saturation under load | Login latency rises | Semaphore caps concurrent hashes; scale replicas (§10) |
| Migration run by two replicas at once | Possible DDL race | Alembic takes a Postgres advisory lock (§15.4) |

---

## 10. Scalability and sizing

- **Stateless:** scale replicas horizontally behind the gateway. All state is in `auth_db`.
- **CPU and memory:** argon2id with 64 MiB memory cost uses 64 MiB per concurrent hash. With `ARGON2_MAX_CONCURRENCY=4` per process and 2 Uvicorn workers, peak hashing memory is about 512 MiB. Set the container limit accordingly or lower concurrency.
- **Traffic shape:** login and signup are rare (once per clinician per day or week). Refresh happens about every 15 minutes per active tab and is a single indexed row lock plus one insert. `/auth/me` is one primary-key read.
- **Verification load is zero on auth-svc** because tokens are verified locally everywhere else.
- **Connections:** `pool_size=5, max_overflow=5` per process. With 2 workers that is at most 20 connections. Check the shared container's `max_connections` budget across the four services (§16.6).
- **Growth path:** a refresh-token cleanup job keeps `refresh_tokens` small; a read replica is never needed for this service; moving `auth_db` to its own server is a connection-string change.

---

## 11. Design decisions (auth-specific)

### ADR-A1: Access token in memory, refresh token in an httpOnly cookie
**Why:** XSS cannot read the refresh token; a reload loses only the short-lived access token, which is restored by a silent refresh at app boot.
**Alternative rejected:** both tokens in localStorage (readable by any injected script).

### ADR-A2: Opaque refresh tokens with rotation and family revocation
**Why:** Server-side revocation is needed for logout and theft response; opaque random values carry nothing to decode; sha256 storage makes a DB leak useless for replay.
**Consequence:** One DB row per refresh. Cheap.

### ADR-A3: Stateless access tokens, no deny-list
**Why:** No per-request call to auth-svc or the database (HLD-v2 ADR-004).
**Consequence:** A token stays valid up to 15 min after logout. Accepted. If ever needed, add a `jti` deny-list in Redis checked by the gateway only.

### ADR-A4: sha256 for refresh-token hashes, argon2id for passwords
**Why:** Refresh tokens have 256 bits of entropy, so a fast hash is safe and allows an indexed lookup. Passwords are low entropy and need a slow, memory-hard hash.

### ADR-A5: Race window instead of failing concurrent refreshes
**Why:** Two tabs refreshing at the same moment is normal. Without a grace window the second request would look like theft and log the user out. A `409` with no cookie change lets the second tab retry with the cookie the first one already received. No token is ever issued from an old token, so the window gives an attacker nothing.

### ADR-A6: Lockout message is explicit (`429 ACCOUNT_LOCKED`)
**Why:** Matches the prototype and helps a real clinician understand why sign-in fails.
**Trade-off:** After five failures it reveals that the email exists. Mitigated by the gateway per-IP limit and by signup being off in production. A strict mode (return `401` while locked) is a one-line config change if required (`LOCKOUT_REVEAL=false`).

### ADR-A7: `kid` = RFC 7638 JWK thumbprint
**Why:** Deterministic from the key itself, so no separate kid registry and no chance of two keys sharing a kid.

---

## 12. Refinements to HLD-v2

These are additions made at LLD level. None changes the HLD contract seen by other services.

| # | Refinement | Reason | HLD-v2 section affected |
|---|---|---|---|
| R1 | `refresh_tokens.family_expires_at` column (absolute session cap, default 30 days) | Without it a rotating 7-day token slides forever | §5.2 ER diagram |
| R2 | `refresh_tokens.revoked_reason` column (`rotated`, `logout`, `reuse_detected`, `user_inactive`) | Audit and the race-window rule need to know why a row was revoked | §5.2 |
| R3 | `409 REFRESH_RACE` within `REFRESH_REUSE_GRACE_S` (default 10 s) | Multi-tab refresh races (ADR-A5) | §7.1, §15.2 |
| R4 | `Origin` allow-list check on cookie endpoints | CSRF defense in depth beside `SameSite=Strict` | §7.4 |
| R5 | Password max length 128 and "not equal to email local part" | DoS and obvious-password protection | §7.1 |
| R6 | Silent refresh at app boot | Access token is memory-only, so a reload needs it | §15.2 |
| R7 | Login and signup responses include the `user` object | Saves an immediate `/auth/me` call after sign-in | §11.1 |
| R8 | `LOCKOUT_REVEAL` flag | Lets production hide lock state if enumeration matters more than UX | §7.1 |
| R9 | Database is named `nephro_auth_db` (test: `nephro_auth_db_test`), set by `AUTH_DB_NAME` | The shared container already had an unrelated `auth_db`. Everywhere this document says `auth_db`, read `nephro_auth_db`. The role stays `auth_svc` | §7, §15, §16 |
| R10 | Login reserves an attempt atomically before verifying; `users.last_failed_at` and `LOGIN_FAILURE_WINDOW_MINUTES` decay old failures | Parallel guesses bypassed the lockout (N tried, not 5) and a correct guess could succeed after the lock | §15, §19.2 |
| R11 | In-process per-IP token bucket on login and signup; hash slots wait at most `ARGON2_QUEUE_TIMEOUT_S`, then `503 SERVICE_BUSY` | Defense in depth until the gateway exists; overload must shed load, not queue forever | §8, §10, §18, §21 |
| R12 | `ENVIRONMENT=production` startup guard; docs and schema disabled in production | Unsafe settings (seed users, insecure cookies, localhost CORS, readable key, open signup) must not reach production | §21, §28 |
| R13 | Hash-locked dependencies, base image pinned by digest, CI with audit and image scan | Reproducible, verifiable builds | §23, §28 |

---

# Part B — Low-Level Design

## 13. Tech stack and dependencies

| Concern | Choice | Notes |
|---|---|---|
| Runtime | Python 3.12 | Same base image across services |
| Web | FastAPI + Uvicorn | Async, OpenAPI at `/docs`, `/openapi.json` |
| Validation | Pydantic v2, `pydantic-settings`, `email-validator` | `EmailStr` needs `email-validator` |
| DB | SQLAlchemy 2.x async + `asyncpg` | Session per request, explicit transactions in the service layer |
| Migrations | Alembic (async template) | Own `alembic/` folder, own version table in `auth_db` |
| Passwords | `argon2-cffi` | argon2id |
| JWT | `PyJWT[crypto]` (uses `cryptography`) | RS256 sign and verify, JWK export |
| Tests | `pytest`, `pytest-asyncio`, `httpx` (ASGI transport) | Real Postgres test database on the same container |
| Lint | `ruff`, optional `mypy` | CI |

`pyproject.toml` (dependencies excerpt):

```toml
[project]
name = "auth-svc"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "email-validator>=2.1",
  "sqlalchemy[asyncio]>=2.0.30",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "argon2-cffi>=23.1",
  "pyjwt[crypto]>=2.8",
  "prometheus-client>=0.20",
  "nephro-common",            # libs/common, installed from the monorepo path
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27", "ruff", "mypy"]
```

---

## 14. Code layout

```
services/auth/
  Dockerfile
  entrypoint.sh
  pyproject.toml
  alembic.ini
  alembic/
    env.py                      async env, advisory lock, target_metadata
    versions/
      0001_initial.py           users, refresh_tokens, citext check
  app/
    main.py                     create_app(), lifespan (keys, hasher, engine, cleanup task)
    core/
      config.py                 Settings (pydantic-settings)
      logging.py                JSON logging setup (wraps libs/common)
      errors.py                 AuthError subclasses → libs/common AppError
      metrics.py                Prometheus counters and histograms
    api/
      deps.py                   get_session, get_settings, current_claims, require_trusted_origin
      routes_auth.py            /auth/signup, /auth/login, /auth/refresh, /auth/logout, /auth/me
      routes_wellknown.py       /.well-known/jwks.json
      routes_health.py          /health, /ready
      cookies.py                set_refresh_cookie, clear_refresh_cookie
    schemas/
      auth.py                   SignupIn, LoginIn, TokenOut, UserOut, JwksOut
    domain/
      password_policy.py        pure: check_password(pw, email) -> list[Violation]
      data/common_passwords.txt lowercased, one per line
      clock.py                  utcnow() injectable for tests
    services/
      password_hasher.py        PasswordHasherService (thread offload + semaphore)
      keystore.py               KeyStore (active signer, published keys, JWKS)
      token_service.py          access token issue/verify, refresh secret helpers
      auth_service.py           signup, login, refresh, logout, me (transactions live here)
    repository/
      users.py                  UserRepository
      refresh_tokens.py         RefreshTokenRepository
    db/
      base.py                   DeclarativeBase, naming convention
      models.py                 User, RefreshToken ORM models
      session.py                engine + async_sessionmaker factory
    jobs/
      cleanup.py                periodic expired-token purge with pg_try_advisory_lock
    scripts/
      wait_for_db.py            retry loop used by entrypoint
      seed_users.py             idempotent demo clinicians
      create_user.py            invite path: create a clinician from the CLI
  tests/
    conftest.py                 test DB, app factory, low-cost argon2
    unit/                       password policy, keystore, token claims, cookie flags
    api/                        signup, login, lockout, refresh rotation, reuse, race, logout, me, jwks
```

Layering rule (HLD-v2 §14): `api` → `services` → `repository` → `db`. Routes never touch SQL; repositories never raise HTTP errors; `domain` has no I/O.

---

## 15. Database design (DDL, indexes, migrations)

### 15.1 ER diagram (refined)

```mermaid
erDiagram
    USERS ||--o{ REFRESH_TOKENS : "has sessions"
    REFRESH_TOKENS ||--o| REFRESH_TOKENS : "replaced_by"
    USERS {
        uuid id PK
        citext email UK
        text password_hash "argon2id encoded"
        text full_name
        text role "clinician only"
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
        uuid family_id "one per sign-in"
        text token_hash UK "sha256 hex, 64 chars"
        timestamptz expires_at "idle expiry"
        timestamptz family_expires_at "absolute cap (R1)"
        timestamptz revoked_at
        text revoked_reason "R2"
        uuid replaced_by_id FK
        text user_agent "truncated to 256"
        timestamptz created_at
    }
```

### 15.2 DDL

This is what `0001_initial.py` produces. Written as SQL here so it can be reviewed and run by hand if needed.

```sql
-- Run as auth_svc in auth_db (citext is created by the init script as superuser, §16.3)
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email               citext      NOT NULL,
    password_hash       text        NOT NULL,
    full_name           text        NOT NULL,
    role                text        NOT NULL DEFAULT 'clinician',
    is_active           boolean     NOT NULL DEFAULT true,
    failed_login_count  integer     NOT NULL DEFAULT 0,
    locked_until        timestamptz NULL,
    last_login_at       timestamptz NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_users_email            UNIQUE (email),
    CONSTRAINT ck_users_email_len        CHECK (char_length(email) BETWEEN 3 AND 254),
    CONSTRAINT ck_users_full_name_len    CHECK (char_length(full_name) BETWEEN 2 AND 120),
    CONSTRAINT ck_users_role             CHECK (role IN ('clinician')),
    CONSTRAINT ck_users_failed_count     CHECK (failed_login_count >= 0),
    CONSTRAINT ck_users_hash_format      CHECK (password_hash LIKE '$argon2id$%')
);

CREATE TABLE refresh_tokens (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id          uuid        NOT NULL,
    token_hash         text        NOT NULL,
    expires_at         timestamptz NOT NULL,
    family_expires_at  timestamptz NOT NULL,
    revoked_at         timestamptz NULL,
    revoked_reason     text        NULL,
    replaced_by_id     uuid        NULL REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    user_agent         text        NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_refresh_tokens_hash      UNIQUE (token_hash),
    CONSTRAINT ck_rt_hash_len              CHECK (char_length(token_hash) = 64),
    CONSTRAINT ck_rt_expiry_order          CHECK (expires_at <= family_expires_at),
    CONSTRAINT ck_rt_revoked_reason        CHECK (
        revoked_reason IS NULL
        OR revoked_reason IN ('rotated', 'logout', 'reuse_detected', 'user_inactive')
    ),
    CONSTRAINT ck_rt_revoked_consistency   CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL)),
    CONSTRAINT ck_rt_user_agent_len        CHECK (user_agent IS NULL OR char_length(user_agent) <= 256)
);

-- Active tokens of a family: used by logout and reuse revocation
CREATE INDEX ix_rt_family_active ON refresh_tokens (family_id) WHERE revoked_at IS NULL;
-- Per-user sessions (future "sign out everywhere", deactivation)
CREATE INDEX ix_rt_user_id      ON refresh_tokens (user_id);
-- Cleanup job
CREATE INDEX ix_rt_expires_at   ON refresh_tokens (expires_at);
```

Migration `0002` adds `users.last_failed_at timestamptz NULL` (time of the latest counted failed attempt, used to decay the counter).

Notes:
- `gen_random_uuid()` is built in from PostgreSQL 13. The app also generates UUIDv4 values itself, so the default is a safety net. Check the container version in §16.1.
- `token_hash` lookups use the unique index created by `uq_refresh_tokens_hash`.
- `updated_at` is set by the ORM (`onupdate=func.now()`), not a trigger, to keep the schema portable and simple.
- The `ck_users_hash_format` check makes it impossible to store a plaintext or wrong-algorithm hash by mistake.

### 15.3 ORM models

```python
# app/db/models.py
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="clinician")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    family_expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None]
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"))
    user_agent: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

All `datetime` columns are `timestamptz` (the `Base` type map sets `datetime → TIMESTAMP(timezone=True)`), and the app always uses timezone-aware UTC values.

### 15.4 Migrations

- `alembic init -t async alembic`, `sqlalchemy.url` comes from `AUTH_DATABASE_URL` in `env.py`, not from `alembic.ini`.
- **Advisory lock** so concurrent container starts do not race:

```python
# alembic/env.py (inside do_run_migrations)
MIGRATION_LOCK_ID = 727_001  # unique per service: auth=727001, patient=727002, ...

def do_run_migrations(connection):
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_ID})
    try:
        context.configure(connection=connection, target_metadata=Base.metadata,
                          compare_type=True, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_ID})
```

- Forward-only in practice. Each revision has a `downgrade()` for local use.
- `0001_initial.py` asserts that `citext` exists and fails with a clear message if the init step (§16.3) was skipped:

```python
def upgrade():
    has_citext = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'citext'")).scalar()
    if not has_citext:
        raise RuntimeError("citext is missing in auth_db. Run infra/postgres/init-auth-db.sh first.")
    # op.create_table(...) for users and refresh_tokens, then indexes, as in §15.2
```

### 15.5 Retention

The cleanup job (§20.8) deletes rows where `expires_at < now() - interval '7 days'` (or `family_expires_at` passed by 7 days). The 7-day tail keeps recent revoked rows available for reuse detection and incident review. Expired tokens are already unusable, so deleting them changes no behavior.

---

## 16. Using the existing Docker Postgres container

HLD-v2 §17.2: "If you reuse your existing Postgres container, run `init-databases.sh` against it once and point each service's `DATABASE_URL` at its own database." This section is the exact procedure for `auth_db`.

> **Important:** scripts in `/docker-entrypoint-initdb.d/` only run when a container starts with an **empty data directory**. An existing container already has data, so mounting the init script into it does nothing. Run the script once with `docker exec` instead, as below.

Placeholders used below: `<pg>` = your container name, `<su>` = its superuser (usually `postgres`, the value of `POSTGRES_USER`).

### 16.1 Inspect the container

```bash
# 1. Find it
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'

# 2. Version (needs >= 13 for built-in gen_random_uuid and trusted citext)
docker exec <pg> psql -U <su> -tAc "SELECT version();"

# 3. Superuser name and published port
docker inspect <pg> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep POSTGRES_USER
docker port <pg> 5432

# 4. Which networks it is on
docker inspect <pg> --format '{{json .NetworkSettings.Networks}}'

# 5. Connection budget
docker exec <pg> psql -U <su> -tAc "SHOW max_connections;"
docker exec <pg> psql -U <su> -tAc "SELECT count(*) FROM pg_stat_activity;"
```

### 16.2 Choose passwords

Add to `.env` (never committed; `.env.example` holds placeholders):

```
AUTH_DB_PW=<long random string>
```

Generate one with `openssl rand -base64 32 | tr -d '/+=' | cut -c1-32`.

### 16.3 Create the role, database and extension (idempotent)

`infra/postgres/init-auth-db.sh` — safe to run any number of times. The full four-service `init-databases.sh` from HLD-v2 §5.1 uses plain `CREATE` statements and fails on a second run; this per-service version is the one to use against a container that already exists.

```bash
#!/usr/bin/env bash
# Usage: AUTH_DB_PW=... ./infra/postgres/init-auth-db.sh <container> [superuser]
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
: "${AUTH_DB_PW:?set AUTH_DB_PW}"

docker exec -i -e AUTH_DB_PW="$AUTH_DB_PW" "$PG_CONTAINER" \
  psql -v ON_ERROR_STOP=1 -v pw="$AUTH_DB_PW" -U "$PG_SU" -d postgres <<'SQL'
-- role (create or reset password)
SELECT format('CREATE ROLE auth_svc LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_svc') \gexec
SELECT format('ALTER ROLE auth_svc WITH LOGIN PASSWORD %L', :'pw') \gexec
ALTER ROLE auth_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- database
SELECT 'CREATE DATABASE auth_db OWNER auth_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'auth_db') \gexec

-- isolation: only auth_svc (and superusers) may connect
REVOKE CONNECT ON DATABASE auth_db FROM PUBLIC;
GRANT  CONNECT ON DATABASE auth_db TO auth_svc;
SQL

docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" -d auth_db <<'SQL'
CREATE EXTENSION IF NOT EXISTS citext;
-- public schema belongs to the db owner; nobody else may create objects in it
ALTER SCHEMA public OWNER TO auth_svc;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL

echo "auth_db ready on $PG_CONTAINER"
```

Optional test database for the API test suite (same container, same isolation):

```bash
docker exec -i <pg> psql -U <su> -d postgres <<'SQL'
SELECT 'CREATE DATABASE auth_db_test OWNER auth_svc TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'auth_db_test') \gexec
REVOKE CONNECT ON DATABASE auth_db_test FROM PUBLIC;
GRANT  CONNECT ON DATABASE auth_db_test TO auth_svc;
SQL
docker exec <pg> psql -U <su> -d auth_db_test -c "CREATE EXTENSION IF NOT EXISTS citext;"
```

This touches nothing that already exists in the container. Existing databases and roles are unchanged.

### 16.4 Networking: how auth-svc reaches the container

**Option A (recommended): put the existing container on the project network.**

```bash
docker network create nephro-net            # once
docker network connect --alias postgres nephro-net <pg>
```

In `docker-compose.yml` declare the network as external and **remove** (or put behind a profile) the `postgres` service so compose does not start a second instance:

```yaml
networks:
  nephro-net:
    external: true

services:
  auth-svc:
    networks: [nephro-net]
    environment:
      AUTH_DATABASE_URL: postgresql+asyncpg://auth_svc:${AUTH_DB_PW}@postgres:5432/auth_db
```

The alias `postgres` keeps the HLD-v2 §17.3 URLs unchanged. Do this once; the attachment survives container restarts (not container re-creation, so re-run `docker network connect` if the container is ever recreated).

**Option B: reach the published host port.** Only if the container cannot join the network.

```yaml
services:
  auth-svc:
    extra_hosts: ["host.docker.internal:host-gateway"]   # needed on Linux
    environment:
      AUTH_DATABASE_URL: postgresql+asyncpg://auth_svc:${AUTH_DB_PW}@host.docker.internal:<published-port>/auth_db
```

**Running auth-svc on the host for development** (Uvicorn outside Docker): use `localhost:<published-port>`. If another server on the host also binds that port (here, host port 5432 is shared with a second Postgres that rejects the `auth_svc` password), use the container's other published port (5433). Check with `netstat -ano | findstr :5432` and test the login with `asyncpg` before debugging anything else.

Because the container is external, compose `depends_on: condition: service_healthy` cannot wait on it. The entrypoint runs `wait_for_db` (§23.2) instead.

### 16.5 Verify isolation and access

```bash
# auth_svc can connect to auth_db
docker exec -e PGPASSWORD="$AUTH_DB_PW" <pg> psql -h localhost -U auth_svc -d auth_db -tAc "SELECT current_user, current_database();"

# a different service role cannot (once patient_svc exists)
docker exec -e PGPASSWORD="$PATIENT_DB_PW" <pg> psql -h localhost -U patient_svc -d auth_db -c "SELECT 1;"
# expected: FATAL: permission denied for database "auth_db"

# extension present
docker exec <pg> psql -U <su> -d auth_db -tAc "SELECT extname FROM pg_extension;"
```

Use `-h localhost` so the connection goes over TCP and exercises password authentication (the official image trusts local socket connections).

### 16.6 Connection budget on the shared instance

| Service | Processes | pool_size + max_overflow | Max connections |
|---|---|---|---|
| auth-svc | 2 workers | 5 + 5 | 20 |
| patient-svc | 2 | 10 + 5 | 30 |
| lab-svc | 2 | 10 + 5 | 30 |
| ai-svc | 2 | 5 + 5 | 20 |
| **Total** | | | **100** |

Default `max_connections` is 100, and the existing container may already have other clients. Either reduce workers or pool sizes, raise `max_connections` on the container, or add PgBouncer when replicas grow (HLD-v2 §13). auth-svc's pool is set by `AUTH_DB_POOL_SIZE` and `AUTH_DB_MAX_OVERFLOW`.

### 16.7 Backup and restore of auth_db only

```bash
docker exec <pg> pg_dump -U <su> -Fc auth_db > backups/auth_db_$(date +%F).dump
docker exec -i <pg> pg_restore -U <su> -d auth_db --clean --if-exists < backups/auth_db_YYYY-MM-DD.dump
```

---

## 17. API specification

All paths are as seen **by auth-svc**. Through the gateway they are prefixed with `/api` (for example `/api/auth/login`). Every error uses the HLD-v2 §12 envelope:

```json
{"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password.", "details": [], "request_id": "req-7f3a2c"}}
```

Token-bearing responses carry `Cache-Control: no-store` and `Pragma: no-cache`.

### 17.1 Endpoint summary

| Method | Path | Auth | Success | Purpose |
|---|---|---|---|---|
| POST | `/auth/signup` | Public (flag) | `201` + cookie | Create clinician and sign in |
| POST | `/auth/login` | Public | `200` + cookie | Sign in |
| POST | `/auth/refresh` | Refresh cookie + Origin check | `200` + rotated cookie | New access token |
| POST | `/auth/logout` | Refresh cookie (optional) + Origin check | `204` + cleared cookie | End this session family |
| GET | `/auth/me` | Bearer JWT | `200` | Current user for the top bar |
| GET | `/.well-known/jwks.json` | Public (internal network) | `200` | Public keys |
| GET | `/health` | None | `200` | Liveness |
| GET | `/ready` | None | `200` / `503` | DB, migrations, key loaded |
| GET | `/metrics` | None (internal) | `200` | Prometheus |

### 17.2 Shared schemas

```python
# app/schemas/auth.py
class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: Literal["clinician"]
    last_login_at: datetime | None

class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int                  # seconds, 900 by default
    user: UserOut
```

### 17.3 `POST /auth/signup`

Request:

```json
{"full_name": "Dr. Priya Sharma", "email": "priya.sharma@clinic.test", "password": "Kidney2026care"}
```

| Field | Rules |
|---|---|
| `full_name` | trimmed, 2–120 chars |
| `email` | valid email, ≤ 254 chars, stored lowercased (citext also compares case-insensitively) |
| `password` | §19.6 policy |

"Confirm password" exists only in the Angular form; the server does not receive it.

Response `201`:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6Ii4uLiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {"id": "1b7c...", "email": "priya.sharma@clinic.test", "full_name": "Dr. Priya Sharma",
           "role": "clinician", "last_login_at": "2026-11-11T18:02:11Z"}
}
```

```
Set-Cookie: nephro_rt=<43-char token>; Max-Age=604800; Path=/api/auth; HttpOnly; Secure; SameSite=Strict
```

Errors: `403 SIGNUP_DISABLED`, `409 EMAIL_TAKEN`, `422 VALIDATION_ERROR` (password rule failures are listed in `details`):

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Password does not meet the rules.",
  "details": [{"field": "password", "code": "TOO_SHORT", "message": "At least 10 characters."},
              {"field": "password", "code": "NEEDS_DIGIT", "message": "Contains a letter and a number."}],
  "request_id": "req-1a2b3c"}}
```

### 17.4 `POST /auth/login`

Request: `{"email": "dr.rao@nephrocare.demo", "password": "Nephro#2026"}`
Response `200`: same body and cookie as signup.

Errors:

| Status | Code | When | Extra |
|---|---|---|---|
| 401 | `INVALID_CREDENTIALS` | Unknown email or wrong password | |
| 429 | `ACCOUNT_LOCKED` | `locked_until > now()` | `Retry-After: <seconds>`; message "Too many failed attempts. Try again in N minutes." |
| 403 | `ACCOUNT_DISABLED` | Correct password but `is_active = false` | |
| 429 | `RATE_LIMITED` | Per-IP bucket empty (also on `/auth/signup`) | `Retry-After: <seconds>` |
| 503 | `SERVICE_BUSY` | Hash queue full for `ARGON2_QUEUE_TIMEOUT_S` | `Retry-After: 1` |
| 422 | `VALIDATION_ERROR` | Malformed body | |

### 17.5 `POST /auth/refresh`

Request: no body. Cookie `nephro_rt` required. If an `Origin` header is present it must be in `CORS_ALLOWED_ORIGINS`.
Response `200`: `TokenOut` with a fresh `user` object, and a new `Set-Cookie` with the rotated token.

| Status | Code | Cookie action | Client action |
|---|---|---|---|
| 401 | `REFRESH_MISSING` | none | Go to sign-in |
| 401 | `REFRESH_INVALID` | clear | Go to sign-in |
| 401 | `REFRESH_EXPIRED` | clear | Go to sign-in, message "Your session expired." |
| 401 | `REFRESH_REUSED` | clear | Go to sign-in, message "You were signed out for security. Please sign in again." |
| 409 | `REFRESH_RACE` | **none** | Retry `/auth/refresh` once |
| 403 | `ORIGIN_NOT_ALLOWED` | none | Bug or attack; log |

### 17.6 `POST /auth/logout`

Request: no body; cookie optional. Response `204`, always (idempotent), with:

```
Set-Cookie: nephro_rt=""; Max-Age=0; Path=/api/auth; HttpOnly; Secure; SameSite=Strict
```

If the cookie maps to a token, every active token in its family is revoked with reason `logout`. The access token remains valid until it expires (ADR-A3); Angular drops it from memory immediately.

### 17.7 `GET /auth/me`

Header: `Authorization: Bearer <access token>`.
Response `200`: `UserOut`.
Errors: `401 UNAUTHENTICATED` (missing or invalid token), `401 TOKEN_EXPIRED`, `403 ACCOUNT_DISABLED`, `404 NOT_FOUND` (user row gone; should never happen because users are not deleted).

### 17.8 `GET /.well-known/jwks.json`

```json
{
  "keys": [
    {"kty": "RSA", "use": "sig", "alg": "RS256",
     "kid": "Jd5c9pV3mYxq2xH2kZK3o4q8b8z9xFh1k3wq7mQ1sC0",
     "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4...",
     "e": "AQAB"}
  ]
}
```

`Cache-Control: public, max-age=300`. During rotation it lists two keys (§26.2). Consumers reach it on the private network at `JWKS_URL=http://auth-svc:8000/.well-known/jwks.json`; the gateway does not need to expose it publicly.

### 17.9 Access token format

Header:

```json
{"alg": "RS256", "typ": "JWT", "kid": "Jd5c9pV3mYxq2xH2kZK3o4q8b8z9xFh1k3wq7mQ1sC0"}
```

Payload:

```json
{
  "iss": "nephro-auth",
  "aud": "nephro-api",
  "sub": "1b7c6d3e-8a0f-4c55-9a7e-1f2d3c4b5a69",
  "role": "clinician",
  "iat": 1762884131,
  "nbf": 1762884131,
  "exp": 1762885031,
  "jti": "5f0c7e7b0f9b4a6d9d1f2a3b4c5d6e7f"
}
```

No name, email or other PII in the token. The display name comes from `/auth/me` or the `user` object in the login response.

### 17.10 `GET /ready`

`200 {"status": "ready", "db": "ok", "migrations": "head", "signing_key": "Jd5c9p..."}` or `503` with the failing check named. Checks: `SELECT 1`, `alembic_version` equals the code's head revision, a signing key is loaded.

---

## 18. Error codes

| HTTP | Code | Message shown to the user (prototype copy where it exists) |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | Invalid email or password. |
| 429 | `ACCOUNT_LOCKED` | Too many failed attempts. Try again in N minutes. |
| 403 | `ACCOUNT_DISABLED` | This account has been deactivated. Contact your clinic's support. |
| 403 | `SIGNUP_DISABLED` | Public signup is turned off. Ask for an invitation. |
| 409 | `EMAIL_TAKEN` | An account with this email already exists. |
| 422 | `VALIDATION_ERROR` | Field-level messages in `details` |
| 401 | `REFRESH_MISSING` | (silent, go to sign-in) |
| 401 | `REFRESH_INVALID` | Your session has ended. Please sign in again. |
| 401 | `REFRESH_EXPIRED` | Your session expired. Please sign in again. |
| 401 | `REFRESH_REUSED` | You were signed out for security. Please sign in again. |
| 409 | `REFRESH_RACE` | (silent, client retries once) |
| 403 | `ORIGIN_NOT_ALLOWED` | Request blocked. |
| 401 | `UNAUTHENTICATED` | Please sign in. |
| 401 | `TOKEN_EXPIRED` | (silent, interceptor refreshes) |
| 404 | `NOT_FOUND` | Not found. |
| 503 | `NOT_READY` | Service unavailable. |
| 429 | `RATE_LIMITED` | Too many requests. Please slow down. |
| 503 | `SERVICE_BUSY` | The service is busy. Please retry shortly. |
| 500 | `INTERNAL_ERROR` | Something went wrong. Reference: `request_id` |

Password rule `details[].code` values: `TOO_SHORT`, `TOO_LONG`, `NEEDS_LETTER`, `NEEDS_DIGIT`, `TOO_COMMON`, `CONTAINS_EMAIL`.

---

## 19. Detailed flows and algorithms

### 19.1 Signup

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant GW as Gateway
    participant A as auth-svc
    participant H as Argon2 (thread pool)
    participant DB as auth_db
    UI->>GW: POST /api/auth/signup {full_name, email, password}
    GW->>GW: rate limit (strict bucket), request-id, public path
    GW->>A: POST /auth/signup
    A->>A: ENABLE_PUBLIC_SIGNUP? else 403 SIGNUP_DISABLED
    A->>A: Pydantic validation, password policy → 422 with rule codes
    A->>H: hash(password) under semaphore
    H-->>A: $argon2id$...
    A->>DB: BEGIN
    A->>DB: INSERT users (... role='clinician')
    alt unique violation on email
        DB-->>A: IntegrityError
        A->>DB: ROLLBACK
        A-->>UI: 409 EMAIL_TAKEN
    else inserted
        A->>DB: UPDATE users SET last_login_at = now()
        A->>DB: INSERT refresh_tokens (new family)
        A->>DB: COMMIT
        A->>A: sign access token (RS256, kid)
        A-->>GW: 201 TokenOut + Set-Cookie nephro_rt
        GW-->>UI: 201 (Set-Cookie passed through)
    end
```

Hashing happens **before** the transaction opens, so no DB connection is held during the slow hash.

### 19.2 Login (attempt reservation and lockout)

The old design read `locked_until`, verified the password, and only then recorded the failure. N parallel
guesses all passed the lock check, so N passwords were tried instead of 5, and a correct guess inside the
burst could log in even after the account had locked. An **attempt is now reserved atomically before the
password is verified.**

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant A as auth-svc
    participant H as Argon2
    participant DB as nephro_auth_db
    UI->>A: POST /auth/login {email, password}
    A->>DB: SELECT * FROM users WHERE email = :email
    alt user missing
        A->>H: verify(dummy_hash, password)
        A-->>UI: 401 INVALID_CREDENTIALS
    else locked_until > now (fast path, no hashing)
        A-->>UI: 429 ACCOUNT_LOCKED + Retry-After (401 if LOCKOUT_REVEAL=false)
    else
        A->>DB: reserve attempt (one atomic UPDATE)
        alt no row: locked meanwhile, or all attempts taken by in-flight requests
            A->>DB: lock account if not already locked (idempotent)
            A-->>UI: 429 ACCOUNT_LOCKED (password NOT verified)
        else attempt reserved
            A->>H: verify(user.password_hash, password)  (waits at most ARGON2_QUEUE_TIMEOUT_S)
            alt hash queue full
                A->>DB: release the reserved attempt
                A-->>UI: 503 SERVICE_BUSY + Retry-After: 1
            else wrong password
                opt this was the last allowed attempt
                    A->>DB: lock_out (locked_until = now + 15 min, counter = 0)
                end
                A-->>UI: 401 INVALID_CREDENTIALS
            else correct, inactive
                A->>DB: release the reserved attempt
                A-->>UI: 403 ACCOUNT_DISABLED
            else correct, active
                A->>DB: BEGIN; SELECT user FOR UPDATE
                alt locked_until > now (another request locked it meanwhile)
                    A-->>UI: 429 ACCOUNT_LOCKED
                else
                    A->>DB: reset counter, clear lock and last_failed_at, set last_login_at, maybe new hash; INSERT refresh_tokens; COMMIT
                    A-->>UI: 200 TokenOut + Set-Cookie
                end
            end
        end
    end
```

**Reservation** (one statement checks and consumes an attempt; failures older than
`LOGIN_FAILURE_WINDOW_MINUTES` no longer count, because the `CASE` resets the counter first):

```sql
UPDATE users
SET failed_login_count = (CASE WHEN last_failed_at IS NOT NULL AND last_failed_at < :now - make_interval(mins => :window)
                               THEN 0 ELSE failed_login_count END) + 1,
    last_failed_at = :now, updated_at = :now
WHERE id = :user_id
  AND (locked_until IS NULL OR locked_until <= :now)
  AND (CASE WHEN last_failed_at IS NOT NULL AND last_failed_at < :now - make_interval(mins => :window)
            THEN 0 ELSE failed_login_count END) < :max_attempts
RETURNING failed_login_count;
```

**Lock** (idempotent: only the request that actually flips the account gets a row back):

```sql
UPDATE users
SET locked_until = :now + make_interval(mins => :lock_minutes), failed_login_count = 0, updated_at = :now
WHERE id = :user_id AND (locked_until IS NULL OR locked_until <= :now)
RETURNING locked_until;
```

`:now` comes from the injected clock (§20.6), never from SQL `now()`, so lockout expiry and failure decay
can be tested with a fake clock. The same applies to every timestamp the service writes.

Rules:
- A locked account is rejected **before** password verification, so guessing during the lock gives no signal and costs no CPU.
- Only `LOGIN_MAX_ATTEMPTS` (5) passwords can ever reach argon2 per lock cycle, however many requests run in parallel.
- The 5th failure locks the account and still returns `401`; the next attempt sees `429` (matches the prototype).
- A correct password can never succeed after `locked_until` was set: the success path re-reads the user `FOR UPDATE` and rejects as locked.
- A successful login resets `failed_login_count` to 0 and clears `locked_until` and `last_failed_at`.
- Failures older than `LOGIN_FAILURE_WINDOW_MINUTES` (15) stop counting: 4 failures, 16 minutes, 1 failure does not lock.
- A reserved attempt that was never judged (hash queue full, or a correct password on a disabled account) is given back, so load cannot push a user toward lockout.
- With `LOCKOUT_REVEAL=false`, a locked account returns the same `401 INVALID_CREDENTIALS`.

### 19.3 Refresh (rotation, reuse detection, race window)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Angular
    participant A as auth-svc
    participant DB as auth_db
    UI->>A: POST /auth/refresh (Cookie nephro_rt=RT)
    A->>A: Origin check; cookie present? else 401 REFRESH_MISSING
    A->>DB: BEGIN
    A->>DB: SELECT ... FROM refresh_tokens WHERE token_hash = sha256(RT) FOR UPDATE
    alt no row
        A->>DB: COMMIT
        A-->>UI: 401 REFRESH_INVALID, clear cookie
    else revoked, reason is not rotated (logout, reuse_detected, user_inactive)
        A->>DB: COMMIT (nothing changed)
        A->>A: log auth.refresh.failure reason=invalid (no reuse alert)
        A-->>UI: 401 REFRESH_INVALID, clear cookie
    else revoked as rotated within grace window
        A->>DB: COMMIT
        A-->>UI: 409 REFRESH_RACE, cookie untouched
    else revoked as rotated, outside grace window
        A->>DB: UPDATE refresh_tokens SET revoked_at=now(), revoked_reason='reuse_detected' WHERE family_id=:f AND revoked_at IS NULL
        A->>DB: COMMIT
        A->>A: log security event auth.refresh.reuse_detected
        A-->>UI: 401 REFRESH_REUSED, clear cookie
    else expired (idle or absolute)
        A->>DB: COMMIT
        A-->>UI: 401 REFRESH_EXPIRED, clear cookie
    else user inactive
        A->>DB: revoke family (user_inactive); COMMIT
        A-->>UI: 401 REFRESH_INVALID, clear cookie
    else valid
        A->>DB: INSERT new token (same family, expires_at = min(now+7d, family_expires_at))
        A->>DB: UPDATE old SET revoked_at=now(), revoked_reason='rotated', replaced_by_id=new.id
        A->>DB: COMMIT
        A-->>UI: 200 TokenOut + Set-Cookie (new RT)
    end
```

Implementation notes:
- `FOR UPDATE` serializes two concurrent refreshes of the **same** token. The second waits, then sees `revoked_reason='rotated'` and a fresh `revoked_at`, so it gets `409 REFRESH_RACE`.
- **Revocation must commit even though the response is an error.** The service method decides an *outcome* inside the transaction and raises the HTTP error **after** the `async with session.begin()` block. Raising inside the block would roll the revocation back. See §20.6.
- **Only a replayed `rotated` token is theft.** A token revoked by `logout`, `reuse_detected` or `user_inactive` marks a session that is already over (a double sign-out, a second tab, a client retry). It answers `401 REFRESH_INVALID`, clears the cookie, logs `auth.refresh.failure reason=invalid`, and does **not** touch the family or log `reuse_detected`, so the alert only fires for a genuinely stolen, rotated-away token.
- The race window only answers `409`; it never issues a token. A thief replaying within 10 s gains nothing, and after 10 s the replay revokes the family.

### 19.4 Logout

1. Origin check.
2. If the cookie is present, look up its row by hash. If found, revoke every active token in that family with reason `logout`.
3. Commit, clear the cookie, return `204`. Missing, unknown or already revoked cookies also get `204`.

### 19.5 Me

1. `current_claims` dependency verifies the bearer token with the **local** `KeyStore` public keys (no HTTP to itself), pinning `RS256`, `iss`, `aud`, requiring `exp`, `iat`, `sub`, leeway 30 s.
2. Load the user by `sub`. If inactive → `403 ACCOUNT_DISABLED`.
3. Return `UserOut`.

### 19.6 Password policy (pure function)

```python
# app/domain/password_policy.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Violation:
    code: str
    message: str

MIN_LEN, MAX_LEN = 10, 128

def check_password(password: str, email: str, common: frozenset[str]) -> list[Violation]:
    v: list[Violation] = []
    if len(password) < MIN_LEN:
        v.append(Violation("TOO_SHORT", "At least 10 characters."))
    if len(password) > MAX_LEN:
        v.append(Violation("TOO_LONG", "At most 128 characters."))
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not has_letter:
        v.append(Violation("NEEDS_LETTER", "Contains a letter and a number."))
    if not has_digit:
        v.append(Violation("NEEDS_DIGIT", "Contains a letter and a number."))
    if password.lower() in common:
        v.append(Violation("TOO_COMMON", "Not a commonly used password."))
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in password.lower():
        v.append(Violation("CONTAINS_EMAIL", "Must not contain your email name."))
    return v
```

The Angular form shows the same three rules live (prototype `pw-rules`). The server is authoritative.

### 19.7 Refresh cookie

| Attribute | Value | Why |
|---|---|---|
| Name | `nephro_rt` (`REFRESH_COOKIE_NAME`) | |
| Value | `secrets.token_urlsafe(32)` | 256 bits |
| `HttpOnly` | yes | Not readable by JS |
| `Secure` | `COOKIE_SECURE` (true by default) | Browsers treat `http://localhost` as a secure context, so `Secure` cookies still work in local dev |
| `SameSite` | `Strict` | Never sent on cross-site requests. `localhost:4200` and `localhost:8080` are the same site (ports are ignored for "site") |
| `Path` | `/api/auth` (`REFRESH_COOKIE_PATH`) | Path as the **browser** sees it (through the gateway), so the cookie is never sent to clinical endpoints |
| `Domain` | not set | Host-only cookie |
| `Max-Age` | seconds until the new token's `expires_at` | |

---

## 20. Component design (classes and key code)

### 20.1 Class overview

```mermaid
classDiagram
    class AuthService {
        +signup(SignupIn, user_agent) SessionResult
        +login(LoginIn, user_agent) SessionResult
        +refresh(raw_token, user_agent) SessionResult
        +logout(raw_token) None
        +me(user_id) User
        -_start_session(session, user, user_agent) str
    }
    class PasswordHasherService {
        +hash(pw) str
        +verify(hash, pw) bool
        +verify_dummy(pw) None
        +needs_rehash(hash) bool
    }
    class TokenService {
        +issue_access_token(user) AccessToken
        +verify_access_token(token) Claims
        +new_refresh_secret() tuple
        +hash_refresh(raw) str
    }
    class KeyStore {
        +active SigningKey
        +public_keys dict
        +jwks() dict
        +public_key_for(kid) RSAPublicKey
    }
    class UserRepository {
        +get_by_email(s, email) User
        +get(s, id) User
        +add(s, user) None
        +register_failure(s, id, max, minutes) datetime
        +register_success(s, user, new_hash) None
    }
    class RefreshTokenRepository {
        +get_by_hash_for_update(s, h) RefreshToken
        +add(s, token) None
        +revoke_family(s, family_id, reason, now) int
        +delete_expired(s, before) int
    }
    AuthService --> PasswordHasherService
    AuthService --> TokenService
    AuthService --> UserRepository
    AuthService --> RefreshTokenRepository
    TokenService --> KeyStore
```

`SessionResult = (user, access_token, expires_in, raw_refresh, refresh_expires_at)`.

### 20.2 App factory and lifespan

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.service_name, s.log_level)
    app.state.keystore = KeyStore.from_files(s.jwt_private_key_path, s.jwt_additional_public_key_paths)
    app.state.hasher = PasswordHasherService(s)          # creates semaphore inside the running loop
    app.state.common_passwords = load_common_passwords()
    app.state.engine = create_engine(s)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    cleanup = asyncio.create_task(run_cleanup_forever(app.state.sessionmaker, s))
    try:
        yield
    finally:
        cleanup.cancel()
        await app.state.engine.dispose()

def create_app() -> FastAPI:
    app = FastAPI(title="auth-svc", version="1.0.0", lifespan=lifespan)
    install_common_middleware(app)          # libs/common: request id, access log, error envelope
    app.include_router(routes_auth.router, prefix="/auth", tags=["auth"])
    app.include_router(routes_wellknown.router)
    app.include_router(routes_health.router)
    mount_metrics(app)
    return app

app = create_app()
```

CORS is **not** configured in auth-svc; the gateway owns CORS (HLD-v2 §8). auth-svc only performs the Origin check on cookie endpoints.

### 20.3 Engine

```python
# app/db/session.py
def create_engine(s: Settings) -> AsyncEngine:
    return create_async_engine(
        s.auth_database_url,
        pool_size=s.auth_db_pool_size,
        max_overflow=s.auth_db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"timeout": 3, "server_settings": {"application_name": "auth-svc"}},
    )
```

`application_name` makes auth-svc connections easy to spot in `pg_stat_activity` on the shared container.

### 20.4 Password hasher

```python
# app/services/password_hasher.py
import asyncio, secrets
import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

class PasswordHasherService:
    def __init__(self, s: Settings):
        self._ph = PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib,
                                  parallelism=s.argon2_parallelism, type=Type.ID)
        self._sem = asyncio.Semaphore(s.argon2_max_concurrency)   # bulkhead on memory and CPU
        self._dummy = self._ph.hash(secrets.token_urlsafe(24))

    async def hash(self, password: str) -> str:
        async with self._sem:
            return await anyio.to_thread.run_sync(self._ph.hash, password)

    async def verify(self, encoded: str, password: str) -> bool:
        async with self._sem:
            try:
                return await anyio.to_thread.run_sync(self._ph.verify, encoded, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False

    async def verify_dummy(self, password: str) -> None:
        await self.verify(self._dummy, password)      # equalize timing for unknown emails

    def needs_rehash(self, encoded: str) -> bool:
        return self._ph.check_needs_rehash(encoded)
```

Argon2 is CPU-bound and would block the event loop; running it in a worker thread keeps refresh, me and JWKS responsive while a login is hashing.

### 20.5 KeyStore and TokenService

```python
# app/services/keystore.py
import base64, hashlib, json
from dataclasses import dataclass
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

def _jwk(pub: RSAPublicKey) -> dict:
    nums = pub.public_numbers()
    return {"kty": "RSA", "n": _b64u_uint(nums.n), "e": _b64u_uint(nums.e)}

def thumbprint_kid(pub: RSAPublicKey) -> str:
    jwk = _jwk(pub)
    canonical = json.dumps({"e": jwk["e"], "kty": "RSA", "n": jwk["n"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()

@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: RSAPrivateKey

class KeyStore:
    def __init__(self, active: SigningKey, published: dict[str, RSAPublicKey]):
        self.active = active
        self.published = published            # kid -> public key, includes the active key

    @classmethod
    def from_files(cls, private_path: str, extra_public_paths: list[str]) -> "KeyStore":
        with open(private_path, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
        if priv.key_size < 2048:
            raise RuntimeError("JWT signing key must be at least 2048 bits")
        pub = priv.public_key()
        published = {thumbprint_kid(pub): pub}
        for p in extra_public_paths:
            with open(p, "rb") as f:
                k = serialization.load_pem_public_key(f.read())
            published[thumbprint_kid(k)] = k
        return cls(SigningKey(thumbprint_kid(pub), priv), published)

    def jwks(self) -> dict:
        return {"keys": [{**_jwk(k), "use": "sig", "alg": "RS256", "kid": kid}
                         for kid, k in self.published.items()]}
```

```python
# app/services/token_service.py
import hashlib, secrets, time, uuid
import jwt

class TokenService:
    def __init__(self, keys: KeyStore, s: Settings):
        self._keys, self._s = keys, s

    def issue_access_token(self, user) -> tuple[str, int]:
        now = int(time.time())
        ttl = self._s.access_token_ttl_min * 60
        claims = {"iss": self._s.jwt_issuer, "aud": self._s.jwt_audience, "sub": str(user.id),
                  "role": user.role, "iat": now, "nbf": now, "exp": now + ttl,
                  "jti": uuid.uuid4().hex}
        token = jwt.encode(claims, self._keys.active.private_key, algorithm="RS256",
                           headers={"kid": self._keys.active.kid, "typ": "JWT"})
        return token, ttl

    def verify_access_token(self, token: str) -> dict:
        kid = jwt.get_unverified_header(token).get("kid")
        key = self._keys.published.get(kid)
        if key is None:
            raise Unauthenticated("Unknown signing key")
        return jwt.decode(token, key, algorithms=["RS256"], audience=self._s.jwt_audience,
                          issuer=self._s.jwt_issuer, leeway=30,
                          options={"require": ["exp", "iat", "sub", "iss", "aud"]})

    @staticmethod
    def new_refresh_secret() -> tuple[str, str]:
        raw = secrets.token_urlsafe(32)
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def hash_refresh(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()
```

`jwt.decode` errors map to `401 TOKEN_EXPIRED` (`ExpiredSignatureError`) or `401 UNAUTHENTICATED` (everything else).

### 20.6 AuthService (transactions and outcomes)

```python
# app/services/auth_service.py (core parts)
from enum import Enum, auto

class RefreshOutcome(Enum):
    OK = auto(); INVALID = auto(); EXPIRED = auto(); REUSED = auto(); RACE = auto()

class AuthService:
    def __init__(self, sm, users, tokens_repo, hasher, tokens, s, common, clock):
        ...

    async def login(self, data: LoginIn, user_agent: str | None) -> SessionResult:
        now = self._clock()
        async with self._sm() as session:
            user = await self._users.get_by_email(session, data.email)

        if user and user.locked_until and user.locked_until > now:
            if self._s.lockout_reveal:
                raise AccountLocked(retry_after=int((user.locked_until - now).total_seconds()) + 1)
            raise InvalidCredentials()

        if user is None:
            await self._hasher.verify_dummy(data.password)
            raise InvalidCredentials()

        if not await self._hasher.verify(user.password_hash, data.password):
            async with self._sm() as session, session.begin():
                await self._users.register_failure(session, user.id,
                                                   self._s.login_max_attempts,
                                                   self._s.login_lock_minutes)
            raise InvalidCredentials()

        if not user.is_active:
            raise AccountDisabled()

        new_hash = (await self._hasher.hash(data.password)
                    if self._hasher.needs_rehash(user.password_hash) else None)

        async with self._sm() as session, session.begin():
            user = await self._users.get(session, user.id)
            await self._users.register_success(session, user, new_hash, now)
            raw, rt_exp = await self._start_session(session, user, user_agent, now)
        access, ttl = self._tokens.issue_access_token(user)
        return SessionResult(user, access, ttl, raw, rt_exp)

    async def refresh(self, raw: str, user_agent: str | None) -> SessionResult:
        now = self._clock()
        outcome, user, new_raw, new_exp = RefreshOutcome.INVALID, None, None, None

        async with self._sm() as session, session.begin():
            row = await self._rt.get_by_hash_for_update(session, self._tokens.hash_refresh(raw))
            if row is None:
                outcome = RefreshOutcome.INVALID
            elif row.revoked_at is not None:
                if row.revoked_reason != "rotated":
                    outcome = RefreshOutcome.INVALID          # session already over: not theft, change nothing
                elif (now - row.revoked_at).total_seconds() <= self._s.refresh_reuse_grace_s:
                    outcome = RefreshOutcome.RACE
                else:
                    await self._rt.revoke_family(session, row.family_id, "reuse_detected", now)
                    outcome = RefreshOutcome.REUSED
            elif row.expires_at <= now or row.family_expires_at <= now:
                outcome = RefreshOutcome.EXPIRED
            else:
                user = await self._users.get(session, row.user_id)
                if user is None or not user.is_active:
                    await self._rt.revoke_family(session, row.family_id, "user_inactive", now)
                    outcome = RefreshOutcome.INVALID
                else:
                    new_raw, new_hash = self._tokens.new_refresh_secret()
                    new_exp = min(now + timedelta(days=self._s.refresh_token_ttl_days),
                                  row.family_expires_at)
                    new = RefreshToken(id=uuid4(), user_id=user.id, family_id=row.family_id,
                                       token_hash=new_hash, expires_at=new_exp,
                                       family_expires_at=row.family_expires_at,
                                       user_agent=_trim(user_agent))
                    await self._rt.add(session, new)              # flush, so new.id exists
                    row.revoked_at, row.revoked_reason, row.replaced_by_id = now, "rotated", new.id
                    outcome = RefreshOutcome.OK
        # transaction committed here, including any family revocation

        if outcome is RefreshOutcome.OK:
            access, ttl = self._tokens.issue_access_token(user)
            return SessionResult(user, access, ttl, new_raw, new_exp)
        if outcome is RefreshOutcome.REUSED:
            log_security_event("auth.refresh.reuse_detected", family_id=str(row.family_id),
                               user_id=str(row.user_id))
        raise {RefreshOutcome.INVALID: RefreshInvalid, RefreshOutcome.EXPIRED: RefreshExpired,
               RefreshOutcome.REUSED: RefreshReused, RefreshOutcome.RACE: RefreshRace}[outcome]()

    async def _start_session(self, session, user, user_agent, now) -> tuple[str, datetime]:
        raw, h = self._tokens.new_refresh_secret()
        family_exp = now + timedelta(days=self._s.session_max_days)
        exp = min(now + timedelta(days=self._s.refresh_token_ttl_days), family_exp)
        await self._rt.add(session, RefreshToken(id=uuid4(), user_id=user.id, family_id=uuid4(),
                                                 token_hash=h, expires_at=exp,
                                                 family_expires_at=family_exp,
                                                 user_agent=_trim(user_agent)))
        return raw, exp
```

### 20.7 Routes and cookie helpers

```python
# app/api/cookies.py
def set_refresh_cookie(resp: Response, raw: str, expires_at: datetime, s: Settings) -> None:
    max_age = max(0, int((expires_at - utcnow()).total_seconds()))
    resp.set_cookie(s.refresh_cookie_name, raw, max_age=max_age, path=s.refresh_cookie_path,
                    secure=s.cookie_secure, httponly=True, samesite="strict")

def clear_refresh_cookie(resp: Response, s: Settings) -> None:
    resp.delete_cookie(s.refresh_cookie_name, path=s.refresh_cookie_path,
                       secure=s.cookie_secure, httponly=True, samesite="strict")
```

```python
# app/api/deps.py (Origin check)
async def require_trusted_origin(request: Request, s: Settings = Depends(get_settings)) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in s.cors_allowed_origins:
        raise OriginNotAllowed()
```

```python
# app/api/routes_auth.py (excerpt)
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response,
                svc: AuthService = Depends(get_auth_service), s: Settings = Depends(get_settings)):
    r = await svc.login(body, request.headers.get("user-agent"))
    set_refresh_cookie(response, r.raw_refresh, r.refresh_expires_at, s)
    response.headers.update(NO_STORE)
    return TokenOut(access_token=r.access_token, expires_in=r.expires_in, user=UserOut.of(r.user))

@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(require_trusted_origin)])
async def refresh(request: Request, response: Response,
                  svc: AuthService = Depends(get_auth_service), s: Settings = Depends(get_settings)):
    raw = request.cookies.get(s.refresh_cookie_name)
    if not raw:
        raise RefreshMissing()
    try:
        r = await svc.refresh(raw, request.headers.get("user-agent"))
    except (RefreshInvalid, RefreshExpired, RefreshReused) as e:
        raise e.with_cookie_clear()          # error handler adds a clearing Set-Cookie
    set_refresh_cookie(response, r.raw_refresh, r.refresh_expires_at, s)
    response.headers.update(NO_STORE)
    return TokenOut(access_token=r.access_token, expires_in=r.expires_in, user=UserOut.of(r.user))
```

`with_cookie_clear()` sets a flag on the `AppError`; the auth-svc error handler adds the clearing `Set-Cookie` header to the error response. `RefreshRace` deliberately does not clear.

### 20.8 Cleanup job

```python
# app/jobs/cleanup.py
CLEANUP_LOCK_ID = 727_101

async def run_cleanup_forever(sm, s: Settings) -> None:
    while True:
        try:
            async with sm() as session, session.begin():
                got = (await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                             {"k": CLEANUP_LOCK_ID})).scalar()
                if got:                                   # only one replica does the work
                    n = await RefreshTokenRepository().delete_expired(
                        session, before=utcnow() - timedelta(days=s.refresh_retention_days))
                    log.info("auth.cleanup.done", extra={"deleted": n})
        except Exception:
            log.exception("auth.cleanup.failed")
        await asyncio.sleep(s.cleanup_interval_s)
```

The transaction-scoped advisory lock releases itself on commit, so a crashed replica never holds it.

### 20.9 Scripts

- `seed_users.py`: inserts `dr.rao@nephrocare.demo` (Dr. Anita Rao) and `dr.malhotra@nephrocare.demo` (Dr. Karan Malhotra) with password `Nephro#2026` using `INSERT ... ON CONFLICT (email) DO NOTHING`. Runs only when `SEED_DEMO_USERS=true`. The prototype's `admin@nephrocare.demo` is **not** seeded (ADR-018).
- `create_user.py --email ... --name ...`: prompts for the password twice (no echo), applies the same policy, inserts the user. This is the production "invite" path when `ENABLE_PUBLIC_SIGNUP=false`.
- `wait_for_db.py`: tries `SELECT 1` up to `DB_WAIT_ATTEMPTS` times with a 2 s pause, then exits non-zero.

---

## 21. Configuration

All settings come from environment variables (12-factor, HLD-v2 §12). Defaults are safe for local development.

| Variable | Default | Purpose |
|---|---|---|
| `SERVICE_NAME` | `auth-svc` | Logs and metrics label |
| `LOG_LEVEL` | `INFO` | |
| `AUTH_DATABASE_URL` | (required) | `postgresql+asyncpg://auth_svc:***@postgres:5432/auth_db` |
| `AUTH_DB_POOL_SIZE` | `5` | Per process |
| `AUTH_DB_MAX_OVERFLOW` | `5` | Per process |
| `DB_WAIT_ATTEMPTS` | `30` | Entrypoint DB wait |
| `JWT_ISSUER` | `nephro-auth` | `iss` |
| `JWT_AUDIENCE` | `nephro-api` | `aud` |
| `JWT_PRIVATE_KEY_PATH` | `/run/secrets/jwt_private` | Active signing key (RSA ≥ 2048, PEM, unencrypted) |
| `JWT_ADDITIONAL_PUBLIC_KEY_PATHS` | empty | Comma-separated PEM public keys to keep publishing during rotation |
| `ACCESS_TOKEN_TTL_MIN` | `15` | |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | Idle expiry |
| `SESSION_MAX_DAYS` | `30` | Absolute cap per sign-in (R1) |
| `REFRESH_REUSE_GRACE_S` | `10` | Race window (R3) |
| `REFRESH_RETENTION_DAYS` | `7` | Cleanup tail |
| `CLEANUP_INTERVAL_S` | `3600` | |
| `REFRESH_COOKIE_NAME` | `nephro_rt` | |
| `REFRESH_COOKIE_PATH` | `/api/auth` | Browser-visible path |
| `COOKIE_SECURE` | `true` | |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:4200` | Used for the Origin check (the gateway uses the same list for CORS) |
| `ENABLE_PUBLIC_SIGNUP` | `true` | Demo on, production off |
| `LOGIN_MAX_ATTEMPTS` | `5` | |
| `LOGIN_LOCK_MINUTES` | `15` | |
| `LOCKOUT_REVEAL` | `true` | `false` returns `401` while locked (R8) |
| `LOGIN_FAILURE_WINDOW_MINUTES` | `15` | Failures older than this stop counting toward lockout (R10) |
| `RATE_LIMIT_ENABLED` | `true` | In-process per-IP limiter on login and signup (R11) |
| `RATE_LIMIT_LOGIN_PER_MIN` | `10` | Sustained refill rate per IP, per worker process |
| `RATE_LIMIT_LOGIN_BURST` | `5` | Bucket size: requests allowed back-to-back from a cold start |
| `ARGON2_QUEUE_TIMEOUT_S` | `2.0` | Max wait for a hash slot before `503 SERVICE_BUSY` |
| `ENVIRONMENT` | `development` | `development` / `test` / `production`; production enables the startup guard (R12) |
| `ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION` | `false` | Explicit opt-in needed to run with `ENABLE_PUBLIC_SIGNUP=true` in production |
| `ARGON2_TIME_COST` | `3` | |
| `ARGON2_MEMORY_KIB` | `65536` | 64 MiB |
| `ARGON2_PARALLELISM` | `4` | |
| `ARGON2_MAX_CONCURRENCY` | `4` | Concurrent hashes per process |
| `SEED_DEMO_USERS` | `false` | `true` in local compose |
| `UVICORN_WORKERS` | `2` | |

`.env.example` additions:

```
# auth-svc
AUTH_DB_PW=change-me
# Compose sets AUTH_DATABASE_URL in the service's environment: block (§23.3).
# This line is only for running auth-svc on the host; use the container's published port.
AUTH_DATABASE_URL=postgresql+asyncpg://auth_svc:change-me@localhost:5432/auth_db
ENABLE_PUBLIC_SIGNUP=true
SEED_DEMO_USERS=true
COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=http://localhost:4200
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private
```

---

## 22. Contracts with the gateway, other services and Angular

### 22.1 Gateway (HLD-v2 §8)

| Item | Requirement |
|---|---|
| Routing | `/api/auth/*` → `http://auth-svc:8000/auth/*` (strip `/api`) |
| Public paths (no JWT check) | `/api/auth/login`, `/api/auth/signup`, `/api/auth/refresh`, `/api/auth/logout` |
| JWT-checked | `/api/auth/me` |
| Cookies | Forward the request `Cookie` header unchanged. Forward **every** `Set-Cookie` response header unchanged (do not merge or drop). Do not cache any `/api/auth/*` response |
| Rate limits | Strict per-IP bucket on `/login` and `/signup` (for example 10 per minute); moderate on `/refresh` (for example 60 per minute per IP) |
| Timeouts | 5 s default is enough (argon2 is well under a second) |
| CORS | Allow-list the Angular origin with `credentials: true` (needed only if the SPA calls the gateway cross-origin; see §22.3) |
| Errors | Connection error or timeout → `502` / `504` in the standard envelope |
| JWKS | Fetch `JWKS_URL` at startup, cache 5 min, refetch on unknown `kid` at most once per 30 s, keep old keys if the fetch fails |

### 22.2 Other services (verifiers)

Use the shared `libs/common/jwt.py` verifier with exactly these options:

```python
jwt.decode(token, key_for_kid, algorithms=["RS256"], audience="nephro-api", issuer="nephro-auth",
           leeway=30, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
```

Then `require_role("clinician")`. Never trust `X-User-Id` or similar headers. Store `sub` as `created_by` / `clinician_id` (UUID, no FK).

### 22.3 Angular

| Concern | Behavior |
|---|---|
| Same-origin in dev | Use the Angular dev-server proxy so `/api` → `http://localhost:8080`. Calls are then same-origin and the cookie path `/api/auth` matches without CORS. If calling the gateway directly cross-origin, set `withCredentials: true` on `/api/auth/*` calls |
| Token storage | Access token in a signal in `AuthService`; never localStorage or sessionStorage |
| App boot | `provideAppInitializer` calls `POST /api/auth/refresh`. `200` → signed in; `401` → route guard sends to `/login` |
| Interceptor | Adds `Authorization` to all `/api/*` except the four public auth paths. On `401 TOKEN_EXPIRED` or `UNAUTHENTICATED`, run a **single-flight** refresh, then retry the original request once |
| Race | On `409 REFRESH_RACE`, retry refresh once after 200 ms |
| Refresh failure | `401 REFRESH_*` → clear state, go to `/login` with the message from §18 |
| Sign out | `POST /api/auth/logout`, then clear state and go to `/login` |
| Signup form | Live checklist for the three rules; server `422` details map to field errors |
| Top bar | Name from `user.full_name`; role label "Nephrologist" for `clinician` (prototype copy) |

### 22.4 Prototype screen mapping

| Prototype element | API |
|---|---|
| Sign in tab, email and password, "Invalid email or password." alert | `POST /auth/login` → `401 INVALID_CREDENTIALS` |
| Lockout text "Five wrong passwords lock an account for 15 minutes" | `429 ACCOUNT_LOCKED` + `Retry-After` |
| Create account tab, password checklist, "An account with this email already exists." | `POST /auth/signup` → `422` rule codes, `409 EMAIL_TAKEN` |
| Demo accounts box | Seeded clinicians only. The "Use admin account" button is removed in the Angular build (ADR-018) |
| Top bar avatar, name, "Nephrologist" | `user` in the login response or `GET /auth/me` |
| Sign out | `POST /auth/logout` |

---

## 23. Containerization and runtime

### 23.1 Dockerfile (build context = repo root, because of `libs/common`)

```dockerfile
# services/auth/Dockerfile
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY libs/common ./libs/common
COPY services/auth/pyproject.toml ./services/auth/pyproject.toml
COPY services/auth/app ./services/auth/app
RUN pip wheel --wheel-dir /wheels ./libs/common ./services/auth

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --system --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY services/auth/alembic.ini ./alembic.ini
COPY services/auth/alembic ./alembic
COPY services/auth/entrypoint.sh ./entrypoint.sh
RUN chmod 0555 entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
ENTRYPOINT ["./entrypoint.sh"]
```

The `app` package is installed from the wheel, so the runtime stage does not copy `app/` again. Alembic's `env.py` imports `app.db.base` from the installed package.

### 23.2 Entrypoint

```sh
#!/bin/sh
set -eu
python -m app.scripts.wait_for_db
alembic upgrade head
if [ "${SEED_DEMO_USERS:-false}" = "true" ]; then
  python -m app.scripts.seed_users
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers "${UVICORN_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*" --no-server-header
```

`--forwarded-allow-ips="*"` is acceptable only because auth-svc has no published port and sits on the private network behind the gateway.

### 23.3 Compose (auth part, existing Postgres container)

```yaml
services:
  auth-svc:
    build:
      context: .
      dockerfile: services/auth/Dockerfile
    env_file: .env
    environment:
      AUTH_DATABASE_URL: postgresql+asyncpg://auth_svc:${AUTH_DB_PW}@postgres:5432/auth_db
      JWT_PRIVATE_KEY_PATH: /run/secrets/jwt_private
      SEED_DEMO_USERS: "true"
    secrets:
      - jwt_private
    networks: [nephro-net]
    mem_limit: 768m
    read_only: true
    tmpfs: [/tmp]
    restart: unless-stopped
    # no "ports": only the gateway publishes a port (HLD-v2 §17.2)

  gateway:
    # ...
    environment:
      JWKS_URL: http://auth-svc:8000/.well-known/jwks.json
    depends_on:
      auth-svc:
        condition: service_healthy
    networks: [nephro-net]

secrets:
  jwt_private:
    file: ./infra/keys/jwt_private.pem

networks:
  nephro-net:
    external: true        # the existing Postgres container is attached to it (§16.4)
```

The secret named `jwt_private` mounts at `/run/secrets/jwt_private`, which is the default `JWT_PRIVATE_KEY_PATH` (§21). Compose secrets outside Swarm are bind mounts and ignore `uid`/`mode`. The key file on the host must be readable by uid 10001 (for local dev, `chmod 0644 infra/keys/jwt_private.pem`; in production use a secret manager, HLD-v2 §13.3).

### 23.4 Key generation

`infra/keys/generate-keys.sh` (keys directory is gitignored):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out jwt_private.pem
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
chmod 0644 jwt_private.pem jwt_public.pem   # dev only, see §23.3
echo "Generated jwt_private.pem and jwt_public.pem"
```

---

## 24. Observability

### 24.1 Logs (JSON, one line per event, no PII)

| Event | Fields |
|---|---|
| `auth.signup.success` | `user_id`, `request_id` |
| `auth.signup.rejected` | `reason` (`disabled`, `email_taken`, `policy`), `request_id` |
| `auth.login.success` | `user_id`, `rehashed` (bool), `request_id` |
| `auth.login.failure` | `reason` (`unknown_user`, `bad_password`, `locked`, `disabled`), `user_id` when known, `request_id` |
| `auth.account.locked` | `user_id`, `until` |
| `auth.refresh.success` | `user_id`, `family_id` |
| `auth.refresh.failure` | `reason` (`missing`, `invalid`, `expired`, `race`, `user_inactive`) |
| `auth.refresh.reuse_detected` | `user_id`, `family_id`, `revoked_count` — **WARN level** |
| `auth.logout` | `user_id` when known, `revoked_count` |
| `auth.cleanup.done` | `deleted` |

Never logged: email addresses, passwords, cookie values, access or refresh tokens, `Authorization` headers.

### 24.2 Metrics (`/metrics`)

| Metric | Type | Labels |
|---|---|---|
| `auth_login_total` | counter | `outcome` |
| `auth_signup_total` | counter | `outcome` |
| `auth_refresh_total` | counter | `outcome` |
| `auth_refresh_reuse_detected_total` | counter | |
| `auth_argon2_seconds` | histogram | `op` (`hash`, `verify`) |
| `auth_argon2_inflight` | gauge | |
| `auth_argon2_rejected_total` | counter | hash requests rejected because the queue wait timed out |
| `auth_rate_limited_total` | counter | `route` |
| `http_request_duration_seconds` | histogram | `route`, `method`, `status` (from libs/common) |

Alert suggestions: any `auth_refresh_reuse_detected_total` increase; login failure rate spike; p95 `auth_argon2_seconds` above 0.5 s.

---

## 25. Testing

Test settings: `ARGON2_MEMORY_KIB=1024`, `ARGON2_TIME_COST=1` (fast), `AUTH_DATABASE_URL` pointing at `auth_db_test` on the same container (§16.3), schema created with `alembic upgrade head` once per session, tables truncated between tests. A fake clock is injected so expiry and lockout can be tested without sleeping.

### 25.1 Unit (pure, no DB)

| Area | Cases |
|---|---|
| Password policy | each rule alone; 9 vs 10 chars; 128 vs 129; letters only; digits only; common password case-insensitive; email local part contained; valid password returns no violations |
| KeyStore | thumbprint `kid` is stable and matches RFC 7638 test vector; JWKS contains `n`, `e`, `kid`, `alg`, `use`; rejects keys under 2048 bits; two keys published during rotation |
| TokenService | claims present and typed; `exp - iat == 900`; header has `kid`; verify rejects wrong `aud`, wrong `iss`, expired, `alg=HS256` token signed with the public key, `alg=none`, unknown `kid` |
| Refresh secret | 43 chars, base64url, sha256 hex length 64, two calls differ |
| Cookie helper | `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api/auth`, `Max-Age` matches expiry; clear sets `Max-Age=0` |

### 25.2 API (FastAPI app + real Postgres)

| Area | Cases |
|---|---|
| Signup | `201` with token and cookie; user row role is `clinician` regardless of payload; `409` on duplicate email with different case; `422` with rule codes; `403` when flag off; password stored as `$argon2id$` |
| Login | `200` for seeded user; `401` same body for unknown email and wrong password; 5 failures then `429` with `Retry-After`; lock expires (fake clock) and login works; success resets counter; `403` for inactive; `LOCKOUT_REVEAL=false` returns `401` while locked; rehash happens when cost settings change |
| Refresh | rotates (old row `rotated`, `replaced_by_id` set, new cookie differs); missing cookie `401 REFRESH_MISSING`; unknown `401 REFRESH_INVALID` and cookie cleared; expired idle; expired absolute (`family_expires_at`); reuse of a `rotated` token outside grace revokes all family rows and returns `401 REFRESH_REUSED`; **login, logout, then refresh with the old cookie returns `401 REFRESH_INVALID`, clears the cookie, logs `auth.refresh.failure reason=invalid`, logs no `reuse_detected` and leaves the family untouched**; replaying a `reuse_detected` token also returns `REFRESH_INVALID`; reuse inside grace returns `409` and does **not** revoke; **revocation persists** after the error response (regression test for §19.3 note); inactive user revokes family; bad `Origin` → `403` |
| Lockout concurrency | 20 parallel wrong guesses reach argon2 at most 5 times and the account ends locked; a correct password slowed while 9 others lock the account answers `429` and starts no session; randomised bursts never succeed after the lock; failures decay after the window (4 failures, +16 min, 1 failure: not locked); `SERVICE_BUSY` gives the attempt back |
| Rate limit and hash queue | the 6th login in a burst from one IP is `429` with `Retry-After`; another IP is unaffected; tokens refill with the fake clock; the bucket map is bounded with LRU eviction; a saturated hash pool answers `503 SERVICE_BUSY` in about the wait timeout and recovers |
| Production guard | each forbidden setting fails startup (and the process exits non-zero); a valid production config starts; `/docs`, `/redoc` and `/openapi.json` return `404` in production; `seed_users` refuses |
| Concurrency | two parallel refreshes with the same cookie → exactly one `200`, one `409`, family still active |
| Logout | `204` with and without cookie; family revoked; subsequent refresh `401` |
| Me | `200` with valid token; `401` missing; `401 TOKEN_EXPIRED`; `403` inactive |
| JWKS | `200`, cache header, verifies a freshly issued token through `libs/common` verifier |
| Health | `/health` 200; `/ready` 503 when DB URL is wrong or migrations not at head |
| Envelope | every error matches `{error: {code, message, details, request_id}}` |
| Logging | captured logs for login contain no email, password or token strings |

### 25.3 Contract and end-to-end

- Gateway test: a `Set-Cookie` from auth-svc reaches the client unchanged through the gateway; `/api/auth/me` without a token is rejected at the gateway.
- E2E smoke (HLD-v2 §16): sign in through the gateway → dashboard loads → reload the page → still signed in (boot refresh) → sign out → protected page redirects to `/login`.

---

## 26. Runbooks

### 26.1 First-time setup on the existing container

```bash
cp .env.example .env                                   # set AUTH_DB_PW
./infra/keys/generate-keys.sh
docker network create nephro-net || true
docker network connect --alias postgres nephro-net <pg>
AUTH_DB_PW=$(grep ^AUTH_DB_PW .env | cut -d= -f2) ./infra/postgres/init-auth-db.sh <pg> <su>
docker compose up --build auth-svc gateway
curl -s http://localhost:8080/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"dr.rao@nephrocare.demo","password":"Nephro#2026"}' -i
```

Expect `200`, a JSON body with `access_token`, and a `Set-Cookie: nephro_rt=...` header.

### 26.2 Signing key rotation (zero downtime)

1. Generate `k2` (private and public PEM).
2. Deploy with `JWT_PRIVATE_KEY_PATH=k1` and `JWT_ADDITIONAL_PUBLIC_KEY_PATHS=k2.pub`. JWKS now lists k1 and k2; tokens are still signed with k1.
3. Wait longer than the verifiers' JWKS cache (5 min).
4. Deploy with `JWT_PRIVATE_KEY_PATH=k2` and `JWT_ADDITIONAL_PUBLIC_KEY_PATHS=k1.pub`. New tokens use k2; old k1 tokens still verify.
5. Wait longer than the access-token lifetime plus leeway (15 min + 30 s).
6. Deploy without k1. Rotation done. Refresh tokens are opaque and unaffected.

### 26.3 Unlock an account

```bash
docker exec <pg> psql -U <su> -d auth_db -c \
  "UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE email = 'dr.rao@nephrocare.demo';"
```

### 26.4 Sign a user out everywhere

```sql
UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'logout'
WHERE user_id = :user_id AND revoked_at IS NULL;
```

Access tokens already issued expire within 15 minutes.

### 26.5 Deactivate a user

```sql
UPDATE users SET is_active = false, updated_at = now() WHERE email = :email;
```

Their next refresh revokes the family (`user_inactive`) and `/auth/me` returns `403`.

### 26.6 Suspected token theft (`reuse_detected` alert)

1. Find the family in logs (`family_id`, `user_id`). It is already revoked.
2. Check other active families for the user: `SELECT family_id, user_agent, created_at FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL;`
3. If in doubt, run §26.4 and reset the user's password. A `set_password.py` script (same policy and hasher as `create_user.py`) is the simplest way; add it when the first reset is needed.

---

## 27. Implementation checklist

| # | Step | Done when |
|---|---|---|
| 1 | Run §16.1 checks on the container (version ≥ 13, connection budget) | Values recorded in README |
| 2 | `init-auth-db.sh` and test DB | §16.5 checks pass |
| 3 | Network attach and compose wiring | `auth-svc` resolves `postgres` |
| 4 | Skeleton: settings, logging, error envelope, health | `/health` 200 in container |
| 5 | Models + `0001_initial` migration with advisory lock | `alembic upgrade head` creates §15.2 schema |
| 6 | KeyStore + JWKS | JWKS returns one key; unit tests green |
| 7 | Password policy + hasher | Unit tests green; hashing runs in a thread |
| 8 | Signup and login with lockout | §25.2 signup and login tests green |
| 9 | Refresh with rotation, reuse and race; logout | §25.2 refresh, concurrency and logout tests green |
| 10 | `/auth/me`, `/ready`, metrics, cleanup job | Tests green; `/ready` reflects DB and migrations |
| 11 | Seed and `create_user` scripts | Demo clinicians can sign in |
| 12 | Gateway routes, public paths, cookie pass-through, JWKS cache | Login through `:8080` returns cookie; `/api/auth/me` works with the token |
| 13 | Angular `AuthService`, boot refresh, interceptor, guards | Reload keeps the session; sign-out returns to `/login` |
| 14 | Export OpenAPI to `docs/api/auth-svc.json` | File committed (HLD-v2 §21 item 4) |

---

## 28. Production hardening

| Area | Behavior |
|---|---|
| Startup guard | With `ENVIRONMENT=production` the service refuses to start (logs `startup.refused` with every reason, exits non-zero) if: `SEED_DEMO_USERS=true`; `COOKIE_SECURE=false`; `CORS_ALLOWED_ORIGINS` contains `localhost` or `*`; the private key file is group- or world-readable; `ENABLE_PUBLIC_SIGNUP=true` without `ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION=true` |
| Docs | `/docs`, `/redoc`, `/openapi.json` are disabled in production. The schema is exported at build time to `docs/api/openapi.json` |
| Seeding | `seed_users` refuses to run in production, even with `--force` |
| Compose | `docker-compose.yml` is dev-oriented and reads seed/signup from `.env`. `docker-compose.prod.yml` sets `ENVIRONMENT=production`, seeding off, signup off, and requires `PROD_CORS_ALLOWED_ORIGINS` |
| Rate limiting | In-process token bucket per client address on `/auth/login` and `/auth/signup`. **Limits are per process** (2 workers means up to 2x the configured rate). Behind the gateway the client address comes from `X-Forwarded-For` (`--proxy-headers`). The gateway is the real limiter; this is defense in depth |
| Bounded hashing | At most `ARGON2_MAX_CONCURRENCY` hashes run at once; others wait up to `ARGON2_QUEUE_TIMEOUT_S`, then get `503 SERVICE_BUSY` (`auth_argon2_rejected_total`) |
| Reproducible builds | `requirements.lock`, `requirements-dev.lock` and `requirements-build.lock` carry hashes (generated inside the pinned Linux image with `pip-compile --generate-hashes`). The Dockerfile installs with `--require-hashes`, from a base image pinned by digest (one digest, both stages) |
| CI | `.github/workflows/auth-svc.yml`: ruff, mypy, pytest against Postgres 16, `pip-audit` on the locks, image build and Trivy (fail on fixable HIGH/CRITICAL) |
