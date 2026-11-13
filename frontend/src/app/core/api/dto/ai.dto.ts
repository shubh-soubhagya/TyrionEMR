// Wire shapes of ai-svc (ai-svc/docs/api/openapi.json and ai-svc/docs/api/examples/*.json). snake_case, readonly.

export interface ReasonDto {
  readonly severity: string;
  readonly text: string;
  readonly code?: string;
}

export interface KpisDto {
  readonly patients: number;
  readonly need_attention: number;
  readonly critical_results: number;
  readonly rapid_decline: number;
}

export interface AttentionRowDto {
  readonly patient_id: string;
  readonly mrn: string;
  readonly name: string;
  readonly age: number;
  readonly reasons: readonly ReasonDto[];
}

export interface AbnormalResultDto {
  readonly patient_id: string;
  readonly name: string;
  readonly mrn: string;
  readonly test: string;
  readonly test_name: string;
  readonly value: number;
  readonly unit: string;
  readonly flag: string;
  readonly collected_at: string;
  readonly result_id: string;
}

export interface DashboardDto {
  readonly as_of: string;
  readonly generated_at: string;
  readonly rules_version: string;
  readonly kpis: KpisDto;
  readonly attention: readonly AttentionRowDto[];
  readonly egfr_distribution: Readonly<Record<string, number>>;
  readonly abnormal_results: readonly AbnormalResultDto[];
}

export interface WorklistDto {
  readonly as_of: string;
  readonly generated_at: string;
  readonly total: number;
  readonly items: readonly {
    readonly patient_id: string;
    readonly rank: number;
    readonly reasons: readonly ReasonDto[];
  }[];
}

export interface EvidenceDto {
  readonly ref: string;
  readonly label: string;
  readonly tab: string;
  readonly target_id: string | null;
  readonly type: string;
}

export interface FindingDto {
  readonly code: string;
  readonly severity: 'high' | 'medium' | 'low';
  readonly kind: 'missing' | 'inconsistent';
  readonly message: string;
  readonly evidence: readonly EvidenceDto[];
}

export interface GapsDto {
  readonly patient_id: string;
  readonly as_of: string;
  readonly rules_version: string;
  readonly provenance: string;
  readonly counts: { readonly high: number; readonly medium: number; readonly low: number };
  readonly findings: readonly FindingDto[];
  readonly attention: { readonly needs_attention: boolean; readonly reasons: readonly ReasonDto[] };
}

export interface StepDto {
  readonly key: string;
  readonly label: string;
  readonly state: string;
  readonly ms: number;
  readonly note: string;
}

export interface StartDto {
  readonly summary_id: string;
  readonly status: string;
  readonly deduplicated: boolean;
  readonly poll_after_ms: number;
  readonly progress: readonly StepDto[];
}

export interface SourceDto {
  readonly tab: string;
  readonly type: string;
  readonly label: string;
  readonly target_id: string | null;
}

export interface NarrativeSectionDto {
  readonly text: string;
  readonly source_refs: readonly string[];
}

export interface NarrativeDto {
  readonly history_summary: NarrativeSectionDto;
  readonly comorbidity_summary: NarrativeSectionDto;
  readonly trend_commentary: NarrativeSectionDto;
  readonly abnormal_commentary: NarrativeSectionDto;
  readonly follow_up_considerations: readonly {
    readonly consideration: string;
    readonly rationale: string;
    readonly source_refs: readonly string[];
  }[];
  readonly not_documented: readonly string[];
}

export interface SummaryDto {
  readonly summary_id: string;
  readonly patient_id: string;
  readonly status: 'queued' | 'running' | 'completed' | 'degraded' | 'failed';
  readonly cached: boolean;
  readonly cached_from: string | null;
  readonly as_of: string | null;
  readonly generated_at: string | null;
  readonly progress: readonly StepDto[];
  readonly facts: Record<string, unknown> | null;
  readonly gaps: {
    readonly findings: readonly FindingDto[];
    readonly provenance: string;
    readonly rules_version: string;
  } | null;
  readonly ai: {
    readonly provenance: string;
    readonly provider: string;
    readonly model: string;
    readonly prompt_version: string;
    readonly content: NarrativeDto | null;
    readonly grounding_warnings: readonly unknown[];
  } | null;
  readonly sources: Readonly<Record<string, SourceDto>> | null;
  readonly validation: {
    readonly attempts: number;
    readonly repaired: boolean;
    readonly refs_total: number;
    readonly refs_resolved: number;
    readonly safety_flags: number;
  } | null;
  readonly error_code: string | null;
  readonly error_message?: string | null;
  readonly disclaimer?: string;
  readonly context?: unknown;
}

export interface HistoryDto {
  readonly items: readonly Record<string, unknown>[];
  readonly page: number;
  readonly size: number;
  readonly total: number;
}
