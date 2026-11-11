#!/usr/bin/env bash
# Idempotent setup of the auth_svc role and the auth database on an EXISTING Postgres container.
# Usage: AUTH_DB_PW=... [AUTH_DB_NAME=nephro_auth_db] ./setup/init-auth-db.sh <container> [superuser]
# Touches only: role auth_svc and database $AUTH_DB_NAME.
# Refuses to adopt a database that already exists with a different owner.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
: "${AUTH_DB_PW:?set AUTH_DB_PW}"
DB="${AUTH_DB_NAME:-nephro_auth_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid AUTH_DB_NAME"; exit 1; }

psql_su() { docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" "$@"; }

owner=$(psql_su -d postgres -tAc "SELECT r.rolname FROM pg_database x JOIN pg_roles r ON r.oid=x.datdba WHERE x.datname='$DB'")
if [[ -n "$owner" && "$owner" != "auth_svc" ]]; then
  echo "Refusing: database $DB exists and is owned by '$owner', not auth_svc." >&2
  exit 2
fi

psql_su -d postgres -v pw="$AUTH_DB_PW" <<SQL
SELECT format('CREATE ROLE auth_svc LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_svc') \gexec
SELECT format('ALTER ROLE auth_svc WITH LOGIN PASSWORD %L', :'pw') \gexec
ALTER ROLE auth_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

SELECT 'CREATE DATABASE $DB OWNER auth_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DB') \gexec

REVOKE CONNECT ON DATABASE $DB FROM PUBLIC;
GRANT  CONNECT ON DATABASE $DB TO auth_svc;
SQL

psql_su -d "$DB" <<SQL
CREATE EXTENSION IF NOT EXISTS citext;
ALTER SCHEMA public OWNER TO auth_svc;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
echo "$DB ready on $PG_CONTAINER"
