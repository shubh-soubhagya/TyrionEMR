// patient-svc DTO <-> view model. Pure functions; the only place the two vocabularies meet (CLAUDE.md §5).
import type {
  Allergy,
  AllergyStatus,
  Condition,
  Encounter,
  EncounterDx,
  EncounterType,
  Med,
  Patient,
  Vitals,
} from '../../data/models';
import type { EgfrCat, Sex } from '../../clinical/lab-tests';
import type {
  AllergyDto,
  AllergyStatusDto,
  ConditionDto,
  DiagnosisDto,
  EncounterDetailDto,
  EncounterListItemDto,
  EncounterWriteDto,
  MedicationCreateDto,
  MedicationDto,
  PatientCreateDto,
  PatientDetailDto,
  PatientListItemDto,
  PatientPatchDto,
  RouteCodeDto,
  VitalsDto,
  VitalsInDto,
} from '../dto/patient.dto';

/** Shown wherever a clinician name is missing (CLAUDE.md §6). */
export const NOT_DOCUMENTED = 'Not documented';

// ---- allergy status: 'has' <-> 'has_allergies' ----------------------------------------------------
export function allergyStatusFromDto(s: AllergyStatusDto): AllergyStatus {
  return s === 'has_allergies' ? 'has' : s;
}

export function allergyStatusToDto(s: AllergyStatus): AllergyStatusDto {
  return s === 'has' ? 'has_allergies' : s;
}

// ---- medication route: label <-> code -------------------------------------------------------------
const ROUTE_LABELS: Readonly<Record<RouteCodeDto, string>> = {
  oral: 'Oral',
  sc: 'SC',
  iv: 'IV',
  topical: 'Topical',
  inhaled: 'Inhaled',
  other: 'Other',
};

export const ROUTE_OPTIONS: readonly string[] = Object.values(ROUTE_LABELS);

export function routeLabel(code: string): string {
  return ROUTE_LABELS[code as RouteCodeDto] ?? ROUTE_LABELS.other;
}

export function routeCode(label: string): RouteCodeDto {
  const hit = (Object.entries(ROUTE_LABELS) as [RouteCodeDto, string][]).find(
    ([, l]) => l.toLowerCase() === label.trim().toLowerCase(),
  );
  return hit ? hit[0] : 'other';
}

const orEmpty = (v: string | null | undefined): string => v ?? '';
const orNull = (v: string | null | undefined): string | null => {
  const t = (v ?? '').trim();
  return t === '' ? null : t;
};

// ---- patient ---------------------------------------------------------------------------------------
export function patientFromList(d: PatientListItemDto): Patient {
  return {
    id: d.id,
    mrn: d.mrn,
    first: d.first_name,
    last: d.last_name,
    dob: '',
    sex: d.sex as Sex,
    phone: orEmpty(d.phone),
    email: '',
    address: '',
    pmh: '',
    fh: '',
    sh: '',
    allergyStatus: allergyStatusFromDto(d.allergy_status),
    ckd: (d.established_ckd_stage as EgfrCat | null) ?? null,
    version: 0,
    deletedAt: null,
    createdAt: '',
  };
}

export function patientFromDetail(d: PatientDetailDto): Patient {
  return {
    id: d.id,
    mrn: d.mrn,
    first: d.first_name,
    last: d.last_name,
    dob: d.date_of_birth,
    sex: d.sex as Sex,
    phone: orEmpty(d.phone),
    email: orEmpty(d.email),
    address: orEmpty(d.address),
    pmh: orEmpty(d.past_medical_history),
    fh: orEmpty(d.family_history),
    sh: orEmpty(d.social_history),
    allergyStatus: allergyStatusFromDto(d.allergy_status),
    ckd: (d.established_ckd_stage as EgfrCat | null) ?? null,
    version: d.version,
    deletedAt: null,
    createdAt: d.created_at,
  };
}

export interface PatientForm {
  first: string;
  last: string;
  dob: string;
  sex: Sex;
  phone: string;
  email: string;
  address: string;
  pmh: string;
  fh: string;
  sh: string;
  allergyStatus: 'unknown' | 'nka';
}

export function patientCreateToDto(f: PatientForm): PatientCreateDto {
  return {
    first_name: f.first.trim(),
    last_name: f.last.trim(),
    date_of_birth: f.dob,
    sex: f.sex,
    phone: orNull(f.phone),
    email: orNull(f.email),
    address: orNull(f.address),
    past_medical_history: orNull(f.pmh),
    family_history: orNull(f.fh),
    social_history: orNull(f.sh),
    allergy_status: f.allergyStatus,
  };
}

export function patientPatchToDto(f: PatientForm, version: number): PatientPatchDto {
  const { allergy_status: _ignored, ...rest } = patientCreateToDto(f);
  void _ignored;
  return { ...rest, version };
}

// ---- conditions ------------------------------------------------------------------------------------
export function conditionFromDto(d: ConditionDto, patientId: string): Condition {
  return {
    id: d.id,
    patientId,
    icd10: orEmpty(d.icd10_code),
    desc: d.description,
    category: d.category === 'nephrology' ? 'nephrology' : 'comorbidity',
    isPrimary: d.is_primary,
    status: d.status === 'resolved' ? 'resolved' : 'active',
    onset: orEmpty(d.onset_date),
    sourceEncounterId: d.source_encounter_id,
    deletedAt: null,
  };
}

