# auth-svc

Identity for the NephroCare EMR. auth-svc registers and signs in clinicians, issues short-lived RS256 access tokens,
rotates refresh tokens held in an HttpOnly cookie, and publishes the public signing keys. Every other service verifies tokens
locally against those keys and never calls auth-svc per request.

It owns: users and password hashes, refresh-token families, the signing keys, the login audit trail.
It does not own: patients, encounters, labs or AI output; authorization beyond one role (`clinician`, ADR-018 in the
[design](docs/auth-svc-HLD-LLD.md)); user management (there is no admin role or admin API).

Synthetic data only.

## Endpoints

Full reference: [docs/API.md](../docs/API.md#auth-svc). All paths are reached through the gateway under `/api`.

| Method | Gateway path | Purpose |
|---|---|---|
| POST | `/api/auth/signup` | Create a clinician and sign them in (controlled by `ENABLE_PUBLIC_SIGNUP`) |
| POST | `/api/auth/login` | Verify email and password; returns an access token and sets the refresh cookie |
| POST | `/api/auth/refresh` | Rotate the refresh cookie and return a new access token |
| POST | `/api/auth/logout` | Revoke the refresh token and clear the cookie |
| GET | `/api/auth/me` | The signed-in user (name and email come from here, never from the token) |
| POST | `/api/auth/password` | Change password; signs the user out everywhere |

Not routed by the gateway:

| Path | Caller |
|---|---|
| `GET /.well-known/jwks.json` | The gateway and the other three services, to verify tokens |
| `GET /health`, `GET /ready` | Docker health checks and the gateway's readiness probe |
| `GET /metrics` | Internal network only (`METRICS_ENABLED`) |

### Token and cookie model

- Access token: RS256, 15 minutes, in the response body, kept in memory by the browser. It carries `sub`, `role`, `iss`,
  `aud`, `kid`, `iat`, `exp` and no personal data.
- Refresh token: opaque random value, 7 days, stored as a SHA-256 hash; sent only as the cookie `nephro_rt`
  (HttpOnly, Secure, SameSite=Strict, `Path=/api/auth`, no `Domain`).
- Rotation with reuse detection: replaying an already rotated token outside a 10 s grace window revokes the whole family.
- Lockout: the 5th failed login locks the account (still `401`), the 6th answers `429` with `Retry-After`.
- Key ids are the RFC 7638 thumbprint of the public key.

## Data

Database `nephro_auth_db` (tests use `nephro_auth_db_test`). Schema and relationships:
[docs/DATABASE.md](../docs/DATABASE.md#auth-svc).

| Table | Holds |
|---|---|
| `users` | Email (unique, lower case), argon2id hash, name, role, active flag, failed-login counters |
| `refresh_tokens` | One row per issued refresh token: SHA-256 hash, family id, expiry, `revoked_at` with a reason (`rotated`, `logout`, `reuse_detected`, `user_inactive`, `password_changed`), the token that replaced it |
| `auth_events` | Append-only audit trail of sign-in outcomes, no emails or tokens (365-day retention) |

Migrations: `0001` initial, `0002` `users.last_failed_at`, `0003` `password_changed` revoke reason, `0004` `auth_events`,
`0005` append-only `auth_events` with `purge_auth_events()`.

## Dependencies

None at runtime except its own database. It calls no other service. Database statement, lock and idle timeouts are set on
every connection; a timeout answers `503 SERVICE_BUSY`.

## Run

As part of the stack: see the root [README](../README.md#quick-start). Alone, for development (needs Python 3.12 and a
Postgres 13+ container; the commands use `graphgpt-postgres` on host port 5433):

```bash
cp .env.example .env            # set the two role passwords and the same passwords inside the four URLs
make install                    # .venv and dev dependencies
make keys                       # RSA-3072 signing key pair into setup/keys (gitignored)
docker network create nephro-net
docker network connect --alias postgres nephro-net graphgpt-postgres
set -a; . ./.env; set +a
make init-db init-test-db       # creates roles auth_migrator and auth_app and the databases; read setup/*.sh first
make migrate                    # as auth_migrator
make seed                       # the two demo clinicians
make run                        # http://localhost:8001/docs on the host
```

`make up` starts the container on `nephro-net` and publishes no host port; only the gateway publishes one. To reach it
directly: `docker run --rm --network nephro-net curlimages/curl -s http://auth-svc:8000/ready`.

Demo clinicians (seeded when `SEED_DEMO_USERS=true`), password `Nephro#2026`:

| Email | Name |
|---|---|
| `dr.rao@nephrocare.demo` | Dr. Anita Rao |
| `dr.malhotra@nephrocare.demo` | Dr. Karan Malhotra |

Their ids are `uuid5(9b3f6a52-7c1e-4d0b-9a58-2f4e8c1d7a10, "user:" + email)`, the ids patient-svc's seed gives its
encounters' clinicians. A database seeded before that change keeps random ids until the two users are deleted and
reseeded: delete them with `DELETE FROM users WHERE email IN (...)`, then `make seed`. Their refresh tokens go with them.
For another clinician when signup is off: `python -m app.cli.create_user --email dr.x@clinic.example --name "Dr. X"`.

Operations (unlock, revoke sessions, reset a password, rotate keys, roles, backups, production): [docs/operations.md](docs/operations.md).

## Configuration

Service-specific settings. The full list with defaults is in [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test` or `production`. Production turns on the startup guard and disables `/docs` |
| `AUTH_DATABASE_URL` | none | Runtime login (`auth_app`) |
| `AUTH_MIGRATION_DATABASE_URL` | unset | Schema-owner login (`auth_migrator`) for Alembic and `make migrate` |
| `ENABLE_PUBLIC_SIGNUP` | `true` in code | Allow `POST /auth/signup`; production also needs `ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION=true` |
| `SEED_DEMO_USERS` | `false` | Seed the two demo clinicians |
| `LOGIN_FAILURE_WINDOW_MINUTES` | `15` | Failed attempts older than this stop counting toward lockout |
| `RATE_LIMIT_LOGIN_PER_MIN` / `RATE_LIMIT_LOGIN_BURST` | `10` / `5` | Per-IP limiter on login and signup, per worker process |
| `ARGON2_QUEUE_TIMEOUT_S` | `2.0` | Longest wait for a hash slot before `503 SERVICE_BUSY` |
| `AUTH_DB_SSLMODE` | `disable` | `disable`, `require` or `verify-full`; production needs `require` or stricter |
| `DB_STATEMENT_TIMEOUT_MS` / `DB_LOCK_TIMEOUT_MS` / `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | `5000` / `2000` / `10000` | Server-side timeouts |
| `AUTH_EVENTS_RETENTION_DAYS` | `365` | Audit retention through `purge_auth_events()`; minimum 30 |
| `METRICS_ENABLED` | `true` | Serve `/metrics` (internal network only) |

Error codes added beyond the design: `429 RATE_LIMITED` (per-IP bucket empty, `Retry-After` set) and `503 SERVICE_BUSY`.
Password-rule details gained `SAME_AS_CURRENT` for the change-password call.

## Tests

```bash
make test         # everything
make test-unit    # pure logic, no database
make test-api     # real Postgres (nephro_auth_db_test), fake clock, cheap argon2
make lint         # ruff and mypy
```

Last recorded full run: 284 passed. API tests run `alembic downgrade base` then `upgrade head` on the test database first, so
the schema under test is the real migration. They need `AUTH_TEST_DATABASE_URL` in `.env`.

Rules the tests prove:

| Rule | Test |
|---|---|
| argon2id only, never plaintext; refresh tokens stored as sha256 | `test_signup`, `test_password_hasher` |
| Unknown email and wrong password: identical `401`; a dummy verify runs | `test_login` |
| 5th failure locks (still `401`), 6th is `429` plus `Retry-After`; no hashing while locked; atomic counter; `LOCKOUT_REVEAL=false` | `test_lockout` |
| Reuse outside the 10 s window revokes the family and the revocation commits | `test_refresh` |
| Reuse inside the window: `409`, nothing changes, cookie untouched | `test_refresh` |
| Only a replayed `rotated` token is theft; logout, `reuse_detected` and `user_inactive` tokens answer `401 REFRESH_INVALID` and touch nothing | `test_refresh` |
| Two parallel refreshes: exactly one `200`, one `409` | `test_refresh_concurrency` |
| Cookie `nephro_rt`: HttpOnly, Secure, SameSite=Strict, `Path=/api/auth`, no `Domain` | `test_cookies`, `test_signup` |
| Origin allow-list on refresh and logout | `test_refresh`, `test_logout` |
| RS256 only; `none`, HS256-confusion, wrong `iss`, `aud` or `kid` rejected; no personal data in the token | `test_token_service` |
| `kid` is the RFC 7638 thumbprint (published test vector) | `test_keystore` |
| `role` is always `clinician`, never read from the request | `test_signup` |
| No emails, passwords, tokens or cookies in logs | `test_no_pii_in_logs` |
| The migration produces exactly the LLD §15.2 schema; the database rejects bad rows itself | `test_schema` |
| `auth_app` cannot alter the schema or change `auth_events` rows | `test_db_roles`, `test_audit_append_only` |

## Design and deviations

Design: [docs/auth-svc-HLD-LLD.md](docs/auth-svc-HLD-LLD.md) (the highest authority for anything auth-related). Operations:
[docs/operations.md](docs/operations.md). This service has no separate build plan.

| # | Design says | Here | Why |
|---|---|---|---|
| D1 | Database `auth_db` | `nephro_auth_db` (and `_test`) | `auth_db` already exists on the shared container, owned by `postgres` |
| D2 | Port 5432 | Host connections use 5433 | Host port 5432 is bound by a different server |
| D3 | `libs/common` and the HLD §17.1 layout | Self-contained service folder; `app/core` instead of an `app/api/deps.py` split | Layout chosen for the repository; overrides HLD §17.1 and LLD §14, §23 |
| D4 | `:now` in the lockout SQL | Every timestamp and access-token expiry use the injected clock | Expiry and lockout can be tested without sleeping |
| D5 | `EmailStr` | `email-validator(test_environment=True)` | `EmailStr` rejects reserved TLDs such as `.test`, which the LLD examples use |
| D6 | `Retry-After` with `+1` | `ceil(remaining seconds)` | A fresh 15-minute lock said "16 minutes" |
| D7 | `docs/api/auth-svc.json` | `docs/api/openapi.json` | One file name in every service |
| D8 | Route label from the path | Rebuilt from the real path | FastAPI reports router-relative paths, which collide across prefixes |
| D9 | JWKS cache and refetch verifier | **Resolved.** The cache and refetch logic live in `gateway/app/services/jwks_cache.py`; patient-svc, lab-svc and ai-svc each keep a copy with the same rules. auth-svc only publishes the keys | The verifier belongs to the consumer, not the issuer |
| D10 | Login verifies, then counts | Login reserves an attempt atomically before verifying; `users.last_failed_at` (migration 0002); old failures stop counting | Parallel guesses bypassed the lockout. LLD §19.2 |
| D11 | No in-service limiter | Per-IP limit on login and signup (`429 RATE_LIMITED`); hash slots wait at most `ARGON2_QUEUE_TIMEOUT_S` then `503 SERVICE_BUSY` | Defense in depth behind the gateway. Limits are per process. LLD §28 |
| D12 | No environment concept | `ENVIRONMENT=production` startup guard; docs off in production; `seed_users` refuses; `docker-compose.prod.yml` | Unsafe configuration must not reach production |
| D13 | Plain install | Base image pinned by digest and a CI workflow. Hash-locked requirements were added, then dropped by decision: the image installs from `pyproject.toml` | Reproducible base image; kept simple like the other services |
| D14 | No timeouts | Statement, lock and idle-in-transaction timeouts on every connection; `503 SERVICE_BUSY` | A stuck query must not hang requests |
| D15 | No TLS setting | `AUTH_DB_SSLMODE` and `AUTH_DB_SSLROOTCERT`; production refuses `disable` | Encrypt database traffic |
| D16 | Log exception messages | Unhandled exceptions log type, cause chain and stack, never messages or locals | Debuggable without leaking request data |
| D17 | 88-entry password list | 142,487 entries (SecLists, MIT) | Real protection against common passwords |
| D18 | `/metrics` public | `METRICS_ENABLED`; documented as internal only | Smaller exposed surface |
| D19 | Manual key handling | `generate-keys.sh --prod`, `rotate-keys.sh`, rotation covered by a test | Key management. LLD §26.2 |
| D20 | No password lifecycle | `POST /auth/password`; CLIs `set_password`, `unlock_user`, `deactivate_user`, `revoke_sessions`; `password_changed` reason (migration 0003) | Password lifecycle without raw SQL |
| D21 | No audit table | `auth_events` (migration 0004), 365-day retention | Durable audit trail with no personal data |
| D22 | One database role | `auth_migrator` and `auth_app`; separate migrate job; `AUTH_MIGRATION_DATABASE_URL` | The runtime role cannot change the schema. LLD §16.3b |
| D23 | `sub` any string | `sub` must be a UUID (else `401`); 20 s graceful shutdown; pool gauges | Small fixes |
| D24 | Audit rows deletable | `auth_events` is append-only for `auth_app`; retention through `purge_auth_events(days)` (migration 0005, `SECURITY DEFINER`, 30-day floor) | The runtime role could rewrite login history. LLD §15.4b |
| D25 | Fallback to the legacy role | No fallback to `auth_svc`: compose requires the four role variables; production refuses a runtime URL using `auth_svc` or `auth_migrator` | A missing variable used to break startup quietly. LLD §16.3b |
| D26 | Examples describe one role | `.env.example` lists the role variables; `setup/retire-legacy-role.sh` retires `auth_svc` (NOLOGIN, never dropped) | The examples had fallen behind the hardening work |
| D27 | FastAPI `redirect_slashes=True` | `redirect_slashes=False`: `/auth/login/` is a 404 | A trailing slash would cost a 307 round trip and leak the upstream path (gateway LLD R14) |
| D28 | Random `uuid4` demo user ids | `uuid5(9b3f6a52-..., "user:" + email)` | patient-svc's seeded encounters reference their clinician by that id |

## Known limitations

- The per-IP limiter is per process: two workers allow up to twice the configured rate.
- The shared Postgres container is a single point of failure for sign-in (see [operations](docs/operations.md#backups-and-the-shared-postgres)).
- There is no admin role, user-management API, email verification or password reset by email; resets are an operator task.
- A database seeded before D28 keeps random demo user ids until reseeded.
