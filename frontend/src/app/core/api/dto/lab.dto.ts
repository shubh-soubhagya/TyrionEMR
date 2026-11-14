// Wire shapes of lab-svc (lab-svc/docs/api/lab-svc.json). Exact field names, snake_case, readonly.

export interface UnitDto {
  readonly unit: string;
  /** A decimal STRING (exact), never a float: the preview converts with decimal arithmetic. */
  readonly factor: string;
  readonly [key: string]: unknown;
}

export interface RangeDto {
  readonly range_id: string | null;
  readonly sex?: string | null;
  readonly age_min?: number | null;
  readonly age_max?: number | null;
  readonly low: number | null;
  readonly high: number | null;
  readonly critical_low: number | null;
  readonly critical_high: number | null;
  readonly text: string;
}

export interface CatalogItemDto {
  readonly code: string;
  readonly name: string;
  readonly canonical_unit: string;
  readonly decimals: number;
  readonly plausible_max: number;
  readonly display_order: number;
  readonly units: readonly UnitDto[];
  readonly range: RangeDto | null;
  readonly ranges: readonly RangeDto[];
}

export interface CatalogDto {
  readonly rules_version: string;
  readonly items: readonly CatalogItemDto[];
}

export interface ResultDto {
  readonly id: string;
  readonly report_id: string;
  readonly test_code: string;
  readonly test_name: string;
  readonly collected_at: string;
  readonly value: number;
  readonly unit: string;
  readonly value_original: number;
  readonly unit_original: string;
  readonly ref_low: number | null;
  readonly ref_high: number | null;
  readonly flag: string;
  readonly lab_name: string;
  readonly is_correction: boolean;
  readonly superseded: boolean;
}

export interface ResultsPageDto {
  readonly items: readonly ResultDto[];
  readonly page: number;
  readonly size: number;
  readonly total: number;
}

export interface TrendPointDto {
  readonly result_id: string | null;
  readonly collected_at: string;
  readonly value: number;
  readonly flag: string;
  readonly ref_low: number | null;
  readonly ref_high: number | null;
}

export interface TrendStatsDto {
  readonly n: number;
  readonly direction: string;
  readonly first?: number | null;
  readonly last?: number | null;
  readonly abs_change?: number | null;
  readonly pct_change?: number | null;
  readonly span_days?: number | null;
  readonly slope_per_year?: number | null;
  readonly rapid_decline?: boolean;
  readonly first_at?: string | null;
  readonly last_at?: string | null;
}

export interface TrendSeriesDto {
  readonly test_code: string;
  readonly unit: string;
  readonly points: readonly TrendPointDto[];
  readonly stats: TrendStatsDto;
  readonly reference: { readonly low: number | null; readonly high: number | null } | null;
  readonly stage_bands?: readonly { readonly code: string; readonly lower: number }[];
}

export interface TrendsDto {
  readonly patient_id: string;
  readonly from: string | null;
  readonly to: string | null;
  readonly series: readonly TrendSeriesDto[];
}

export interface LatestResultDto {
  readonly result_id: string;
  readonly report_id: string;
  readonly value: number;
  readonly flag: string;
  readonly collected_at: string;
  readonly ref_low: number | null;
  readonly ref_high: number | null;
}

export interface LatestTileDto {
  readonly test_code: string;
  readonly name: string;
  readonly canonical_unit: string;
  readonly result: LatestResultDto | null;
}

export interface CkdBlockDto {
  readonly egfr_category: string | null;
  readonly egfr_label: string | null;
  readonly egfr_value: number | null;
  readonly egfr_collected_at: string | null;
  readonly uacr_category: string | null;
  readonly uacr_label: string | null;
  readonly uacr_value: number | null;
  readonly uacr_collected_at: string | null;
}

export interface LatestDto {
  readonly patient_id: string;
  readonly tests: readonly LatestTileDto[];
  readonly ckd: CkdBlockDto;
  readonly has_critical: boolean;
  readonly rapid_decline: boolean;
  readonly last_result_at: string | null;
  readonly first_result_at: string | null;
  readonly egfr_lt60_run: { readonly since: string; readonly n: number } | null;
  readonly status_version: number;
  /** Current results (superseded rows excluded), 0 when none. */
  readonly result_count: number;
}

export interface SummaryItemDto {
  readonly patient_id: string;
  readonly has_results: boolean;
  readonly latest_egfr: {
    readonly value: number;
    readonly flag: string;
    readonly collected_at: string;
  } | null;
  readonly egfr_category: string | null;
  readonly egfr_direction: string | null;
  readonly spark: readonly { readonly t: string; readonly v: number }[];
  readonly has_critical: boolean;
  readonly rapid_decline: boolean;
  readonly last_result_at: string | null;
}

export interface SummaryDto {
  readonly items: readonly SummaryItemDto[];
}

export interface ReportInDto {
  readonly collected_at: string;
  readonly lab_name?: string | null;
  readonly notes?: string | null;
  readonly results: readonly {
    readonly test_code: string;
    readonly value: number | string;
    readonly unit: string;
  }[];
}

export interface CreatedReportDto {
  readonly report: {
    readonly id: string;
    readonly patient_id: string;
    readonly collected_at: string;
    readonly lab_name: string;
    readonly notes: string | null;
    readonly entered_by: string;
    readonly created_at: string;
  };
  readonly results: readonly Record<string, unknown>[];
  readonly summary: { readonly n: number; readonly abnormal: number; readonly critical: number };
}
