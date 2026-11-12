# auth-svc

Identity, credentials, sessions and token-signing keys for the NephroCare EMR. Self-contained: own
Dockerfile, migrations, tests and docs. Design: [docs/auth-svc-HLD-LLD.md](docs/auth-svc-HLD-LLD.md)
(highest authority for anything auth-related). API: [docs/api/openapi.json](docs/api/openapi.json).

Synthetic data only. One role, `clinician` (ADR-018): there is no admin role and no user-management API.

## Layout

```
app/core         settings, error envelope, request-id + JSON access log, redaction, metrics, token verification
app/api          routes -> services (no SQL here), cookie helpers
app/services     AuthService (transactions), TokenService, KeyStore (JWKS), PasswordHasherService
app/repositories all SQL
app/models       SQLAlchemy models        app/domain  pure logic (password policy, clock)
app/jobs         refresh-token cleanup    app/cli     wait_for_db, seed_users, create_user, export_openapi
migrations       Alembic (async, advisory lock)        setup   one-time DB + key scripts
```

## First-time setup (existing Postgres container)

Prerequisites: Docker, Python 3.12, and a running Postgres 13+ container. The commands below use
`graphgpt-postgres`; override with `PG_CONTAINER=... PG_SUPERUSER=...`.

```bash
cp .env.example .env            # set AUTH_DB_PW (and the password inside the two URLs)
make install                    # .venv + dev dependencies
make keys                       # RSA-3072 signing key pair -> setup/keys (gitignored)

# These two change the shared Postgres container. Read setup/*.sh first. They only create the
# role auth_svc and the databases nephro_auth_db / nephro_auth_db_test, and refuse to touch a
# database owned by anyone else.
docker network create nephro-net
docker network connect --alias postgres nephro-net graphgpt-postgres
set -a; . ./.env; set +a
make init-db init-test-db

make migrate                    # alembic upgrade head
make seed                       # demo clinicians
```

Run it:

```bash
make run                        # host, http://localhost:8001/docs
make up                         # Docker, on nephro-net (no host port is published)
```

`make up` publishes nothing by design; only the gateway will publish a port. To reach it from the
host for a quick check, run a throwaway container on `nephro-net`, for example
`docker run --rm --network nephro-net curlimages/curl -s http://auth-svc:8000/ready`.

### Demo users (seeded when `SEED_DEMO_USERS=true`)

| Email | Name | Password |
|---|---|---|
| dr.rao@nephrocare.demo | Dr. Anita Rao | `Nephro#2026` |
| dr.malhotra@nephrocare.demo | Dr. Karan Malhotra | `Nephro#2026` |

The prototype's `admin@nephrocare.demo` is deliberately not seeded. Invite a clinician when signup is
off: `python -m app.cli.create_user --email dr.x@clinic.example --name "Dr. X"`.

## Tests

```bash
make test         # everything (105 tests)
make test-unit    # pure, no database
make test-api     # real Postgres (nephro_auth_db_test), fake clock, cheap argon2
make lint         # ruff + mypy
```

API tests run `alembic downgrade base` then `upgrade head` on the test database first, so the schema
under test is the real migration. They need `AUTH_TEST_DATABASE_URL` in `.env`.

## Rules the tests prove

| Rule | Test |
|---|---|
| argon2id only, never plaintext; refresh tokens stored as sha256 | `test_signup`, `test_password_hasher` |
| Unknown email and wrong password: identical `401`; dummy verify runs | `test_login` |
| 5th failure locks (still `401`), 6th is `429` + `Retry-After`; no hashing while locked; atomic counter; `LOCKOUT_REVEAL=false` | `test_lockout` |
| Reuse outside the 10 s window revokes the family **and the revocation commits** | `test_refresh` (mutation-checked) |
| Reuse inside the window: `409`, nothing changes, cookie untouched | `test_refresh` |
| Only a replayed `rotated` token is theft. Logout / `reuse_detected` / `user_inactive` tokens answer `401 REFRESH_INVALID`, clear the cookie, touch nothing, log no `reuse_detected` | `test_refresh` |
| Two parallel refreshes: exactly one `200`, one `409` | `test_refresh_concurrency` |
| Cookie `nephro_rt`: HttpOnly, Secure, SameSite=Strict, Path=/api/auth, no Domain | `test_cookies`, `test_signup` |
| Origin allow-list on refresh and logout | `test_refresh`, `test_logout` |
| RS256 only; `none`/HS256-confusion/wrong iss/aud/kid rejected; no PII in token | `test_token_service` |
| `kid` is the RFC 7638 thumbprint (published test vector) | `test_keystore` |
| `role` always `clinician`, never read from the request | `test_signup` |
| No emails, passwords, tokens or cookies in logs | `test_no_pii_in_logs` |
| Migration produces exactly the LLD 15.2 schema; DB rejects bad rows itself | `test_schema` |

## Deviations from the design documents

