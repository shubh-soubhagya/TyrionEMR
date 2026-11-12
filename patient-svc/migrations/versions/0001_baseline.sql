CREATE EXTENSION IF NOT EXISTS pg_trgm;
--@@
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;
--@@
CREATE SEQUENCE patient_mrn_seq START WITH 101 INCREMENT BY 1 NO CYCLE;
--@@
CREATE TABLE patients (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mrn                    text NOT NULL DEFAULT ('PT-' || lpad(nextval('patient_mrn_seq')::text, 6, '0')),
  first_name             text NOT NULL,
  last_name              text NOT NULL,
  search_name            text GENERATED ALWAYS AS (lower(first_name || ' ' || last_name)) STORED,
  date_of_birth          date NOT NULL,
  sex                    text NOT NULL,
  phone                  text,
  email                  text,
  address                text,
  past_medical_history   text,
  family_history         text,
  social_history         text,
  allergy_status         text NOT NULL DEFAULT 'unknown',
  established_ckd_stage  text,
  version                integer NOT NULL DEFAULT 1,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  created_by             uuid,
  updated_by             uuid,
  deleted_at             timestamptz,

  CONSTRAINT patients_mrn_format     CHECK (mrn ~ '^PT-[0-9]{6,}$'),
  CONSTRAINT patients_first_len      CHECK (char_length(btrim(first_name)) BETWEEN 1 AND 60),
  CONSTRAINT patients_last_len       CHECK (char_length(btrim(last_name))  BETWEEN 1 AND 60),
  CONSTRAINT patients_dob_floor      CHECK (date_of_birth >= DATE '1900-01-01'),
  CONSTRAINT patients_sex            CHECK (sex IN ('M','F','O')),
  CONSTRAINT patients_phone          CHECK (phone IS NULL OR phone ~ '^[+0-9 ()-]{7,20}$'),
  CONSTRAINT patients_email_len      CHECK (email IS NULL OR char_length(email) <= 254),
  CONSTRAINT patients_address_len    CHECK (address IS NULL OR char_length(address) <= 300),
  CONSTRAINT patients_pmh_len        CHECK (past_medical_history IS NULL OR char_length(past_medical_history) <= 4000),
  CONSTRAINT patients_fh_len         CHECK (family_history IS NULL OR char_length(family_history) <= 4000),
  CONSTRAINT patients_sh_len         CHECK (social_history IS NULL OR char_length(social_history) <= 4000),
  CONSTRAINT patients_allergy_status CHECK (allergy_status IN ('unknown','nka','has_allergies')),
  CONSTRAINT patients_ckd_stage      CHECK (established_ckd_stage IS NULL
                                            OR established_ckd_stage IN ('G1','G2','G3a','G3b','G4','G5')),
  CONSTRAINT patients_version        CHECK (version >= 1)
);
--@@
ALTER SEQUENCE patient_mrn_seq OWNED BY patients.mrn;
--@@
CREATE UNIQUE INDEX patients_mrn_uq        ON patients (mrn text_pattern_ops);
--@@
CREATE INDEX patients_search_trgm          ON patients USING gin (search_name gin_trgm_ops) WHERE deleted_at IS NULL;
--@@
CREATE INDEX patients_name_sort            ON patients (lower(last_name), lower(first_name)) WHERE deleted_at IS NULL;
--@@
CREATE INDEX patients_dob                  ON patients (date_of_birth) WHERE deleted_at IS NULL;
--@@
CREATE INDEX patients_stage                ON patients (established_ckd_stage) WHERE deleted_at IS NULL;
--@@
CREATE TRIGGER patients_updated_at BEFORE UPDATE ON patients FOR EACH ROW EXECUTE FUNCTION set_updated_at();
--@@
CREATE TABLE encounters (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id         uuid NOT NULL REFERENCES patients(id),
  encounter_date     timestamptz NOT NULL,
  encounter_type     text NOT NULL DEFAULT 'follow_up',
  clinician_id       uuid NOT NULL,
  clinician_name     text NOT NULL,
  chief_complaint    text,
  symptoms           text[] NOT NULL DEFAULT '{}',
  examination_notes  text,
  assessment         text,
  plan               text,
  follow_up_date     date,
  status             text NOT NULL DEFAULT 'draft',
  version            integer NOT NULL DEFAULT 1,
  finalized_at       timestamptz,
  finalized_by       uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  created_by         uuid NOT NULL,
  updated_by         uuid,
  deleted_at         timestamptz,

  CONSTRAINT encounters_type         CHECK (encounter_type IN ('new','follow_up','emergency')),
  CONSTRAINT encounters_status       CHECK (status IN ('draft','final')),
  CONSTRAINT encounters_cc_len       CHECK (chief_complaint IS NULL OR char_length(chief_complaint) <= 200),
  CONSTRAINT encounters_exam_len     CHECK (examination_notes IS NULL OR char_length(examination_notes) <= 4000),
  CONSTRAINT encounters_assess_len   CHECK (assessment IS NULL OR char_length(assessment) <= 4000),
  CONSTRAINT encounters_plan_len     CHECK (plan IS NULL OR char_length(plan) <= 4000),
  CONSTRAINT encounters_symptoms_n   CHECK (cardinality(symptoms) <= 30),
  CONSTRAINT encounters_final_stamp  CHECK ((status = 'final') = (finalized_at IS NOT NULL)),
  CONSTRAINT encounters_final_fields CHECK (status <> 'final' OR (
        coalesce(btrim(chief_complaint), '') <> ''
    AND coalesce(btrim(assessment), '')      <> ''
    AND coalesce(btrim(plan), '')            <> '')),
  CONSTRAINT encounters_delete_draft CHECK (deleted_at IS NULL OR status = 'draft'),
  CONSTRAINT encounters_version      CHECK (version >= 1)
);
--@@
CREATE INDEX encounters_patient_date    ON encounters (patient_id, encounter_date DESC) WHERE deleted_at IS NULL;
--@@
CREATE INDEX encounters_patient_final   ON encounters (patient_id, encounter_date DESC) WHERE status = 'final' AND deleted_at IS NULL;
--@@
CREATE INDEX encounters_status_date     ON encounters (status, encounter_date DESC) WHERE deleted_at IS NULL;
--@@
CREATE INDEX encounters_followup        ON encounters (follow_up_date) WHERE status = 'final' AND deleted_at IS NULL;
--@@
CREATE TRIGGER encounters_updated_at BEFORE UPDATE ON encounters FOR EACH ROW EXECUTE FUNCTION set_updated_at();
--@@
CREATE TABLE patient_conditions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id           uuid NOT NULL REFERENCES patients(id),
  icd10_code           text,
  description          text NOT NULL,
  category             text NOT NULL,
  is_primary           boolean NOT NULL DEFAULT false,
  status               text NOT NULL DEFAULT 'active',
  onset_date           date,
  resolved_date        date,
  source_encounter_id  uuid REFERENCES encounters(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  created_by           uuid,
  updated_by           uuid,
  deleted_at           timestamptz,

  CONSTRAINT conditions_icd10      CHECK (icd10_code IS NULL OR icd10_code ~ '^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$'),
  CONSTRAINT conditions_desc_len   CHECK (char_length(btrim(description)) BETWEEN 1 AND 160),
  CONSTRAINT conditions_category   CHECK (category IN ('nephrology','comorbidity')),
  CONSTRAINT conditions_status     CHECK (status IN ('active','resolved')),
  CONSTRAINT conditions_primary    CHECK (NOT is_primary OR status = 'active'),
  CONSTRAINT conditions_resolved   CHECK ((status = 'resolved') = (resolved_date IS NOT NULL)),
  CONSTRAINT conditions_dates      CHECK (resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date)
);
--@@
CREATE UNIQUE INDEX conditions_one_primary ON patient_conditions (patient_id)
  WHERE is_primary AND status = 'active' AND deleted_at IS NULL;
