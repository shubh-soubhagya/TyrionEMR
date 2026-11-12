#!/usr/bin/env bash
# Restores a dump made by backup-patient-db.sh into ONE patient database. DESTRUCTIVE for that database
# (--clean --if-exists drops and recreates its tables). Other databases are never touched.
# Usage: [PATIENT_DB_NAME=nephro_patient_db] ./setup/restore-patient-db.sh <container> <dump-file> [superuser] [--yes]
# The target is PATIENT_DB_NAME (default nephro_patient_db); to rehearse a restore, set PATIENT_DB_NAME to the
# test database (nephro_patient_db_test). Without --yes you must type the database name to confirm.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
DUMP="${2:?dump file}"
PG_SU="${3:-postgres}"
CONFIRM="${4:-}"
DB="${PATIENT_DB_NAME:-nephro_patient_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid PATIENT_DB_NAME" >&2; exit 1; }
[[ "$DB" == *patient_db* ]] || { echo "Refusing: '$DB' does not look like an patient database." >&2; exit 2; }
[[ -f "$DUMP" ]] || { echo "dump file not found: $DUMP" >&2; exit 1; }

if [[ "$CONFIRM" != "--yes" ]]; then
  read -r -p "This will DROP and recreate the tables in database '$DB'. Type the database name to continue: " typed
  [[ "$typed" == "$DB" ]] || { echo "aborted" >&2; exit 3; }
fi
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_SU" -d "$DB" --clean --if-exists --no-owner < "$DUMP"
echo "restored $DUMP into $DB"