| # | Deviation | Reason |
|---|---|---|
| D1 | Database is `nephro_auth_db` (and `_test`), not `auth_db` | `auth_db` already exists on the shared container, owned by `postgres`. Chosen by the user (option B). |
| D2 | Host-side connections use port **5433**, not 5432 | Host port 5432 is also bound by a different server, which rejects the `auth_svc` password. 5433 reaches the same container. |
| D3 | Self-contained service in `auth-svc/`, no `libs/common`, `app/core` instead of `app/api/deps.py` split etc. | Layout change requested by the user, overriding HLD-v2 §17.1 and LLD §14/§23. |
| D4 | Lockout SQL and every timestamp use the injected clock (`:now`), and **access-token expiry is checked against the same clock** | Needed to test expiry and lockout without sleeping. The LLD already specified `:now` for lockout; token expiry needed the same treatment (PyJWT checks the wall clock). |
| D5 | Email validated with `email-validator(test_environment=True)` instead of `EmailStr` | `EmailStr` rejects reserved TLDs, including `.test` used by the LLD's own examples. Deliverability is never checked. |
| D6 | `Retry-After` is `ceil(remaining seconds)` | The LLD's `+1` made a fresh 15-minute lock say "16 minutes". |
| D7 | OpenAPI export is `docs/api/openapi.json` | Per the requested tree (the original task said `docs/api/auth-svc.json`). |
| D8 | Route label in logs/metrics is rebuilt from the real path | FastAPI reports router-relative paths (`/login`), which would collide across prefixes. |
| D9 | JWKS cache/refetch verifier is not included | It is gateway-side. Deferred with the gateway. |
| D10 | Login reserves an attempt atomically **before** verifying the password; new column `users.last_failed_at` (migration 0002); failures older than `LOGIN_FAILURE_WINDOW_MINUTES` stop counting | Parallel guesses bypassed the lockout (N tried instead of 5) and a correct guess could log in after the account locked. LLD §19.2 |
| D11 | In-process per-IP rate limit on `/auth/login` and `/auth/signup` (`429 RATE_LIMITED`); hash slots wait at most `ARGON2_QUEUE_TIMEOUT_S` then `503 SERVICE_BUSY` | Defense in depth until the gateway exists. Limits are **per process** (2 workers = up to 2x). LLD §28 |
| D12 | `ENVIRONMENT=production` startup guard; docs/schema off in production; `seed_users` refuses; `docker-compose.prod.yml` | Unsafe config must not reach production. LLD §28 |
| D13 | Dependencies hash-locked (`requirements*.lock`), base image pinned by digest, CI workflow, runtime image no longer copies `app/` | Reproducible, verifiable builds. `/ready` now finds `alembic.ini` via the working directory |

## Configuration added for production readiness

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` / `test` / `production`. Production turns on the startup guard and disables `/docs`, `/redoc`, `/openapi.json` |
| `ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION` | `false` | Needed to run production with `ENABLE_PUBLIC_SIGNUP=true` |
| `LOGIN_FAILURE_WINDOW_MINUTES` | `15` | Failed attempts older than this stop counting toward lockout |
| `RATE_LIMIT_ENABLED` | `true` | In-process per-IP limiter on login and signup |
| `RATE_LIMIT_LOGIN_PER_MIN` | `10` | Sustained refill per IP, **per worker process** |
| `RATE_LIMIT_LOGIN_BURST` | `5` | Requests allowed back-to-back from a cold start |
| `ARGON2_QUEUE_TIMEOUT_S` | `2.0` | Max wait for a hash slot before `503 SERVICE_BUSY` |

### New error codes

| HTTP | Code | When |
|---|---|---|
| 429 | `RATE_LIMITED` | Per-IP bucket empty on login or signup. `Retry-After` set |
| 503 | `SERVICE_BUSY` | Hash queue full for `ARGON2_QUEUE_TIMEOUT_S`. `Retry-After: 1` |

### Running in production

```bash
PROD_CORS_ALLOWED_ORIGINS=https://emr.example.org \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The service refuses to start (and says why) if seeding is on, cookies are not Secure, CORS names
localhost or `*`, the key file is group/world readable, or public signup is on without
`ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION=true`.

### Reproducible builds

Dependencies are locked with hashes, generated inside the pinned Linux image:

```bash
make lock    # rewrites requirements.lock, requirements-dev.lock and requirements-build.lock
```

`pip install --require-hashes` is used by the Dockerfile and CI. CI is `.github/workflows/auth-svc.yml`.

## Operations

Unlock an account, sign a user out everywhere, deactivate a user, rotate keys: see LLD §26.
Key files: `setup/keys/jwt_private.pem` (readable by uid 10001 in dev only; use a secret manager in
production). Other services and the gateway need only `JWKS_URL=http://auth-svc:8000/.well-known/jwks.json`.

## Status and open items

auth-svc is complete except the smoke test through the gateway on `:8080`. The gateway is a separate
step in its own folder; it needs only `JWKS_URL=http://auth-svc:8000/.well-known/jwks.json`.
The pre-existing empty `auth_db` on the shared container is intentionally left alone.
