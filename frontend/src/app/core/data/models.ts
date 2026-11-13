import { EgfrCat, Flag, Sex, TestCode } from '../clinical/lab-tests';

export type AllergyStatus = 'unknown' | 'nka' | 'has';
export type CkdStage = EgfrCat;

export interface Patient {
  id: string;
  mrn: string;
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
  allergyStatus: AllergyStatus;
  ckd: CkdStage | null;
  version: number;
  deletedAt: string | null;
  createdAt: string;
}

export interface Condition {
  id: string;
  patientId: string;
  icd10: string;
  desc: string;
  category: 'nephrology' | 'comorbidity';
  isPrimary: boolean;
  status: 'active' | 'resolved';
  onset: string;
  sourceEncounterId: string | null;
  deletedAt: string | null;
}

export interface Med {
  id: string;
  patientId: string;
  name: string;
  dose: string;
  route: string;
  freq: string;
  start: string;
  end: string | null;
  status: 'active' | 'discontinued';
}

export interface Allergy {
  id: string;
  patientId: string;
  allergen: string;
  reaction: string;
  severity: 'mild' | 'moderate' | 'severe';
}

export interface Vitals {
  sys: number | null;
  dia: number | null;
  hr: number | null;
  temp: number | null;
  wt: number | null;
}

export interface EncounterDx {
  icd: string;
  desc: string;
  condId: string | null;
  /** "Add to problem list" (the server links or creates the condition when the encounter is finalized). */
  prob?: boolean;
}

export type EncounterType = 'new' | 'follow_up' | 'emergency';

export interface Encounter {
  id: string;
  patientId: string;
  date: string;
  type: EncounterType;
  clinician: string;
  cc: string;
  symptoms: string[];
  exam: string;
  assessment: string;
  plan: string;
  followUp: string;
  status: 'draft' | 'final';
  vitals: Vitals | null;
  diagnoses: EncounterDx[];
  version: number;
  deletedAt: string | null;
  finalizedAt?: string;
}

export interface LabResult {
  id: string;
  reportId: string;
  patientId: string;
  collectedAt: string;
  test: TestCode;
  value: number;
  unit: string;
  valueOriginal: number;
  unitOriginal: string;
  refLow: number | null;
  refHigh: number | null;
  flag: Flag;
  /** The laboratory that reported it (lab-svc `lab_name`). */
  labName?: string;
}
