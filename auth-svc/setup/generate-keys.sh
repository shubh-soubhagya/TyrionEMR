#!/usr/bin/env bash
# Generates the JWT signing key pair for LOCAL DEVELOPMENT. Output is gitignored.
set -euo pipefail
cd "$(dirname "$0")/keys"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out jwt_private.pem
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
chmod 0644 jwt_private.pem jwt_public.pem   # dev only: the container user (uid 10001) must read it
echo "Generated jwt_private.pem and jwt_public.pem"
