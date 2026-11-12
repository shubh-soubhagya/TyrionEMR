#!/usr/bin/env bash
# Generates the JWT signing key pair into setup/keys (gitignored).
#   ./setup/generate-keys.sh          development: 0644 so the container user (uid 10001) can read a bind mount
#   ./setup/generate-keys.sh --prod   production: private key 0600, owned by uid 10001
# ENVIRONMENT=production refuses to start if the private key is group/world readable.
set -euo pipefail
MODE="dev"
case "${1:-}" in
  "") ;;
  --prod) MODE="prod" ;;
  *) echo "usage: $0 [--prod]" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/keys"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out jwt_private.pem
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem

if [[ "$MODE" == "prod" ]]; then
  chmod 0600 jwt_private.pem
  chmod 0644 jwt_public.pem                       # the public key is published in the JWKS anyway
  if [[ "$(id -u)" == "0" ]]; then
    chown 10001:10001 jwt_private.pem jwt_public.pem
    echo "Generated production keys: jwt_private.pem is 0600 and owned by uid 10001."
  else
    echo "Generated production keys: jwt_private.pem is 0600, but owned by you."
    echo "The container runs as uid 10001; hand the file over before starting it:"
    echo "  sudo chown 10001:10001 $(pwd)/jwt_private.pem $(pwd)/jwt_public.pem"
  fi
else
  chmod 0644 jwt_private.pem jwt_public.pem
  echo "Generated jwt_private.pem and jwt_public.pem (DEVELOPMENT mode, mode 0644)."
  echo "WARNING: do not use these for production. Use --prod, or a secret manager."
fi
