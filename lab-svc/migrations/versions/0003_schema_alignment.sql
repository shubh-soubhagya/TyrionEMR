-- Aligns the first-build schema with LLD B3. Each statement is separated by --@@ and runs in one transaction.
-- Refuses (instead of guessing) when existing rows cannot satisfy a new constraint.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM lab_results WHERE scale(value_original) > 4 OR scale(value) > 4) THEN
    RAISE EXCEPTION '0003: some stored values have more than 4 decimal places; refusing to round clinical data';
  END IF;
END $$
--@@
-- ---------------------------------------------------------------- lab_tests (B3.2)
ALTER TABLE lab_tests RENAME COLUMN max_value TO plausible_max
--@@
ALTER TABLE lab_tests RENAME COLUMN sort_order TO display_order
--@@
ALTER TABLE lab_tests ALTER COLUMN plausible_max TYPE numeric(12,4)
--@@
ALTER TABLE lab_tests ADD CONSTRAINT lab_tests_display_order_key UNIQUE (display_order),
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()
--@@
ALTER TABLE lab_tests DROP CONSTRAINT lab_tests_code_check,
  ADD CONSTRAINT lab_tests_code_check CHECK (code ~ '^[A-Z]{1,10}$')
--@@
CREATE TRIGGER lab_tests_updated BEFORE UPDATE ON lab_tests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at()
--@@
-- ---------------------------------------------------------------- lab_reference_ranges (B3.2)
ALTER TABLE lab_reference_ranges
  ADD COLUMN source text NOT NULL DEFAULT 'reference/emr-ui.html prototype',
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ALTER COLUMN low TYPE numeric(12,4), ALTER COLUMN high TYPE numeric(12,4),
  ALTER COLUMN critical_low TYPE numeric(12,4), ALTER COLUMN critical_high TYPE numeric(12,4)
--@@
ALTER TABLE lab_reference_ranges ALTER COLUMN source DROP DEFAULT
--@@
ALTER TABLE lab_reference_ranges DROP CONSTRAINT lab_ranges_low_high,
  ADD CONSTRAINT range_low_lt_high CHECK (low IS NULL OR high IS NULL OR low < high),
  ADD CONSTRAINT range_has_a_limit CHECK (low IS NOT NULL OR high IS NOT NULL),
  ADD CONSTRAINT range_age_max_plausible CHECK (age_max IS NULL OR age_max <= 130)
--@@
ALTER TABLE lab_reference_ranges RENAME CONSTRAINT lab_ranges_age_order TO range_age_order
--@@
ALTER TABLE lab_reference_ranges RENAME CONSTRAINT lab_ranges_crit_low TO crit_low_le_low
--@@
ALTER TABLE lab_reference_ranges RENAME CONSTRAINT lab_ranges_crit_high TO crit_high_ge_high
--@@
DROP INDEX lab_ranges_key
--@@
CREATE UNIQUE INDEX ux_ranges_key ON lab_reference_ranges
  (test_code, COALESCE(sex, '*'), COALESCE(age_min, -1), COALESCE(age_max, -1), effective_from)
--@@
-- ---------------------------------------------------------------- lab_reports (B3.3)
ALTER TABLE lab_reports DISABLE TRIGGER lab_reports_append_only
--@@
UPDATE lab_reports SET lab_name = 'Unspecified laboratory' WHERE lab_name IS NULL OR btrim(lab_name) = ''
--@@
UPDATE lab_reports SET notes = left(notes, 500) WHERE char_length(notes) > 500
--@@
ALTER TABLE lab_reports ENABLE TRIGGER lab_reports_append_only
--@@
ALTER TABLE lab_reports DROP CONSTRAINT lab_reports_not_future,
  DROP CONSTRAINT lab_reports_lab_name_check, DROP CONSTRAINT lab_reports_notes_check,
  ALTER COLUMN lab_name SET NOT NULL,
  ALTER COLUMN created_at SET DEFAULT now(),
  ADD COLUMN request_id text,
  ADD CONSTRAINT lab_reports_lab_name_check CHECK (char_length(lab_name) BETWEEN 1 AND 120),
  ADD CONSTRAINT lab_reports_notes_check CHECK (notes IS NULL OR char_length(notes) <= 500),
  ADD CONSTRAINT lab_reports_collected_plausible CHECK (collected_at >= TIMESTAMPTZ '1900-01-01 00:00Z'),
  ADD CONSTRAINT ux_reports_id_patient_collected UNIQUE (id, patient_id, collected_at)
--@@
ALTER INDEX lab_reports_patient RENAME TO ix_reports_patient_collected
--@@
-- ---------------------------------------------------------------- lab_results (B3.3)
ALTER TABLE lab_results
  ADD COLUMN range_id uuid REFERENCES lab_reference_ranges(id),
  ADD COLUMN crit_low numeric(12,4),
  ADD COLUMN crit_high numeric(12,4),
  ADD COLUMN correction_reason text,
  ADD COLUMN entered_by uuid
