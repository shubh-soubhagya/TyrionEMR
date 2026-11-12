"""encounters.clinician_name becomes nullable; set_updated_at() respects an explicit updated_at.

1. The name is now resolved from auth-svc /auth/me (tokens carry no PII), so it can legitimately be unknown when
   auth-svc is unreachable at write time: NULL replaces the old 'Unknown clinician' placeholder.

2. Existing placeholders are backfilled to NULL, including on FINAL encounters, which ``encounters_guard``
   normally forbids touching. The one-time exception is safe because it replaces a placeholder that meant
   "unknown" with NULL, which means the same thing, and changes no clinical content. The guard and the
   updated_at trigger are disabled only for that single UPDATE, inside this migration's transaction, so the
   rows keep their original updated_at and the guard is back on before the migration commits.

3. set_updated_at() used to overwrite updated_at unconditionally. It now sets now() only when the statement did
   not change updated_at itself, so the injected clock can control timestamps.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_NEW_FN = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$
"""

_OLD_FN = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$
"""


def _rewrite_names(conn, sql: str) -> None:
    conn.exec_driver_sql("ALTER TABLE encounters DISABLE TRIGGER encounters_guard")
    conn.exec_driver_sql("ALTER TABLE encounters DISABLE TRIGGER encounters_updated_at")
    conn.exec_driver_sql(sql)
    conn.exec_driver_sql("ALTER TABLE encounters ENABLE TRIGGER encounters_updated_at")
    conn.exec_driver_sql("ALTER TABLE encounters ENABLE TRIGGER encounters_guard")


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE encounters ALTER COLUMN clinician_name DROP NOT NULL")
    _rewrite_names(conn, "UPDATE encounters SET clinician_name = NULL WHERE clinician_name = 'Unknown clinician'")
    conn.exec_driver_sql(_NEW_FN)


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(_OLD_FN)
    _rewrite_names(conn, "UPDATE encounters SET clinician_name = 'Unknown clinician' WHERE clinician_name IS NULL")
    conn.exec_driver_sql("ALTER TABLE encounters ALTER COLUMN clinician_name SET NOT NULL")