// ---- medications -----------------------------------------------------------------------------------
export function medFromDto(d: MedicationDto, patientId: string): Med {
  return {
    id: d.id,
    patientId,
    name: d.name,
    dose: d.dose,
    route: routeLabel(d.route),
    freq: d.frequency,
    start: orEmpty(d.start_date),
    end: d.end_date,
    status: d.status === 'discontinued' ? 'discontinued' : 'active',
  };
}

export function medToCreateDto(m: {
  name: string;
  dose: string;
  route: string;
  freq: string;
  start: string;
  end: string | null;
}): MedicationCreateDto {
  return {
    name: m.name.trim(),
    dose: m.dose.trim(),
    frequency: m.freq.trim(),
    route: routeCode(m.route),
    start_date: orNull(m.start),
    end_date: orNull(m.end),
  };
}

// ---- allergies -------------------------------------------------------------------------------------
export function allergyFromDto(d: AllergyDto, patientId: string): Allergy {
  const severity = d.severity === 'mild' || d.severity === 'severe' ? d.severity : 'moderate';
  return { id: d.id, patientId, allergen: d.allergen, reaction: orEmpty(d.reaction), severity };
}

// ---- encounters ------------------------------------------------------------------------------------
export function vitalsFromDto(v: VitalsDto | null): Vitals | null {
  return v === null
    ? null
    : {
        sys: v.systolic_bp,
        dia: v.diastolic_bp,
        hr: v.heart_rate,
        temp: v.temperature_c,
        wt: v.weight_kg,
      };
}

export function vitalsToDto(v: Vitals | null): VitalsInDto | null {
  if (v === null) return null;
  return {
    systolic_bp: v.sys,
    diastolic_bp: v.dia,
    heart_rate: v.hr,
    temperature_c: v.temp,
    weight_kg: v.wt,
  };
}

export function diagnosisFromDto(d: DiagnosisDto): EncounterDx {
  return {
    icd: orEmpty(d.icd10_code),
    desc: d.description,
    condId: d.condition_id,
    prob: d.add_to_problem_list,
  };
}

const encounterType = (t: string): EncounterType =>
  t === 'new' || t === 'emergency' ? t : 'follow_up';

export function encounterFromDetail(d: EncounterDetailDto): Encounter {
  return {
    id: d.id,
    patientId: d.patient_id,
    date: d.encounter_date,
    type: encounterType(d.encounter_type),
    clinician: d.clinician_name ?? NOT_DOCUMENTED,
    cc: orEmpty(d.chief_complaint),
    symptoms: [...d.symptoms],
    exam: orEmpty(d.examination_notes),
    assessment: orEmpty(d.assessment),
    plan: orEmpty(d.plan),
    followUp: orEmpty(d.follow_up_date),
    status: d.status === 'final' ? 'final' : 'draft',
    vitals: vitalsFromDto(d.vitals),
    diagnoses: d.diagnoses.map(diagnosisFromDto),
    version: d.version,
    deletedAt: null,
    ...(d.finalized_at ? { finalizedAt: d.finalized_at } : {}),
  };
}

/** A list row has no diagnoses, symptoms or notes; those arrive when the row is opened. */
export function encounterFromListItem(d: EncounterListItemDto, patientId: string): Encounter {
  const b = d.vitals_brief;
  return {
    id: d.id,
    patientId,
    date: d.encounter_date,
    type: encounterType(d.encounter_type),
    clinician: d.clinician_name ?? NOT_DOCUMENTED,
    cc: orEmpty(d.chief_complaint),
    symptoms: [],
    exam: '',
    assessment: orEmpty(d.assessment),
    plan: '',
    followUp: orEmpty(d.follow_up_date),
    status: d.status === 'final' ? 'final' : 'draft',
    vitals:
      b === null
        ? null
        : { sys: b.systolic_bp, dia: b.diastolic_bp, hr: b.heart_rate, temp: null, wt: null },
    diagnoses: [],
    version: 0,
    deletedAt: null,
  };
}

export function encounterToWriteDto(e: {
  date: string;
  type: EncounterType;
  cc: string;
  symptoms: readonly string[];
  exam: string;
  assessment: string;
  plan: string;
  followUp: string;
  vitals: Vitals | null;
  diagnoses: readonly {
    icd: string;
    desc: string;
    prob: boolean;
    category?: 'nephrology' | 'comorbidity' | null;
  }[];
  status: 'draft' | 'final';
}): EncounterWriteDto {
  return {
    encounter_date: e.date,
    encounter_type: e.type,
    chief_complaint: orNull(e.cc),
    symptoms: e.symptoms,
    examination_notes: orNull(e.exam),
    assessment: orNull(e.assessment),
    plan: orNull(e.plan),
    follow_up_date: orNull(e.followUp),
    status: e.status,
    vitals: vitalsToDto(e.vitals),
    diagnoses: e.diagnoses.map((d) => ({
      icd10_code: orNull(d.icd),
      description: d.desc.trim(),
      add_to_problem_list: d.prob,
      ...(d.category ? { category: d.category } : {}),
    })),
  };
}
