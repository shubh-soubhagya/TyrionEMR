#!/usr/bin/env bash
# Restores a dump made by backup-lab-db.sh into ONE lab database. DESTRUCTIVE for that database
# (--clean --if-exists drops and recreates its tables). Other databases are never touched.
# Usage: [LAB_DB_NAME=nephro_lab_db] ./setup/restore-lab-db.sh <container> <dump-file> [superuser] [--yes]
# The target is LAB_DB_NAME (default nephro_lab_db); to rehearse a restore, set LAB_DB_NAME to the
# test database (nephro_lab_db_test). Without --yes you must type the database name to confirm.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
DUMP="${2:?dump file}"
PG_SU="${3:-postgres}"
CONFIRM="${4:-}"
DB="${LAB_DB_NAME:-nephro_lab_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid LAB_DB_NAME" >&2; exit 1; }
[[ "$DB" == *lab_db* ]] || { echo "Refusing: '$DB' does not look like an lab database." >&2; exit 2; }
[[ -f "$DUMP" ]] || { echo "dump file not found: $DUMP" >&2; exit 1; }

if [[ "$CONFIRM" != "--yes" ]]; then
  read -r -p "This will DROP and recreate the tables in database '$DB'. Type the database name to continue: " typed
  [[ "$typed" == "$DB" ]] || { echo "aborted" >&2; exit 3; }
fi
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_SU" -d "$DB" --clean --if-exists --no-owner < "$DUMP"
echo "restored $DUMP into $DB"
