#!/usr/bin/env bash
# Retires the legacy single role auth_svc once auth_app / auth_migrator have replaced it.
#
#   ./setup/retire-legacy-role.sh <container> [superuser] [--plan]
#
# It touches ONLY the role auth_svc and the databases nephro_auth_db / nephro_auth_db_test (AUTH_DB_NAME):
#   1. REVOKE CONNECT ON DATABASE <each> FROM auth_svc
#   2. ALTER ROLE auth_svc NOLOGIN          (NOT dropped: fully reversible, see the undo lines it prints)
# It REFUSES to run if
#   * auth_migrator or auth_app does not exist (the replacements must be in place first), or
#   * auth_svc still owns ANY object (including the database itself) in either database.
# Idempotent: a second run reports that nothing needs changing. --plan prints what would happen and changes nothing.
set -euo pipefail
PG_CONTAINER="${1:?container name}"
PG_SU="postgres"; PLAN=0
shift
for arg in "$@"; do
  case "$arg" in
    --plan) PLAN=1 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) PG_SU="$arg" ;;
  esac
done
DB="${AUTH_DB_NAME:-nephro_auth_db}"
[[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid AUTH_DB_NAME" >&2; exit 1; }
DBS=("$DB" "${DB}_test")
LEGACY="auth_svc"

psql_su() { docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_SU" "$@"; }
scalar() { psql_su -d postgres -tAc "$1"; }
for d in "${DBS[@]}"; do
  [[ "$(scalar "SELECT count(*) FROM pg_database WHERE datname='$d'")" == "1" ]] || { echo "database $d does not exist" >&2; exit 1; }
done

if [[ "$(scalar "SELECT count(*) FROM pg_roles WHERE rolname='$LEGACY'")" == "0" ]]; then
  echo "Role $LEGACY does not exist: nothing to retire."; exit 0
fi
for r in auth_migrator auth_app; do
  [[ "$(scalar "SELECT count(*) FROM pg_roles WHERE rolname='$r'")" == "1" ]] || {
    echo "Refusing: role $r does not exist. Run setup/init-auth-db.sh first; the replacements must exist before $LEGACY is retired." >&2
    exit 3; }
done

# --- 1. ownership check: does auth_svc still own anything? -------------------------------------------------
blocked=0
for d in "${DBS[@]}"; do
  db_owner=$(scalar "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$d'")
  # pg_shdepend lists every object a role OWNS (deptype 'o'), per database: tables, indexes, functions, schemas, types...
  owned=$(scalar "SELECT count(*) FROM pg_shdepend s WHERE s.refclassid = 'pg_authid'::regclass AND s.deptype = 'o'
                  AND s.refobjid = (SELECT oid FROM pg_roles WHERE rolname='$LEGACY')
                  AND s.dbid = (SELECT oid FROM pg_database WHERE datname='$d')")
  echo "  $d: owner=$db_owner, objects owned by $LEGACY inside it: $owned"
  if [[ "$db_owner" == "$LEGACY" || "$owned" != "0" ]]; then blocked=1; fi
done
if [[ "$blocked" == "1" ]]; then
  echo "Refusing: $LEGACY still owns objects (see above). Move them first: run setup/init-auth-db.sh, which transfers" >&2
  echo "ownership to auth_migrator, then re-run this script." >&2
  exit 4
fi

# --- 2. what would change -----------------------------------------------------------------------------------
can_login=$(scalar "SELECT rolcanlogin FROM pg_roles WHERE rolname='$LEGACY'")
sessions=$(scalar "SELECT count(*) FROM pg_stat_activity WHERE usename='$LEGACY'")
echo "  $LEGACY: can log in = $can_login, open sessions = $sessions"
todo=()
for d in "${DBS[@]}"; do
  # Always revoke on the first run (harmless when no explicit grant is left: moving database ownership already
  # replaced auth_svc's own ACL entry). On later runs only if a grant has reappeared.
  if [[ "$can_login" == "t" || "$(scalar "SELECT has_database_privilege('$LEGACY', '$d', 'CONNECT')")" == "t" ]]; then
    todo+=("REVOKE CONNECT ON DATABASE $d FROM $LEGACY")
  fi
done
[[ "$can_login" == "t" ]] && todo+=("ALTER ROLE $LEGACY NOLOGIN")

if [[ ${#todo[@]} -eq 0 ]]; then
  echo "Already retired: $LEGACY cannot log in and cannot connect to either database. Nothing changed."; exit 0
fi
echo "Planned changes:"; for t in "${todo[@]}"; do echo "  - $t"; done
if [[ "$PLAN" == "1" ]]; then echo "(--plan: nothing was changed)"; exit 0; fi
[[ "$sessions" == "0" ]] || echo "Note: $sessions existing $LEGACY session(s) keep running until they close; this does not terminate them."

# --- 3. apply -----------------------------------------------------------------------------------------------
for t in "${todo[@]}"; do psql_su -d postgres -c "$t" > /dev/null && echo "done: $t"; done
echo
echo "$LEGACY is retired (not dropped). To undo:"
for d in "${DBS[@]}"; do echo "  GRANT CONNECT ON DATABASE $d TO $LEGACY;"; done
echo "  ALTER ROLE $LEGACY LOGIN;"
