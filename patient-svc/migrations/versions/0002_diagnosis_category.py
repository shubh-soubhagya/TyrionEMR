"""encounter_diagnoses.category (deviation D7 from LLD §9.2).

The encounter form may send an explicit category for a diagnosis (LLD §11.9 ``DiagnosisIn.category``). Linkage
to the problem list happens at FINALIZE (P-04), possibly in a later request than the one that stored a draft's
diagnoses, so the explicit category must be stored with the draft diagnosis or it would be lost. NULL means
"infer from the ICD-10 code" (LLD §13.6).
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE encounter_diagnoses ADD COLUMN category text")
    conn.exec_driver_sql(
        "ALTER TABLE encounter_diagnoses ADD CONSTRAINT dx_category "
        "CHECK (category IS NULL OR category IN ('nephrology','comorbidity'))")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE encounter_diagnoses DROP COLUMN category")
