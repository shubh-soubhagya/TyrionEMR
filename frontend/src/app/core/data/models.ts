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

export interface LabReport {
  id: string;
  patientId: string;
  collectedAt: string;
  labName: string;
  notes: string;
  enteredBy: string;
  createdAt: string;
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
}

export interface Db {
  patients: Patient[];
  conditions: Condition[];
  meds: Med[];
  allergies: Allergy[];
  encounters: Encounter[];
  labReports: LabReport[];
  labResults: LabResult[];
  aiSummaries: AiSummaryRecord[];
  config: { toolsEnabled: boolean; maxToolIterations: number; dailyQuota: number };
}

export interface GapFinding {
  code: string;
  sev: 'high' | 'medium' | 'low';
  kind: 'missing' | 'inconsistent';
  message: string;
  refs: string[];
}

export interface FollowUpItem {
  consideration: string;
  rationale: string;
  source_refs: string[];
}

export interface Narrative {
  history_summary: { text: string; source_refs: string[] };
  comorbidity_summary: { text: string; source_refs: string[] };
  trend_commentary: { text: string; source_refs: string[] };
  abnormal_commentary: { text: string; source_refs: string[] };
  follow_up_considerations: FollowUpItem[];
  not_documented: string[];
}

export interface AiSummaryRecord {
  id: string;
  patientId: string;
  status: 'completed' | 'degraded';
  provider: string;
  model: string;
  contextHash: string;
  contextSnapshot: unknown;
  output: Narrative | null;
  facts: {
    ckd: {
      established: CkdStage | null;
      egfrCat: EgfrCat | null;
      uacrCat: string | null;
    };
    abnormal: { test: TestCode; value: number; unit: string; flag: Flag; date: string }[];
    trends: Record<'EGFR' | 'CREAT', TrendLite>;
  };
  gaps: GapFinding[];
  attempts: number;
  validation: { refsTotal: number; refsOk: number; lint: number } | null;
  errorCode: string | null;
  createdAt: string;
}

export interface TrendLite {
  n: number;
  first?: number;
  last?: number;
  pctChange?: number;
  slopePerYear?: number | null;
  direction?: string;
  rapidDecline?: boolean;
}
