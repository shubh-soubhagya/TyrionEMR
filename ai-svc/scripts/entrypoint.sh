#!/bin/sh
# wait_for_db -> alembic upgrade (optional) -> uvicorn. ONE worker: the LLM semaphore, breaker, insights cache and
# job registry are per process (AI-ADR-9). Scale by containers, not workers.
set -eu
python -m app.cli.wait_for_db
if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  alembic upgrade head
fi
# --forwarded-allow-ips="*" is acceptable only because ai-svc publishes no host port and sits on the private
# network behind the gateway.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers "${UVICORN_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="*" --no-server-header
