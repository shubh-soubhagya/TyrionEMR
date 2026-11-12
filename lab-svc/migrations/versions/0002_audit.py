"""Audit trail (same shape as patient-svc): every result write and chart read is recorded in the same
transaction. ``details`` holds field names and counts, never lab values."""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_suffix(".sql")


def upgrade() -> None:
    conn = op.get_bind()
    for stmt in _SQL.read_text(encoding="utf-8").split("\n--@@\n"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)


def downgrade() -> None:
    """Local use only."""
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TABLE IF EXISTS audit_events CASCADE")
    conn.exec_driver_sql("DROP FUNCTION IF EXISTS audit_append_only()")
