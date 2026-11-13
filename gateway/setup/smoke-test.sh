#!/usr/bin/env bash
# End-to-end smoke test of the RUNNING gateway against the real auth-svc, patient-svc, lab-svc and ai-svc.
# Needs: the stack up (`make up` at the repo root), SEED_DEMO_USERS=true in auth-svc, curl, python.
# Usage: bash setup/smoke-test.sh            (GATEWAY_URL defaults to http://localhost:8080)
# Runs in Git Bash on Windows too: every temp file comes from mktemp, JSON is read with $PY.
set -uo pipefail

BASE="${GATEWAY_URL:-http://localhost:8080}"
ORIGIN="${SMOKE_ORIGIN:-http://localhost:4200}"
EMAIL="${SMOKE_EMAIL:-dr.rao@nephrocare.demo}"
PASSWORD="${SMOKE_PASSWORD:-Nephro#2026}"
PY="${PY:-}"
if [ -z "$PY" ]; then
  for c in python python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import json' >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "python not found (set PY=...)"; exit 2; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

check() {   # check "<name>" "<expected>" "<actual>"
  if [ "$2" = "$3" ]; then printf 'PASS  %s\n' "$1"; pass=$((pass + 1))
  else printf 'FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; fail=$((fail + 1)); fi
}
# status <curl args...>: prints only the HTTP status
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)" < "$2" 2>/dev/null; }
cookie_of() { tr -d '\r' < "$1" | sed -n 's/^[Ss]et-[Cc]ookie: nephro_rt=\([^;]*\).*/\1/p' | head -n 1; }

check "health"                          200 "$(status "$BASE/health")"
check "ready"                           200 "$(status "$BASE/ready")"
check "preflight from the app origin"   204 "$(status -X OPTIONS -H "Origin: $ORIGIN" -H 'Access-Control-Request-Method: GET' "$BASE/api/patients")"
check "preflight from a foreign origin" 403 "$(status -X OPTIONS -H 'Origin: http://evil.example' -H 'Access-Control-Request-Method: GET' "$BASE/api/patients")"

# ---- login (no token needed) --------------------------------------------------------------------------------
LOGIN_BODY="$TMP/login.json"; LOGIN_HDR="$TMP/login.hdr"
code="$(curl -s -o "$LOGIN_BODY" -D "$LOGIN_HDR" -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' \
  -H "Origin: $ORIGIN" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" "$BASE/api/auth/login")"
check "login with the demo user" 200 "$code"
TOKEN="$(json 'd["access_token"]' "$LOGIN_BODY")"
RT="$(cookie_of "$LOGIN_HDR")"
check "login set the refresh cookie" yes "$([ -n "$RT" ] && echo yes || echo no)"
AUTH="Authorization: Bearer $TOKEN"

check "/api/auth/me with a token"       200 "$(status -H "$AUTH" "$BASE/api/auth/me")"
check "/api/auth/me without a token"    401 "$(status "$BASE/api/auth/me")"
check "garbage token"                   401 "$(status -H 'Authorization: Bearer not.a.token' "$BASE/api/auth/me")"

# ---- refresh rotates the cookie ----------------------------------------------------------------------------
REF_BODY="$TMP/refresh.json"; REF_HDR="$TMP/refresh.hdr"
code="$(curl -s -o "$REF_BODY" -D "$REF_HDR" -w '%{http_code}' --max-time 20 -X POST -H "Origin: $ORIGIN" \
  -H "Cookie: nephro_rt=$RT" "$BASE/api/auth/refresh")"
check "refresh with the cookie" 200 "$code"
NEW_TOKEN="$(json 'd["access_token"]' "$REF_BODY")"; NEW_RT="$(cookie_of "$REF_HDR")"
[ -n "$NEW_TOKEN" ] && AUTH="Authorization: Bearer $NEW_TOKEN"

# ---- routing and path safety -------------------------------------------------------------------------------
check "internal route is hidden"        404 "$(status -H "$AUTH" "$BASE/api/internal/patients/charts")"
check "raw path traversal"              400 "$(status --path-as-is -H "$AUTH" "$BASE/api/patients/../auth/me")"
check "encoded path traversal"          400 "$(status --path-as-is -H "$AUTH" "$BASE/api/patients/%2e%2e/auth/me")"
check "unknown prefix"                  404 "$(status -H "$AUTH" "$BASE/api/nope")"

# ---- every upstream answers through the gateway ------------------------------------------------------------
check "GET /api/patients"               200 "$(status -H "$AUTH" "$BASE/api/patients")"
check "GET /api/labs/tests"             200 "$(status -H "$AUTH" "$BASE/api/labs/tests")"
check "GET /api/insights/dashboard"     200 "$(status -H "$AUTH" "$BASE/api/insights/dashboard")"

# ---- logout, then the old cookie is dead -------------------------------------------------------------------
check "logout"                          204 "$(status -X POST -H "Origin: $ORIGIN" -H "Cookie: nephro_rt=${NEW_RT:-$RT}" "$BASE/api/auth/logout")"
check "refresh after logout"            401 "$(status -X POST -H "Origin: $ORIGIN" -H "Cookie: nephro_rt=${NEW_RT:-$RT}" "$BASE/api/auth/refresh")"

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
