"""auth_events is append-only for the runtime role; retention goes through a guarded function

The default privileges give auth_app UPDATE and DELETE on every table, including the audit trail, so the
service (or anyone holding its credentials) could rewrite or erase login history. This migration:

  * leaves auth_app with SELECT and INSERT only on auth_events
  * adds purge_auth_events(retention_days), SECURITY DEFINER and owned by the migration role, which is the
    ONLY way the runtime role can delete audit rows, and refuses to delete anything newer than 30 days.
    It uses the database clock (now()) on purpose: a caller cannot fake the time to widen the purge.

Every statement that names auth_app is guarded, so the migration also runs on a database without that role
(single-role development and test setups).

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON auth_events FROM auth_app;
        GRANT SELECT, INSERT ON auth_events TO auth_app;
      END IF;
    END
    $$""")

    op.execute("""
    CREATE FUNCTION purge_auth_events(retention_days integer) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE n integer;
    BEGIN
      IF retention_days IS NULL OR retention_days < 30 THEN
        RAISE EXCEPTION 'retention_days must be at least 30';
      END IF;
      DELETE FROM public.auth_events WHERE at < now() - make_interval(days => retention_days);
      GET DIAGNOSTICS n = ROW_COUNT;
      RETURN n;
    END $$""")
    op.execute("REVOKE ALL ON FUNCTION purge_auth_events(integer) FROM PUBLIC")
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_app') THEN
        GRANT EXECUTE ON FUNCTION purge_auth_events(integer) TO auth_app;
      END IF;
    END
    $$""")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_auth_events(integer)")
    # back to what the default privileges gave auth_app before this migration
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON auth_events TO auth_app;
      END IF;
    END
    $$""")
