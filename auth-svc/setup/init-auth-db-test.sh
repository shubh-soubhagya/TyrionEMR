#!/usr/bin/env bash
# The API-test database: the same least-privilege setup as init-auth-db.sh, on ${AUTH_DB_NAME}_test.
# Usage: AUTH_MIGRATOR_DB_PW=... AUTH_APP_DB_PW=... [AUTH_DB_NAME=nephro_auth_db] \
#          ./setup/init-auth-db-test.sh <container> [superuser]
set -euo pipefail
export AUTH_DB_NAME="${AUTH_DB_NAME:-nephro_auth_db}_test"
exec bash "$(dirname "$0")/init-auth-db.sh" "$@"
