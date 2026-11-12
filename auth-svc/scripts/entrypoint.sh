#!/bin/sh
# wait_for_db -> alembic upgrade -> seed (optional) -> uvicorn
set -eu
python -m app.cli.wait_for_db
# Migrations are a separate job (docker compose run --rm migrate) that uses the schema-owner role.
# The runtime role cannot run DDL. RUN_MIGRATIONS_ON_START=true is a local-development convenience
# and needs AUTH_MIGRATION_DATABASE_URL.
if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  alembic upgrade head
fi
if [ "${SEED_DEMO_USERS:-false}" = "true" ]; then
  python -m app.cli.seed_users
fi
# --forwarded-allow-ips="*" is acceptable only because auth-svc publishes no host port and sits
# on the private network behind the gateway.
# --timeout-graceful-shutdown: in-flight requests get 20 s to finish after SIGTERM; compose waits 25 s
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers "${UVICORN_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*" --no-server-header \
  --timeout-graceful-shutdown 20
