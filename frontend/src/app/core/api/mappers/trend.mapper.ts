// lab-svc trends -> what the existing chart components draw. Display adapter only: every number is the server's.
import type { Flag, TrendPoint, TrendStats } from '../../clinical/lab-tests';
import type { TrendSeriesDto, TrendStatsDto } from '../dto/lab.dto';
import { flagFromDto } from './lab.mapper';

const DIRECTIONS = ['no_data', 'insufficient_data', 'worsening', 'improving', 'stable'] as const;

export function directionFrom(d: string): TrendStats['direction'] {
  return (DIRECTIONS as readonly string[]).includes(d) ? (d as TrendStats['direction']) : 'stable';
}

export function statsFromDto(s: TrendStatsDto, pts: TrendPoint[]): TrendStats {
  return {
    n: s.n,
    first: s.first ?? 0,
    last: s.last ?? 0,
    abs: s.abs_change ?? 0,
    pct: s.pct_change ?? 0,
    slope: s.slope_per_year ?? null,
    direction: directionFrom(s.direction),
    rapid: s.rapid_decline === true,
    spanDays: s.span_days ?? 0,
    pts,
  };
}

export interface ChartSeries {
  readonly test: string;
  readonly unit: string;
  readonly stats: TrendStats;
  readonly low: number | null;
  readonly high: number | null;
  /** Insufficient data (fewer than 3 results): the chips say so instead of a slope. */
  readonly insufficient: boolean;
}

export function chartSeriesFromDto(s: TrendSeriesDto): ChartSeries {
  const pts: TrendPoint[] = s.points.map((p) => ({
    t: new Date(p.collected_at).getTime(),
    v: p.value,
    flag: flagFromDto(p.flag) as Flag,
    ...(p.result_id ? { id: p.result_id } : {}),
  }));
  return {
    test: s.test_code,
    unit: s.unit,
    stats: statsFromDto(s.stats, pts),
    low: s.reference?.low ?? null,
    high: s.reference?.high ?? null,
    insufficient: s.stats.direction === 'insufficient_data',
  };
}
