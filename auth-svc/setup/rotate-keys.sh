#!/usr/bin/env bash
# Signing-key rotation, LLD section 26.2 steps 1 and 2: generate the NEXT key (k2) and print the
# configuration that publishes it next to the current one. Nothing is switched yet.
#   ./setup/rotate-keys.sh            development file modes
#   ./setup/rotate-keys.sh --prod     private key 0600 (chown to uid 10001 as shown)
set -euo pipefail
MODE="${1:-}"
[[ -z "$MODE" || "$MODE" == "--prod" ]] || { echo "usage: $0 [--prod]" >&2; exit 2; }

cd "$(dirname "$0")/keys"
[[ -f jwt_private.pem ]] || { echo "No current key (jwt_private.pem). Run generate-keys.sh first." >&2; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NEXT_PRIV="jwt_private_${STAMP}.pem"
NEXT_PUB="jwt_public_${STAMP}.pem"

# Step 1: generate k2
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$NEXT_PRIV"
openssl rsa -in "$NEXT_PRIV" -pubout -out "$NEXT_PUB"
if [[ "$MODE" == "--prod" ]]; then chmod 0600 "$NEXT_PRIV"; else chmod 0644 "$NEXT_PRIV"; fi
chmod 0644 "$NEXT_PUB"
HERE="$(pwd)"

cat <<EOF

Step 1 done: generated the next key
  private: $HERE/$NEXT_PRIV
  public:  $HERE/$NEXT_PUB

Step 2: publish BOTH keys (k1 still signs). Deploy auth-svc with:
  JWT_PRIVATE_KEY_PATH=<path to the CURRENT private key (k1)>
  JWT_ADDITIONAL_PUBLIC_KEY_PATHS=$HERE/$NEXT_PUB
The JWKS now lists k1 and k2. Tokens are still signed with k1.

Later steps (do them in order; do not skip the waits):
  3. Wait longer than the verifiers' JWKS cache (5 minutes + margin).
  4. Switch the signer to k2 and keep k1 published:
       JWT_PRIVATE_KEY_PATH=$HERE/$NEXT_PRIV
       JWT_ADDITIONAL_PUBLIC_KEY_PATHS=<path to the k1 PUBLIC key>
  5. Wait longer than the access-token lifetime plus leeway (15 minutes + 30 seconds).
  6. Deploy without k1 (JWT_ADDITIONAL_PUBLIC_KEY_PATHS empty). Rotation is done.
Refresh tokens are opaque and are not affected by rotation.
EOF
if [[ "$MODE" == "--prod" && "$(id -u)" != "0" ]]; then
  echo
  echo "Hand the new private key to the container user:  sudo chown 10001:10001 $HERE/$NEXT_PRIV"
fi
