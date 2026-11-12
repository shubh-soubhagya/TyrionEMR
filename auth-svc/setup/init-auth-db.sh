#!/usr/bin/env bash
# Idempotent LEAST-PRIVILEGE setup of the auth database on an EXISTING Postgres container.
#
#   auth_migrator  owns the database, the schema and every table; runs Alembic. Never used at runtime.
#   auth_app       the service's runtime login: SELECT/INSERT/UPDATE/DELETE on tables, USAGE on the schema,
#                  CONNECT on the database. Cannot create, alter, drop or truncate anything.
#
# Usage:
#   AUTH_MIGRATOR_DB_PW=... AUTH_APP_DB_PW=... [AUTH_DB_NAME=nephro_auth_db] \
#     ./setup/init-auth-db.sh <container> [superuser]
#
# Touches only: roles auth_migrator and auth_app, and database $AUTH_DB_NAME. Safe to run any number of
# times. If the database (and its tables) are still owned by the older single role auth_svc, ownership
# is MOVED to auth_migrator; auth_svc itself is left in place (see the note printed at the end).
# Refuses to touch a database that belongs to anyone other than auth_migrator / auth_svc.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
: "${AUTH_MIGRATOR_DB_PW:?set AUTH_MIGRATOR_DB_PW}"
: "${AUTH_APP_DB_PW:?set AUTH_APP_DB_PW}"
DB="${AUTH_DB_NAME:-nephro_auth_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid AUTH_DB_NAME" >&2; exit 1; }

psql_su() { docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" "$@"; }

owner=$(psql_su -d postgres -tAc "SELECT r.rolname FROM pg_database x JOIN pg_roles r ON r.oid=x.datdba WHERE x.datname='$DB'")
case "$owner" in
  ""|auth_migrator|auth_svc) ;;
  *) echo "Refusing: database $DB exists and is owned by '$owner'." >&2; exit 2 ;;
esac

# 1. roles and the database (cluster level)
psql_su -d postgres -v mpw="$AUTH_MIGRATOR_DB_PW" -v apw="$AUTH_APP_DB_PW" <<SQL
SELECT format('CREATE ROLE auth_migrator LOGIN PASSWORD %L', :'mpw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_migrator') \gexec
SELECT format('ALTER ROLE auth_migrator WITH LOGIN PASSWORD %L', :'mpw') \gexec
ALTER ROLE auth_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

SELECT format('CREATE ROLE auth_app LOGIN PASSWORD %L', :'apw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_app') \gexec
SELECT format('ALTER ROLE auth_app WITH LOGIN PASSWORD %L', :'apw') \gexec
ALTER ROLE auth_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

SELECT 'CREATE DATABASE $DB OWNER auth_migrator ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DB') \gexec
ALTER DATABASE $DB OWNER TO auth_migrator;

REVOKE CONNECT ON DATABASE $DB FROM PUBLIC;
GRANT  CONNECT ON DATABASE $DB TO auth_migrator, auth_app;
SQL

# 2. inside the database. Quoted heredoc: the DO block contains dollar signs the shell must not expand.
psql_su -d "$DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS citext;
ALTER SCHEMA public OWNER TO auth_migrator;

-- move ownership of any table still owned by the legacy single role (no-op on a fresh database)
DO $$
DECLARE r record;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_svc') THEN
    FOR r IN SELECT schemaname, tablename FROM pg_tables
             WHERE schemaname = 'public' AND tableowner = 'auth_svc' LOOP
      EXECUTE format('ALTER TABLE %I.%I OWNER TO auth_migrator', r.schemaname, r.tablename);
    END LOOP;
  END IF;
END
$$;

-- the runtime role: DML only
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT  USAGE ON SCHEMA public TO auth_app;
GRANT  SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auth_app;
-- tables the migrator creates later grant DML to auth_app automatically
ALTER DEFAULT PRIVILEGES FOR ROLE auth_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auth_app;
SQL

echo "$DB ready on $PG_CONTAINER: auth_migrator owns it, auth_app has DML only."
if [[ "$owner" == "auth_svc" ]]; then
  echo "Ownership moved from auth_svc. auth_svc now owns nothing here; once every environment has switched to"
  echo "auth_app / auth_migrator you can retire it:  ALTER ROLE auth_svc NOLOGIN;   (then DROP ROLE auth_svc;)"
fi
