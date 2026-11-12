#!/usr/bin/env bash
# Idempotent setup of the ai_svc role and the ai database on an EXISTING Postgres container.
# Usage: AI_DB_PW=... [AI_DB_NAME=nephro_ai_db] ./setup/init-ai-db.sh <container> [superuser]
# Touches only: role ai_svc and database $AI_DB_NAME.
# Refuses to adopt a database that already exists with a different owner.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
: "${AI_DB_PW:?set AI_DB_PW}"
DB="${AI_DB_NAME:-nephro_ai_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid AI_DB_NAME"; exit 1; }

psql_su() { docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" "$@"; }

owner=$(psql_su -d postgres -tAc "SELECT r.rolname FROM pg_database x JOIN pg_roles r ON r.oid=x.datdba WHERE x.datname='$DB'")
if [[ -n "$owner" && "$owner" != "ai_svc" ]]; then
  echo "Refusing: database $DB exists and is owned by '$owner', not ai_svc." >&2
  exit 2
fi

psql_su -d postgres -v pw="$AI_DB_PW" <<SQL
SELECT format('CREATE ROLE ai_svc LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_svc') \gexec
SELECT format('ALTER ROLE ai_svc WITH LOGIN PASSWORD %L', :'pw') \gexec
ALTER ROLE ai_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 25;

SELECT 'CREATE DATABASE $DB OWNER ai_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DB') \gexec

REVOKE CONNECT ON DATABASE $DB FROM PUBLIC;
GRANT  CONNECT ON DATABASE $DB TO ai_svc;
ALTER ROLE ai_svc IN DATABASE $DB SET timezone = 'UTC';
SQL

psql_su -d "$DB" <<SQL

ALTER SCHEMA public OWNER TO ai_svc;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
echo "$DB ready on $PG_CONTAINER"