--@@
CREATE INDEX conditions_patient     ON patient_conditions (patient_id, status) WHERE deleted_at IS NULL;
--@@
CREATE INDEX conditions_patient_icd ON patient_conditions (patient_id, icd10_code) WHERE deleted_at IS NULL;
--@@
CREATE TRIGGER conditions_updated_at BEFORE UPDATE ON patient_conditions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
--@@
CREATE TABLE encounter_vitals (
  encounter_id   uuid PRIMARY KEY REFERENCES encounters(id),
  systolic_bp    integer,
  diastolic_bp   integer,
  heart_rate     integer,
  temperature_c  numeric(4,1),
  weight_kg      numeric(5,1),
  CONSTRAINT vitals_sys    CHECK (systolic_bp   IS NULL OR systolic_bp   BETWEEN 50 AND 300),
  CONSTRAINT vitals_dia    CHECK (diastolic_bp  IS NULL OR diastolic_bp  BETWEEN 20 AND 200),
  CONSTRAINT vitals_hr     CHECK (heart_rate    IS NULL OR heart_rate    BETWEEN 20 AND 300),
  CONSTRAINT vitals_temp   CHECK (temperature_c IS NULL OR temperature_c BETWEEN 30 AND 45),
  CONSTRAINT vitals_wt     CHECK (weight_kg     IS NULL OR weight_kg     BETWEEN 1 AND 500),
  CONSTRAINT vitals_bp     CHECK (systolic_bp IS NULL OR diastolic_bp IS NULL OR systolic_bp > diastolic_bp),
  CONSTRAINT vitals_any    CHECK (num_nonnulls(systolic_bp, diastolic_bp, heart_rate, temperature_c, weight_kg) >= 1)
);
--@@
CREATE TABLE encounter_diagnoses (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encounter_id         uuid NOT NULL REFERENCES encounters(id),
  seq                  smallint NOT NULL,
  icd10_code           text,
  description          text NOT NULL,
  add_to_problem_list  boolean NOT NULL DEFAULT false,
  condition_id         uuid REFERENCES patient_conditions(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT dx_icd10    CHECK (icd10_code IS NULL OR icd10_code ~ '^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$'),
  CONSTRAINT dx_desc_len CHECK (char_length(btrim(description)) BETWEEN 1 AND 160),
  CONSTRAINT dx_seq_uq   UNIQUE (encounter_id, seq)
);
--@@
CREATE INDEX dx_condition ON encounter_diagnoses (condition_id) WHERE condition_id IS NOT NULL;
--@@
CREATE TABLE medications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES patients(id),
  name        text NOT NULL,
  dose        text NOT NULL,
  route       text NOT NULL DEFAULT 'oral',
  frequency   text NOT NULL,
  start_date  date,
  end_date    date,
  status      text NOT NULL DEFAULT 'active',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  updated_by  uuid,
  deleted_at  timestamptz,
  CONSTRAINT meds_name_len     CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
  CONSTRAINT meds_dose_len     CHECK (char_length(btrim(dose)) BETWEEN 1 AND 40),
  CONSTRAINT meds_freq_len     CHECK (char_length(btrim(frequency)) BETWEEN 1 AND 80),
  CONSTRAINT meds_route        CHECK (route IN ('oral','sc','iv','topical','inhaled','other')),
  CONSTRAINT meds_status       CHECK (status IN ('active','discontinued')),
  CONSTRAINT meds_dates        CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
  CONSTRAINT meds_disc_has_end CHECK (status <> 'discontinued' OR end_date IS NOT NULL)
);
--@@
CREATE INDEX meds_patient        ON medications (patient_id) WHERE deleted_at IS NULL;
--@@
CREATE INDEX meds_patient_active ON medications (patient_id) WHERE status = 'active' AND deleted_at IS NULL;
--@@
CREATE TRIGGER meds_updated_at BEFORE UPDATE ON medications FOR EACH ROW EXECUTE FUNCTION set_updated_at();
--@@
CREATE TABLE allergies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES patients(id),
  allergen    text NOT NULL,
  reaction    text,
  severity    text NOT NULL DEFAULT 'moderate',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  deleted_at  timestamptz,
  deleted_by  uuid,
  CONSTRAINT allergies_allergen_len CHECK (char_length(btrim(allergen)) BETWEEN 1 AND 80),
  CONSTRAINT allergies_reaction_len CHECK (reaction IS NULL OR char_length(reaction) <= 200),
  CONSTRAINT allergies_severity     CHECK (severity IN ('mild','moderate','severe'))
);
--@@
CREATE UNIQUE INDEX allergies_one_per_allergen ON allergies (patient_id, lower(btrim(allergen))) WHERE deleted_at IS NULL;
--@@
CREATE TRIGGER allergies_updated_at BEFORE UPDATE ON allergies FOR EACH ROW EXECUTE FUNCTION set_updated_at();
--@@
CREATE TABLE audit_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id     uuid NOT NULL,
  patient_id   uuid,
  action       text NOT NULL,
  resource     text NOT NULL,
  resource_id  uuid,
  at           timestamptz NOT NULL DEFAULT now(),
  request_id   text,
  details      jsonb NOT NULL DEFAULT '{}'::jsonb
);
--@@
CREATE INDEX audit_patient_at ON audit_events (patient_id, at DESC);
--@@
CREATE INDEX audit_actor_at   ON audit_events (actor_id, at DESC);
--@@
CREATE OR REPLACE FUNCTION encounters_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'encounters are never hard-deleted' USING ERRCODE = 'P0001', HINT = 'NO_HARD_DELETE';
  END IF;
  IF OLD.status = 'final' THEN
    RAISE EXCEPTION 'encounter % is final and immutable', OLD.id USING ERRCODE = 'P0001', HINT = 'ENCOUNTER_FINAL';
  END IF;
  RETURN NEW;
