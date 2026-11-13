// Wire shapes of patient-svc (patient-svc/docs/api/patient-svc.json). Exact field names, snake_case, readonly.

export type AllergyStatusDto = 'unknown' | 'nka' | 'has_allergies';
export type RouteCodeDto = 'oral' | 'sc' | 'iv' | 'topical' | 'inhaled' | 'other';
export type StageDto = 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5';

export interface PrimaryDiagnosisBriefDto {
  readonly description: string;
  readonly icd10_code: string | null;
}

export interface PatientListItemDto {
  readonly id: string;
  readonly mrn: string;
  readonly first_name: string;
  readonly last_name: string;
  readonly age: number;
  readonly sex: string;
  readonly phone: string | null;
  readonly allergy_status: AllergyStatusDto;
  readonly established_ckd_stage: string | null;
  readonly last_visit: string | null;
  readonly primary_diagnosis: PrimaryDiagnosisBriefDto | null;
}

export interface PatientListDto {
  readonly items: readonly PatientListItemDto[];
  readonly page: number;
  readonly size: number;
  readonly total: number;
}

export interface AllergyBriefDto {
  readonly id: string;
  readonly allergen: string;
  readonly severity: string;
}

export interface CountsDto {
  readonly conditions: number;
  readonly active_conditions: number;
  readonly active_medications: number;
  readonly encounters: number;
}

