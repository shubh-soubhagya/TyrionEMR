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
make test         # everything (103 tests)
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
| D9 | JWKS cache/refetch verifier is not included | It is gateway-side. Deferred with the gateway (see Open questions). |

## Operations

Unlock an account, sign a user out everywhere, deactivate a user, rotate keys: see LLD §26.
Key files: `setup/keys/jwt_private.pem` (readable by uid 10001 in dev only; use a secret manager in
production). Other services and the gateway need only `JWKS_URL=http://auth-svc:8000/.well-known/jwks.json`.

## Open questions

1. The gateway was deferred by the layout change ("its own folder, later"). The original task listed it
   in scope and in the definition of done (smoke test through `:8080`). Confirm it is a separate step.
2. `/auth/refresh` after `/auth/logout` with the old cookie reports `REFRESH_REUSED` and logs a WARN
   `reuse_detected`, because a logged-out token is "revoked, not rotated" (LLD §19.3). Harmless, but it
   will raise the alert metric if a client retries logout then refresh. Say if logout-revoked tokens
   should answer `REFRESH_INVALID` quietly instead.
3. `auth_db` (the pre-existing, empty, `postgres`-owned database) was left untouched.
