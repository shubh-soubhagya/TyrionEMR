"""patient_lab_status gains first_result_at and egfr_lt60_run (ai-svc LLD B20.1 #1-2, lab-rules-2).

Both columns are nullable and derived, so existing rows stay valid. They are filled by a rebuild
(``python -m app.cli.rebuild_status --stale-only``): rows still on ``lab-rules-1`` are the stale ones.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE patient_lab_status ADD COLUMN first_result_at timestamptz NULL, "
               "ADD COLUMN egfr_lt60_run jsonb NULL")


def downgrade() -> None:
    """Local use only: the columns are derived data, a later rebuild restores them."""
    op.execute("ALTER TABLE patient_lab_status DROP COLUMN egfr_lt60_run, DROP COLUMN first_result_at")
