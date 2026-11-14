"""patients.last_visit and patients.primary_dx_sort: derived sort keys for the list (README deviation D11, LLD §26).

Sorting the list by last visit or by primary diagnosis needed two lateral joins evaluated for every filtered row
before LIMIT (about 270 ms at 10,000 patients). The two values are now kept on the patient row, in the SAME
transaction as the change that moves them (encounter finalize; condition add, edit, set primary, resolve, delete),
and the list sorts on them. The lateral joins stay for the DISPLAYED values, so the response does not change.

- last_visit      latest encounter_date among the patient's final, not deleted encounters
- primary_dx_sort lower(description) of the active, not deleted primary condition

Both are written by statements that touch only these columns, so the optimistic-concurrency ``version`` is not
bumped: a sort cache must never cause 409 VERSION_CONFLICT for a clinician editing demographics.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE patients ADD COLUMN last_visit timestamptz, ADD COLUMN primary_dx_sort text")
    # backfill from the existing rows (the encounters guard only blocks writes to encounters, not reads)
    conn.exec_driver_sql("""
        UPDATE patients p SET last_visit = v.last_visit
        FROM (SELECT patient_id, max(encounter_date) AS last_visit FROM encounters
              WHERE status = 'final' AND deleted_at IS NULL GROUP BY patient_id) v
        WHERE v.patient_id = p.id""")
    conn.exec_driver_sql("""
        UPDATE patients p SET primary_dx_sort = lower(c.description)
        FROM patient_conditions c
        WHERE c.patient_id = p.id AND c.is_primary AND c.status = 'active' AND c.deleted_at IS NULL""")
    conn.exec_driver_sql(
        "CREATE INDEX patients_last_visit ON patients (last_visit DESC NULLS LAST, id) WHERE deleted_at IS NULL")
    conn.exec_driver_sql(
        "CREATE INDEX patients_primary_dx_sort ON patients (primary_dx_sort NULLS LAST, id) WHERE deleted_at IS NULL")


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DROP INDEX IF EXISTS patients_primary_dx_sort")
    conn.exec_driver_sql("DROP INDEX IF EXISTS patients_last_visit")
    conn.exec_driver_sql("ALTER TABLE patients DROP COLUMN primary_dx_sort, DROP COLUMN last_visit")
