"""Baseline schema (HLD §5.4): catalog, ranges, reports, results, read model, append-only triggers.

The DDL lives in 0001_baseline.sql (one statement per ``--@@`` separator) and is executed verbatim.
Statements go straight to the driver: asyncpg cannot run a multi-statement string and SQLAlchemy's
``text()`` would read ``:`` inside the SQL as bind parameters.
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_suffix(".sql")

_DROP = """
DROP TABLE IF EXISTS patient_lab_status, lab_results, lab_reports, lab_reference_ranges, lab_tests CASCADE;
DROP FUNCTION IF EXISTS set_updated_at(), lab_append_only()
"""


def upgrade() -> None:
    conn = op.get_bind()
    for stmt in _SQL.read_text(encoding="utf-8").split("\n--@@\n"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)


def downgrade() -> None:
    """Local use only; never run against shared data."""
    conn = op.get_bind()
    for stmt in _DROP.split(";"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)
