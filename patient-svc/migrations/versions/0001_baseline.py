"""Baseline schema (LLD §9.2): tables, constraints, indexes, MRN sequence and the immutability triggers.

The DDL lives in 0001_baseline.sql (one statement per ``--@@`` separator) and is executed verbatim, so the
migration is exactly the reviewed SQL. Statements are sent with the driver directly: asyncpg cannot run a
multi-statement string and SQLAlchemy's ``text()`` would try to read ``:`` inside the SQL as bind parameters.
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_suffix(".sql")

_DROP = """
DROP TABLE IF EXISTS audit_events, encounter_diagnoses, encounter_vitals, medications, allergies,
  patient_conditions, encounters, patients CASCADE;
DROP SEQUENCE IF EXISTS patient_mrn_seq;
DROP FUNCTION IF EXISTS set_updated_at(), encounters_guard(), encounter_children_guard(),
  audit_append_only(), no_hard_delete();
"""


def upgrade() -> None:
    conn = op.get_bind()
    for stmt in _SQL.read_text(encoding="utf-8").split("\n--@@\n"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)


def downgrade() -> None:
    """Local use only; never run against shared data (LLD §23.1)."""
    conn = op.get_bind()
    for stmt in _DROP.split(";"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)
