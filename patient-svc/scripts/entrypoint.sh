#!/bin/sh
# wait_for_db -> alembic upgrade (optional) -> seed (optional, idempotent) -> uvicorn
set -eu
python -m app.cli.wait_for_db
if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  alembic upgrade head
fi
if [ "${SEED_ON_START:-false}" = "true" ]; then
  python -m app.cli.seed_patients
fi
# --forwarded-allow-ips="*" is acceptable only because patient-svc publishes no host port and sits
# on the private network behind the gateway.
# --h11-max-incomplete-event-size 32768: GET /patients?ids=<500 uuids> is about 18.5 KB, above uvicorn's 16 KiB
# default; 32 KiB matches what the gateway accepts (gateway LLD R8).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers "${UVICORN_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*" --no-server-header \
  --h11-max-incomplete-event-size 32768
