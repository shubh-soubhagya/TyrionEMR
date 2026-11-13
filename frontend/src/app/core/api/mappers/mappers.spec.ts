import { describe, expect, it } from 'vitest';
import type { PatientDetailDto } from '../dto/patient.dto';
import type { ResultDto } from '../dto/lab.dto';
import { labResultFromDto } from './lab.mapper';
import {
  NOT_DOCUMENTED,
  allergyFromDto,
  allergyStatusFromDto,
  allergyStatusToDto,
  conditionFromDto,
  encounterFromDetail,
  encounterToWriteDto,
  medFromDto,
  medToCreateDto,
  patientCreateToDto,
  patientFromDetail,
  routeCode,
  routeLabel,
  vitalsFromDto,
  vitalsToDto,
} from './patient.mapper';

describe('allergy status', () => {
  it('maps has <-> has_allergies and leaves the others alone', () => {
    expect(allergyStatusFromDto('has_allergies')).toBe('has');
    expect(allergyStatusFromDto('nka')).toBe('nka');
    expect(allergyStatusFromDto('unknown')).toBe('unknown');
    expect(allergyStatusToDto('has')).toBe('has_allergies');
    expect(allergyStatusToDto('nka')).toBe('nka');
  });
});

describe('medication route', () => {
  it.each([
    ['oral', 'Oral'],
    ['sc', 'SC'],
    ['iv', 'IV'],
    ['topical', 'Topical'],
    ['inhaled', 'Inhaled'],
    ['other', 'Other'],
  ])('%s <-> %s', (code, label) => {
    expect(routeLabel(code)).toBe(label);
    expect(routeCode(label)).toBe(code);
  });

  it('falls back to other for an unknown value', () => {
    expect(routeLabel('rectal')).toBe('Other');
    expect(routeCode('Intramuscular')).toBe('other');
  });
});

describe('medication', () => {
  it('renames freq, start and end and turns the route into a label', () => {
    const m = medFromDto(
      {
        id: 'm1',
        name: 'Losartan',
        dose: '50 mg',
        route: 'oral',
        frequency: 'Once daily',
        start_date: '2025-01-02',
        end_date: null,
        status: 'active',
        created_at: '',
        updated_at: '',
      },
      'p1',
    );
    expect(m).toMatchObject({
      freq: 'Once daily',
      start: '2025-01-02',
      end: null,
      route: 'Oral',
      patientId: 'p1',
    });
    expect(
      medToCreateDto({
        name: ' Losartan ',
        dose: '50 mg',
        route: 'SC',
        freq: 'Weekly',
        start: '',
        end: null,
      }),
    ).toEqual({
      name: 'Losartan',
      dose: '50 mg',
      frequency: 'Weekly',
      route: 'sc',
      start_date: null,
      end_date: null,
    });
  });
});

describe('condition', () => {
  it('maps icd10_code, description and onset_date', () => {
    const c = conditionFromDto(
      {
        id: 'c1',
        icd10_code: 'N18.4',
        description: 'CKD stage 4',
        category: 'nephrology',
        is_primary: true,
        status: 'active',
        onset_date: '2020-05-01',
        resolved_date: null,
        source_encounter_id: null,
        created_at: '',
        updated_at: '',
      },
      'p1',
    );
    expect(c).toMatchObject({
      icd10: 'N18.4',
      desc: 'CKD stage 4',
      onset: '2020-05-01',
      isPrimary: true,
    });
  });
});

describe('allergy', () => {
  it('keeps severity and fills a missing reaction with an empty string', () => {
    expect(
      allergyFromDto(
        { id: 'a', allergen: 'Latex', reaction: null, severity: 'severe', created_at: '' },
        'p',
      ),
    ).toEqual({
      id: 'a',
      patientId: 'p',
      allergen: 'Latex',
      reaction: '',
      severity: 'severe',
    });
  });
});

describe('patient', () => {
  const detail: PatientDetailDto = {
    id: 'p1',
    mrn: 'PT-000101',
    first_name: 'Ramesh',
    last_name: 'Kulkarni',
    age: 61,
    sex: 'M',
    phone: null,
    email: null,
    address: null,
    date_of_birth: '1965-05-02',
    past_medical_history: 'HTN',
    family_history: null,
    social_history: null,
    allergy_status: 'has_allergies',
    established_ckd_stage: 'G3b',
    last_visit: null,
    primary_diagnosis: null,
    allergy_summary: [],
    counts: { conditions: 0, active_conditions: 0, active_medications: 0, encounters: 0 },
    next_follow_up: null,
    version: 4,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '',
  };

  it('maps the names, allergy status, stage and version', () => {
    expect(patientFromDetail(detail)).toMatchObject({
      first: 'Ramesh',
      last: 'Kulkarni',
      dob: '1965-05-02',
      pmh: 'HTN',
      fh: '',
      allergyStatus: 'has',
      ckd: 'G3b',
      version: 4,
    });
  });

  it('sends snake_case names, trims text and turns blanks into null', () => {
    const dto = patientCreateToDto({
      first: ' Asha ',
      last: 'Rao',
      dob: '1980-01-01',
      sex: 'F',
      phone: '  ',
      email: '',
      address: '',
      pmh: 'x',
      fh: '',
      sh: '',
      allergyStatus: 'nka',
    });
    expect(dto).toEqual({
      first_name: 'Asha',
      last_name: 'Rao',
      date_of_birth: '1980-01-01',
      sex: 'F',
      phone: null,
      email: null,
      address: null,
      past_medical_history: 'x',
      family_history: null,
      social_history: null,
      allergy_status: 'nka',
    });
  });
});

