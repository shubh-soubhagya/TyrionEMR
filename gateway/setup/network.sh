#!/usr/bin/env bash
# Idempotent: creates the external Docker network the gateway and every service share. Safe to run any number of times.
# (Attaching the shared Postgres container to it is done by the repo-root `make network`, not here: the gateway has no database.)
set -euo pipefail
NET="${1:-nephro-net}"
if docker network inspect "$NET" >/dev/null 2>&1; then
  echo "network $NET already exists"
else
  docker network create "$NET" >/dev/null
  echo "network $NET created"
fi
