#!/usr/bin/env bash
# Idempotent creation of the API-test database (${PATIENT_DB_NAME}_test). Run init-patient-db.sh first (creates the role).
# Usage: [PATIENT_DB_NAME=nephro_patient_db] ./setup/init-patient-db-test.sh <container> [superuser]
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
DB="${PATIENT_DB_NAME:-nephro_patient_db}_test"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid PATIENT_DB_NAME"; exit 1; }

psql_su() { docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" "$@"; }

owner=$(psql_su -d postgres -tAc "SELECT r.rolname FROM pg_database x JOIN pg_roles r ON r.oid=x.datdba WHERE x.datname='$DB'")
if [[ -n "$owner" && "$owner" != "patient_svc" ]]; then
  echo "Refusing: database $DB exists and is owned by '$owner', not patient_svc." >&2
  exit 2
fi

psql_su -d postgres <<SQL
SELECT 'CREATE DATABASE $DB OWNER patient_svc ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DB') \gexec
REVOKE CONNECT ON DATABASE $DB FROM PUBLIC;
GRANT  CONNECT ON DATABASE $DB TO patient_svc;
SQL
psql_su -d "$DB" <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER SCHEMA public OWNER TO patient_svc;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
echo "$DB ready on $PG_CONTAINER"
