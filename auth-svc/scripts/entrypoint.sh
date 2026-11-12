#!/bin/sh
# wait_for_db -> alembic upgrade -> seed (optional) -> uvicorn
set -eu
python -m app.cli.wait_for_db
alembic upgrade head
if [ "${SEED_DEMO_USERS:-false}" = "true" ]; then
  python -m app.cli.seed_users
fi
# --forwarded-allow-ips="*" is acceptable only because auth-svc publishes no host port and sits
# on the private network behind the gateway.
# --timeout-graceful-shutdown: in-flight requests get 20 s to finish after SIGTERM; compose waits 25 s
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers "${UVICORN_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*" --no-server-header \
  --timeout-graceful-shutdown 20
