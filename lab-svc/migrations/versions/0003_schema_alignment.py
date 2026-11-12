"""Aligns the schema with LLD B3 (constraints, snapshot columns, view, read-model columns).

The first build was made from the system HLD before the LLD existed. This migration keeps stored data: it
backfills what it can derive and refuses (with a clear message) when a row cannot satisfy a new constraint.
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_suffix(".sql")

_DOWN = """
DROP VIEW IF EXISTS lab_results_current;
DROP INDEX IF EXISTS ix_status_attention, ix_results_patient_collected, ux_results_report_test_original;
ALTER TABLE patient_lab_status DROP COLUMN result_count, DROP COLUMN version, DROP COLUMN rules_version;
ALTER TABLE lab_results DROP CONSTRAINT fk_results_report, DROP CONSTRAINT fk_results_supersedes,
  DROP CONSTRAINT unknown_iff_no_range, DROP CONSTRAINT not_self_superseding, DROP CONSTRAINT correction_needs_reason,
  DROP CONSTRAINT lab_results_correction_reason_check, DROP CONSTRAINT ux_results_id_report_test;
ALTER TABLE lab_results DROP COLUMN range_id, DROP COLUMN crit_low, DROP COLUMN crit_high,
  DROP COLUMN correction_reason, DROP COLUMN entered_by;
ALTER TABLE lab_results ADD FOREIGN KEY (report_id) REFERENCES lab_reports(id),
  ADD FOREIGN KEY (supersedes_id) REFERENCES lab_results(id);
ALTER INDEX ix_results_trend RENAME TO lab_results_patient_test;
ALTER INDEX ux_results_supersedes RENAME TO lab_results_one_correction;
CREATE INDEX lab_results_report ON lab_results (report_id);
ALTER INDEX ix_reports_patient_collected RENAME TO lab_reports_patient;
ALTER TABLE lab_reports DROP CONSTRAINT ux_reports_id_patient_collected, DROP COLUMN request_id,
  DROP CONSTRAINT lab_reports_collected_plausible;
ALTER TABLE lab_tests DROP COLUMN created_at, DROP COLUMN updated_at;
ALTER TABLE lab_tests RENAME COLUMN plausible_max TO max_value;
ALTER TABLE lab_tests RENAME COLUMN display_order TO sort_order
"""


def upgrade() -> None:
    conn = op.get_bind()
    for stmt in _SQL.read_text(encoding="utf-8").split("\n--@@\n"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)


def downgrade() -> None:
    """Local use only; partial (constraints that only tighten are left in place)."""
    conn = op.get_bind()
    for stmt in _DOWN.split(";\n"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)
