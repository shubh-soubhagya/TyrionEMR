#!/bin/sh
# The gateway has no database and no migrations: it only starts uvicorn.
set -eu
# ONE worker: the rate-limit buckets and the JWKS cache are per process (the limits would multiply per worker).
# --no-proxy-headers: the gateway IS the edge, so X-Forwarded-* from a client must never be trusted.
# --h11-max-incomplete-event-size 32768: GET /patients?ids=<500 uuids> is about 18.5 KB (gateway LLD R8).
# --timeout-graceful-shutdown 10: in-flight requests get 10 s after SIGTERM; compose waits 15 s.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --no-proxy-headers --no-server-header --h11-max-incomplete-event-size 32768 \
  --timeout-graceful-shutdown 10