describe('vitals', () => {
  it('renames sys, dia, hr, temp, wt both ways', () => {
    const wire = {
      systolic_bp: 130,
      diastolic_bp: 80,
      heart_rate: 70,
      temperature_c: 36.8,
      weight_kg: 71,
    };
    const view = { sys: 130, dia: 80, hr: 70, temp: 36.8, wt: 71 };
    expect(vitalsFromDto(wire)).toEqual(view);
    expect(vitalsToDto(view)).toEqual(wire);
    expect(vitalsFromDto(null)).toBeNull();
  });
});

describe('encounter', () => {
  it('renames the fields and shows "Not documented" for a missing clinician', () => {
    const e = encounterFromDetail({
      id: 'e1',
      patient_id: 'p1',
      encounter_date: '2026-10-01',
      encounter_type: 'follow_up',
      clinician_id: 'u',
      clinician_name: null,
      chief_complaint: 'Review',
      symptoms: ['fatigue'],
      examination_notes: 'ok',
      assessment: null,
      plan: null,
      follow_up_date: '2026-12-01',
      status: 'final',
      vitals: null,
      diagnoses: [
        {
          seq: 1,
          icd10_code: 'N18.4',
          description: 'CKD 4',
          category: 'nephrology',
          add_to_problem_list: true,
          condition_id: 'c1',
        },
      ],
      finalized_at: '2026-10-01T10:00:00Z',
      finalized_by: 'u',
      version: 3,
      created_at: '',
      updated_at: '',
    });
    expect(e).toMatchObject({
      date: '2026-10-01',
      clinician: NOT_DOCUMENTED,
      cc: 'Review',
      exam: 'ok',
      followUp: '2026-12-01',
      status: 'final',
      version: 3,
      finalizedAt: '2026-10-01T10:00:00Z',
    });
    expect(e.diagnoses[0]).toMatchObject({ icd: 'N18.4', desc: 'CKD 4', condId: 'c1', prob: true });
  });

  it('writes chief_complaint, examination_notes, follow_up_date and the add_to_problem_list flag', () => {
    const dto = encounterToWriteDto({
      date: '2026-11-01',
      type: 'new',
      cc: 'Cough',
      symptoms: [],
      exam: '',
      assessment: 'a',
      plan: '',
      followUp: '',
      vitals: null,
      diagnoses: [{ icd: '', desc: 'Hypertension', prob: true, category: 'comorbidity' }],
      status: 'draft',
    });
    expect(dto).toMatchObject({
      encounter_date: '2026-11-01',
      chief_complaint: 'Cough',
      examination_notes: null,
      follow_up_date: null,
      status: 'draft',
      diagnoses: [
        {
          icd10_code: null,
          description: 'Hypertension',
          add_to_problem_list: true,
          category: 'comorbidity',
        },
      ],
    });
  });
});

describe('lab result', () => {
  it('renames test_code, ref_low, ref_high, value_original, unit_original and collected_at', () => {
    const dto: ResultDto = {
      id: 'r1',
      report_id: 'rep1',
      test_code: 'CREAT',
      test_name: 'Serum creatinine',
      collected_at: '2026-10-01T09:00:00Z',
      value: 1.5,
      unit: 'mg/dL',
      value_original: 133,
      unit_original: 'µmol/L',
      ref_low: 0.7,
      ref_high: 1.3,
      flag: 'high',
      lab_name: 'Lab',
      is_correction: false,
      superseded: false,
    };
    expect(labResultFromDto(dto, 'p1')).toEqual({
      id: 'r1',
      reportId: 'rep1',
      patientId: 'p1',
      collectedAt: '2026-10-01T09:00:00Z',
      test: 'CREAT',
      value: 1.5,
      unit: 'mg/dL',
      valueOriginal: 133,
      unitOriginal: 'µmol/L',
      refLow: 0.7,
      refHigh: 1.3,
      flag: 'high',
    });
  });

  it('treats an unknown flag as unknown', () => {
    expect(labResultFromDto({ flag: 'weird' } as ResultDto, 'p').flag).toBe('unknown');
  });
});
