# auth-svc operations

Runbooks for running auth-svc outside a quick local start. The service README ([../README.md](../README.md)) covers what the
service does and how to run it; this file covers what an operator does with it.

Contents:

- [Run in production](#run-in-production)
- [Reproducible builds](#reproducible-builds)
- [Everyday tasks](#everyday-tasks)
- [Least-privilege database roles](#least-privilege-database-roles)
- [Retire the legacy role](#retire-the-legacy-role)
- [Watch the audit table](#watch-the-audit-table)
- [Backups and the shared Postgres](#backups-and-the-shared-postgres)
- [Common-password list](#common-password-list)
- [CI](#ci)

Run the commands inside the container (`docker compose exec auth-svc ...`) or on the host with `.env` loaded.

## Run in production

```bash
PROD_CORS_ALLOWED_ORIGINS=https://emr.example.org \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The service refuses to start, and says why, if seeding is on, cookies are not Secure, CORS names localhost or `*`, the key
file is group or world readable, or public signup is on without `ALLOW_PUBLIC_SIGNUP_IN_PRODUCTION=true`. Production also
refuses a runtime database URL that uses `auth_svc` or `auth_migrator`, and requires `AUTH_DB_SSLMODE` of `require` or
stricter. `/docs`, `/redoc` and `/openapi.json` are off in production.

Other services and the gateway need only `JWKS_URL=http://auth-svc:8000/.well-known/jwks.json`.

## Reproducible builds

The image installs from `pyproject.toml` (version floors, no hashes; hash-locked requirements were dropped by decision). The
base image is pinned by digest. CI installs with `pip install -e ".[dev]"` and scans with `pip-audit`.

## Everyday tasks

Each command prints what it changed and writes an audit event.

| Task | Command |
|---|---|
| Unlock an account | `python -m app.cli.unlock_user --email dr.rao@nephrocare.demo` |
| Sign a user out everywhere | `python -m app.cli.revoke_sessions --email ...` |
| Deactivate a user (and sign out) | `python -m app.cli.deactivate_user --email ...` |
| Reset a password (prompted twice, policy applied, signs out everywhere) | `python -m app.cli.set_password --email ...` |
| Create a clinician when signup is off | `python -m app.cli.create_user --email ... --name "Dr. X"` |
| Migrate the schema (schema-owner role) | `make migrate` |
| See what retiring the legacy `auth_svc` role would do (read-only) | `make retire-legacy-role-plan` |
| Retire the legacy `auth_svc` role (no login, no connect; not dropped) | `make retire-legacy-role` |
| Rotate the signing key (steps 1-2 of LLD §26.2) | `./setup/rotate-keys.sh [--prod]` |
| Create the production signing key (mode 0600, uid 10001) | `./setup/generate-keys.sh --prod` |

## Least-privilege database roles

| Role | Used by | Rights |
|---|---|---|
| `auth_migrator` | Alembic, `make migrate`, test cleanup | Owns the database, the `public` schema and every table and function. Never used at runtime. |
| `auth_app` | The running service (`AUTH_DATABASE_URL`) | `CONNECT`; `USAGE` on `public`; `SELECT, INSERT, UPDATE, DELETE` on `users` and `refresh_tokens`; `SELECT, INSERT` only on `auth_events` (append-only); `EXECUTE` on `purge_auth_events()`. Cannot create, alter, drop or truncate anything. |
| `auth_svc` | Nobody: the retired single role | Owns nothing after `init-auth-db.sh`; `make retire-legacy-role` blocks its login. |

`setup/init-auth-db.sh` is idempotent and moves ownership from the legacy `auth_svc`. It changes roles and grants, so read
it before running it on a shared Postgres. A fresh setup ends with the same grants as after migration `0005`.

```bash
set -a; . ./.env; set +a
make init-db init-test-db       # create or repair the roles, databases and grants
make migrate                    # schema changes run as auth_migrator
```

The tests that prove the split (`tests/api/test_db_roles.py`, `tests/api/test_audit_append_only.py`) run when
`AUTH_TEST_DATABASE_URL` (auth_app) and `AUTH_TEST_MIGRATION_DATABASE_URL` (auth_migrator) differ.

## Retire the legacy role

```bash
make retire-legacy-role-plan    # read-only: shows what it would do
make retire-legacy-role         # REVOKE CONNECT on both databases, then ALTER ROLE auth_svc NOLOGIN
```

`setup/retire-legacy-role.sh` touches only `auth_svc`. It is idempotent. It refuses to run if `auth_migrator` or `auth_app`
is missing, or if `auth_svc` still owns any object in either database. It never drops the role. It prints the undo commands
(`ALTER ROLE auth_svc LOGIN`, `GRANT CONNECT ...`). Existing `auth_svc` sessions keep running until they close; the script
does not terminate them.

## Watch the audit table

Every login with an unknown email writes an `auth_events` row (`unknown_user`, no email stored). The per-IP rate limit caps
that per address, and retention purges old rows (`AUTH_EVENTS_RETENTION_DAYS`, 365 by default, never below 30). A
distributed password-spraying attack still grows the table fast, and its rows cannot be purged for at least 30 days.
Monitor the table size and row count, their growth rate, the share of `unknown_user` outcomes, and `auth_rate_limited_total`.
The reasoning and queries are in the design document, LLD §24.3.

```sql
SELECT pg_size_pretty(pg_total_relation_size('auth_events')) AS size, (SELECT count(*) FROM auth_events) AS rows;
```

## Backups and the shared Postgres

```bash
./setup/backup-auth-db.sh graphgpt-postgres postgres                    # this database only, verified readable
AUTH_DB_NAME=nephro_auth_db_test ./setup/restore-auth-db.sh graphgpt-postgres backups/<file>.dump postgres   # rehearse on the test DB
```

`nephro_auth_db` shares the `graphgpt-postgres` container with other databases. A restore, a heavy query or a full disk
elsewhere on that server affects sign-in for everyone. Use a dedicated instance, or managed Postgres with point-in-time
recovery, in production.

## Common-password list

`app/domain/data/common_passwords.txt` is SecLists' `Pwdb_top-1000000.txt` (MIT, Daniel Miessler), filtered to 10 or more
characters, lowercased and de-duplicated (142,487 entries). The file header records the source. To regenerate it, download
the source file into an empty directory and keep the lines of 10 or more characters, lowercased and de-duplicated.

## CI

`.github/workflows/auth-svc.yml` runs ruff, mypy and pytest on Postgres 16 with both roles, then `pip-audit`, an image
build and Trivy. It is the only service with a CI workflow.