--@@
ALTER TABLE lab_results DISABLE TRIGGER lab_results_append_only
--@@
UPDATE lab_results r SET entered_by = p.entered_by FROM lab_reports p WHERE p.id = r.report_id
--@@
-- snapshot -> range: the range in force on the collection date whose limits equal the stored ref_low/ref_high
UPDATE lab_results r SET range_id = (
  SELECT g.id FROM lab_reference_ranges g
  WHERE g.test_code = r.test_code AND g.effective_from <= r.collected_at::date
    AND g.low IS NOT DISTINCT FROM r.ref_low AND g.high IS NOT DISTINCT FROM r.ref_high
  ORDER BY g.effective_from DESC LIMIT 1)
WHERE r.flag <> 'unknown'
--@@
UPDATE lab_results r SET crit_low = g.critical_low, crit_high = g.critical_high
FROM lab_reference_ranges g WHERE g.id = r.range_id
--@@
UPDATE lab_results SET correction_reason = 'Legacy correction (reason not recorded)' WHERE supersedes_id IS NOT NULL
--@@
ALTER TABLE lab_results ENABLE TRIGGER lab_results_append_only
--@@
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM lab_results WHERE flag <> 'unknown' AND range_id IS NULL) THEN
    RAISE EXCEPTION '0003: some results have a flag but no matching reference range; resolve them by hand first';
  END IF;
END $$
--@@
ALTER TABLE lab_results
  DROP CONSTRAINT lab_results_report_id_fkey,
  DROP CONSTRAINT lab_results_supersedes_id_fkey,
  ALTER COLUMN entered_by SET NOT NULL,
  ALTER COLUMN created_at SET DEFAULT now(),
  ALTER COLUMN value TYPE numeric(12,4),
  ALTER COLUMN value_original TYPE numeric(14,4),
  ALTER COLUMN ref_low TYPE numeric(12,4),
  ALTER COLUMN ref_high TYPE numeric(12,4),
  ADD CONSTRAINT ux_results_id_report_test UNIQUE (id, report_id, test_code),
  ADD CONSTRAINT lab_results_correction_reason_check
    CHECK (correction_reason IS NULL OR char_length(correction_reason) BETWEEN 3 AND 300),
  ADD CONSTRAINT correction_needs_reason CHECK ((supersedes_id IS NULL) = (correction_reason IS NULL)),
  ADD CONSTRAINT not_self_superseding CHECK (supersedes_id IS DISTINCT FROM id),
  ADD CONSTRAINT unknown_iff_no_range CHECK ((flag = 'unknown') = (range_id IS NULL))
--@@
ALTER TABLE lab_results
  ADD CONSTRAINT fk_results_report FOREIGN KEY (report_id, patient_id, collected_at)
    REFERENCES lab_reports (id, patient_id, collected_at),
  ADD CONSTRAINT fk_results_supersedes FOREIGN KEY (supersedes_id, report_id, test_code)
    REFERENCES lab_results (id, report_id, test_code)
--@@
ALTER INDEX lab_results_patient_test RENAME TO ix_results_trend
--@@
ALTER INDEX lab_results_one_correction RENAME TO ux_results_supersedes
--@@
DROP INDEX lab_results_report
--@@
CREATE UNIQUE INDEX ux_results_report_test_original ON lab_results (report_id, test_code)
  WHERE supersedes_id IS NULL
--@@
CREATE INDEX ix_results_patient_collected ON lab_results (patient_id, collected_at DESC)
--@@
-- ---------------------------------------------------------------- current-results view (B3.5)
CREATE VIEW lab_results_current AS
SELECT r.* FROM lab_results r
WHERE NOT EXISTS (SELECT 1 FROM lab_results s WHERE s.supersedes_id = r.id)
--@@
-- ---------------------------------------------------------------- read model (B3.6)
ALTER TABLE patient_lab_status
  ADD COLUMN result_count integer NOT NULL DEFAULT 0,
  ADD COLUMN version integer NOT NULL DEFAULT 1,
  ADD COLUMN rules_version text NOT NULL DEFAULT 'lab-rules-0'
--@@
UPDATE patient_lab_status s SET result_count = c.n
FROM (SELECT patient_id, count(*) AS n FROM lab_results_current GROUP BY patient_id) c
WHERE c.patient_id = s.patient_id
--@@
-- 'lab-rules-0' marks rows built before rules were versioned: rebuild_status --stale-only recomputes them
ALTER TABLE patient_lab_status ALTER COLUMN rules_version DROP DEFAULT
--@@
CREATE INDEX ix_status_attention ON patient_lab_status (patient_id) WHERE has_critical OR rapid_decline
