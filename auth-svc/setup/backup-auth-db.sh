#!/usr/bin/env bash
# Backs up ONLY the auth database with pg_dump (custom format). Never touches other databases.
# Usage: [AUTH_DB_NAME=nephro_auth_db] ./setup/backup-auth-db.sh <container> [superuser] [output-dir]
# Output: <output-dir>/<db>_<UTC timestamp>.dump (default dir: ./backups, gitignored). Prints the file path.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="${2:-postgres}"
OUT_DIR="${3:-backups}"
DB="${AUTH_DB_NAME:-nephro_auth_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid AUTH_DB_NAME" >&2; exit 1; }

mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/${DB}_$(date -u +%Y%m%dT%H%M%SZ).dump"
# -Fc: compressed, restorable selectively; --no-owner so a restore works under a different owner role
docker exec "$PG_CONTAINER" pg_dump -U "$PG_SU" -Fc --no-owner "$DB" > "$FILE"
# a truncated or empty dump must not look like a success
docker exec -i "$PG_CONTAINER" pg_restore --list < "$FILE" > /dev/null
echo "$FILE"