export interface PatientDetailDto extends PatientListItemDto {
  readonly date_of_birth: string;
  readonly email: string | null;
  readonly address: string | null;
  readonly past_medical_history: string | null;
  readonly family_history: string | null;
  readonly social_history: string | null;
  readonly allergy_summary: readonly AllergyBriefDto[];
  readonly counts: CountsDto;
  readonly next_follow_up: string | null;
  readonly primary_diagnosis: (PrimaryDiagnosisBriefDto & { readonly id: string }) | null;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface PatientCreateDto {
  readonly first_name: string;
  readonly last_name: string;
  readonly date_of_birth: string;
  readonly sex: 'M' | 'F' | 'O';
  readonly phone?: string | null;
  readonly email?: string | null;
  readonly address?: string | null;
  readonly past_medical_history?: string | null;
  readonly family_history?: string | null;
  readonly social_history?: string | null;
  readonly allergy_status?: 'unknown' | 'nka';
}

export interface PatientPatchDto extends Partial<Omit<PatientCreateDto, 'allergy_status'>> {
  readonly version: number;
  readonly allergy_status?: 'unknown' | 'nka' | null;
  readonly established_ckd_stage?: StageDto | null;
}

export interface ConditionDto {
  readonly id: string;
  readonly icd10_code: string | null;
  readonly description: string;
  readonly category: string;
  readonly is_primary: boolean;
  readonly status: string;
  readonly onset_date: string | null;
  readonly resolved_date: string | null;
  readonly source_encounter_id: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly primary_cleared?: boolean;
}

export interface ConditionCreateDto {
  readonly description: string;
  readonly category: 'nephrology' | 'comorbidity';
  readonly icd10_code?: string | null;
  readonly is_primary?: boolean;
  readonly onset_date?: string | null;
}

export interface ConditionPatchDto {
  readonly is_primary?: boolean;
  readonly status?: 'active' | 'resolved';
  readonly description?: string;
  readonly icd10_code?: string | null;
}

export interface MedicationDto {
  readonly id: string;
  readonly name: string;
  readonly dose: string;
  readonly route: string;
  readonly frequency: string;
  readonly start_date: string | null;
  readonly end_date: string | null;
  readonly status: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface MedicationCreateDto {
  readonly name: string;
  readonly dose: string;
  readonly frequency: string;
  readonly route?: RouteCodeDto;
  readonly start_date?: string | null;
  readonly end_date?: string | null;
}

export interface AllergyDto {
  readonly id: string;
  readonly allergen: string;
  readonly reaction: string | null;
  readonly severity: string;
  readonly created_at: string;
}

export interface AllergyCreateDto {
  readonly allergen: string;
  readonly reaction?: string | null;
  readonly severity?: 'mild' | 'moderate' | 'severe';
}

/** POST and DELETE on allergies answer with the new status and the patient's new version. */
export interface AllergyChangeDto {
  readonly allergy?: AllergyDto;
  readonly allergy_status: AllergyStatusDto;
  readonly patient_version: number;
}

export interface VitalsDto {
  readonly systolic_bp: number | null;
  readonly diastolic_bp: number | null;
  readonly heart_rate: number | null;
  readonly temperature_c: number | null;
  readonly weight_kg: number | null;
}

export interface DiagnosisDto {
  readonly seq: number;
  readonly icd10_code: string | null;
  readonly description: string;
  readonly category: string | null;
  readonly add_to_problem_list: boolean;
  readonly condition_id: string | null;
}

export interface EncounterListItemDto {
  readonly id: string;
  readonly encounter_date: string;
  readonly encounter_type: string;
  readonly clinician_name: string | null;
  readonly chief_complaint: string | null;
  readonly assessment: string | null;
  readonly follow_up_date: string | null;
  readonly status: string;
  readonly vitals_brief: {
    readonly systolic_bp: number | null;
    readonly diastolic_bp: number | null;
    readonly heart_rate: number | null;
  } | null;
}

export interface EncounterListDto {
  readonly items: readonly EncounterListItemDto[];
  readonly page: number;
  readonly size: number;
  readonly total: number;
}

export interface EncounterDetailDto {
  readonly id: string;
  readonly patient_id: string;
  readonly encounter_date: string;
  readonly encounter_type: string;
  readonly clinician_id: string;
  readonly clinician_name: string | null;
  readonly chief_complaint: string | null;
  readonly symptoms: readonly string[];
  readonly examination_notes: string | null;
  readonly assessment: string | null;
  readonly plan: string | null;
  readonly follow_up_date: string | null;
  readonly status: string;
  readonly vitals: VitalsDto | null;
  readonly diagnoses: readonly DiagnosisDto[];
  readonly finalized_at: string | null;
  readonly finalized_by: string | null;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ProblemListChangesDto {
  readonly added?: number;
  readonly linked?: number;
  readonly reactivated?: number;
}

export interface EncounterResultDto {
  readonly encounter: EncounterDetailDto;
  readonly problem_list_changes: ProblemListChangesDto;
}

export interface VitalsInDto {
  readonly systolic_bp?: number | null;
  readonly diastolic_bp?: number | null;
  readonly heart_rate?: number | null;
  readonly temperature_c?: number | null;
  readonly weight_kg?: number | null;
}

export interface DiagnosisInDto {
  readonly icd10_code?: string | null;
  readonly description: string;
  readonly category?: 'nephrology' | 'comorbidity' | null;
  readonly add_to_problem_list?: boolean;
}

export interface EncounterWriteDto {
  readonly encounter_date: string;
  readonly encounter_type?: 'new' | 'follow_up' | 'emergency';
  readonly chief_complaint?: string | null;
  readonly symptoms?: readonly string[];
  readonly examination_notes?: string | null;
  readonly assessment?: string | null;
  readonly plan?: string | null;
  readonly follow_up_date?: string | null;
  readonly status?: 'draft' | 'final';
  readonly vitals?: VitalsInDto | null;
  readonly diagnoses?: readonly DiagnosisInDto[];
}

export interface EncounterPatchDto extends Partial<EncounterWriteDto> {
  readonly version: number;
}

export interface DashboardEncounterDto {
  readonly encounter_id: string;
  readonly patient_id: string;
  readonly patient_name: string;
  readonly mrn: string;
  readonly encounter_date: string;
  readonly encounter_type: string;
  readonly chief_complaint: string | null;
  readonly plan: string | null;
  readonly follow_up_date: string | null;
}

export interface DashboardEncountersDto {
  readonly items: readonly DashboardEncounterDto[];
  readonly total: number;
}
