CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := clock_timestamp(); RETURN NEW; END $$;
--@@
CREATE TABLE lab_tests (
  code           text PRIMARY KEY CHECK (code ~ '^[A-Z0-9_]{1,16}$'),
  name           text NOT NULL,
  canonical_unit text NOT NULL,
  allowed_units  jsonb NOT NULL,
  decimals       int  NOT NULL CHECK (decimals BETWEEN 0 AND 4),
  max_value      numeric NOT NULL CHECK (max_value > 0),
  sort_order     int  NOT NULL,
  CONSTRAINT lab_tests_units_object CHECK (jsonb_typeof(allowed_units) = 'object'),
  CONSTRAINT lab_tests_canonical_is_allowed CHECK (allowed_units ? canonical_unit)
)
--@@
CREATE TABLE lab_reference_ranges (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  test_code      text NOT NULL REFERENCES lab_tests(code),
  sex            text CHECK (sex IN ('M','F')),
  age_min        int  CHECK (age_min >= 0),
  age_max        int,
  low            numeric,
  high           numeric,
  critical_low   numeric,
  critical_high  numeric,
  effective_from date NOT NULL,
  CONSTRAINT lab_ranges_age_order CHECK (age_max IS NULL OR age_min IS NULL OR age_max >= age_min),
  CONSTRAINT lab_ranges_low_high CHECK (low IS NULL OR high IS NULL OR low <= high),
  CONSTRAINT lab_ranges_crit_low CHECK (critical_low IS NULL OR low IS NULL OR critical_low <= low),
  CONSTRAINT lab_ranges_crit_high CHECK (critical_high IS NULL OR high IS NULL OR critical_high >= high)
)
--@@
CREATE UNIQUE INDEX lab_ranges_key ON lab_reference_ranges
  (test_code, COALESCE(sex, '*'), COALESCE(age_min, 0), COALESCE(age_max, 200), effective_from)
--@@
CREATE TABLE lab_reports (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id   uuid NOT NULL,
  collected_at timestamptz NOT NULL,
  lab_name     text CHECK (lab_name IS NULL OR length(lab_name) <= 120),
  notes        text CHECK (notes IS NULL OR length(notes) <= 2000),
  entered_by   uuid NOT NULL,
  created_at   timestamptz NOT NULL,
  CONSTRAINT lab_reports_not_future CHECK (collected_at <= created_at + interval '5 minutes')
)
--@@
CREATE INDEX lab_reports_patient ON lab_reports (patient_id, collected_at DESC)
--@@
CREATE TABLE lab_results (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id      uuid NOT NULL REFERENCES lab_reports(id),
  patient_id     uuid NOT NULL,
  collected_at   timestamptz NOT NULL,
  test_code      text NOT NULL REFERENCES lab_tests(code),
  value          numeric NOT NULL CHECK (value >= 0),
  unit           text NOT NULL,
  value_original numeric NOT NULL CHECK (value_original >= 0),
  unit_original  text NOT NULL,
  ref_low        numeric,
  ref_high       numeric,
  flag           text NOT NULL
                 CHECK (flag IN ('normal','low','high','critical_low','critical_high','unknown')),
  supersedes_id  uuid REFERENCES lab_results(id),
  created_at     timestamptz NOT NULL
)
--@@
CREATE INDEX lab_results_patient_test ON lab_results (patient_id, test_code, collected_at DESC)
--@@
CREATE INDEX lab_results_report ON lab_results (report_id)
--@@
CREATE UNIQUE INDEX lab_results_one_correction ON lab_results (supersedes_id) WHERE supersedes_id IS NOT NULL
--@@
CREATE TABLE patient_lab_status (
  patient_id     uuid PRIMARY KEY,
  latest         jsonb NOT NULL DEFAULT '{}'::jsonb,
  egfr_category  text CHECK (egfr_category IN ('G1','G2','G3a','G3b','G4','G5')),
  uacr_category  text CHECK (uacr_category IN ('A1','A2','A3')),
  egfr_stats     jsonb,
  creat_stats    jsonb,
  egfr_spark     jsonb NOT NULL DEFAULT '[]'::jsonb,
  has_critical   boolean NOT NULL DEFAULT false,
  rapid_decline  boolean NOT NULL DEFAULT false,
  last_result_at timestamptz,
  updated_at     timestamptz NOT NULL DEFAULT clock_timestamp()
)
--@@
CREATE TRIGGER patient_lab_status_updated BEFORE UPDATE ON patient_lab_status
  FOR EACH ROW EXECUTE FUNCTION set_updated_at()
--@@
CREATE FUNCTION lab_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% on % is not allowed: lab data is append-only', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'P0001', HINT = 'LAB_APPEND_ONLY';
END $$;
--@@
CREATE TRIGGER lab_results_append_only BEFORE UPDATE OR DELETE ON lab_results
  FOR EACH ROW EXECUTE FUNCTION lab_append_only()
--@@
CREATE TRIGGER lab_reports_append_only BEFORE UPDATE OR DELETE ON lab_reports
  FOR EACH ROW EXECUTE FUNCTION lab_append_only()