END $$;
--@@
CREATE TRIGGER encounters_guard BEFORE UPDATE OR DELETE ON encounters
  FOR EACH ROW EXECUTE FUNCTION encounters_guard();
--@@
CREATE OR REPLACE FUNCTION encounter_children_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
  SELECT status INTO s FROM encounters
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.encounter_id ELSE NEW.encounter_id END;
  IF s = 'final' THEN
    RAISE EXCEPTION 'children of a final encounter are immutable' USING ERRCODE = 'P0001', HINT = 'ENCOUNTER_FINAL';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
--@@
CREATE TRIGGER vitals_guard BEFORE INSERT OR UPDATE OR DELETE ON encounter_vitals
  FOR EACH ROW EXECUTE FUNCTION encounter_children_guard();
--@@
CREATE TRIGGER dx_guard BEFORE INSERT OR UPDATE OR DELETE ON encounter_diagnoses
  FOR EACH ROW EXECUTE FUNCTION encounter_children_guard();
--@@
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'P0001', HINT = 'AUDIT_APPEND_ONLY';
END $$;
--@@
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
--@@
CREATE OR REPLACE FUNCTION no_hard_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows are soft-deleted only', TG_TABLE_NAME USING ERRCODE = 'P0001', HINT = 'NO_HARD_DELETE';
END $$;
--@@
CREATE TRIGGER patients_no_delete   BEFORE DELETE ON patients           FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
--@@
CREATE TRIGGER conditions_no_delete BEFORE DELETE ON patient_conditions FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
--@@
CREATE TRIGGER meds_no_delete       BEFORE DELETE ON medications        FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
--@@
CREATE TRIGGER allergies_no_delete  BEFORE DELETE ON allergies          FOR EACH ROW EXECUTE FUNCTION no_hard_delete();
