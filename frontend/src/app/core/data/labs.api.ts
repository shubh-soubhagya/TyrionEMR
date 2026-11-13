import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import type { SummaryDto, SummaryItemDto } from '../api/dto/lab.dto';
import { LABS } from '../api/endpoints';
import type { TrendStats } from '../clinical/lab-tests';

/** One list row's eGFR cell: the latest value and the data for the sparkline, from lab-svc. */
export interface EgfrSummary {
  readonly hasResults: boolean;
  readonly latest: { readonly value: number; readonly flag: string } | null;
  readonly spark: TrendStats | null;
}

/** lab-svc through the gateway. The browser never computes a flag, a category or a trend itself. */
@Injectable({ providedIn: 'root' })
export class LabsApi {
  private readonly http = inject(HttpClient);

  /** One request for the visible page (at most 50 ids): `GET /labs/summary?patient_ids=a,b`. */
  summary(ids: readonly string[]): Observable<ReadonlyMap<string, EgfrSummary>> {
    return this.http
      .get<SummaryDto>(LABS.summary, { params: { patient_ids: ids.join(',') } })
      .pipe(map((d) => new Map(d.items.map((i) => [i.patient_id, toEgfrSummary(i)] as const))));
  }
}

/** Shapes lab-svc's points for the existing sparkline component (display only). */
export function toEgfrSummary(i: SummaryItemDto): EgfrSummary {
  const pts = i.spark.map((p) => ({ t: new Date(p.t).getTime(), v: p.v }));
  const first = pts[0]?.v ?? 0;
  const last = pts[pts.length - 1]?.v ?? 0;
  const dir = i.egfr_direction;
  const direction: TrendStats['direction'] =
    dir === 'worsening' || dir === 'improving' || dir === 'stable' || dir === 'insufficient_data'
      ? dir
      : pts.length
        ? 'stable'
        : 'no_data';
  return {
    hasResults: i.has_results,
    latest: i.latest_egfr ? { value: i.latest_egfr.value, flag: i.latest_egfr.flag } : null,
    spark: pts.length
      ? {
          n: pts.length,
          first,
          last,
          abs: last - first,
          pct: first ? ((last - first) / first) * 100 : 0,
          slope: null,
          direction,
          rapid: i.rapid_decline,
          spanDays: Math.round(((pts[pts.length - 1]?.t ?? 0) - (pts[0]?.t ?? 0)) / 86400000),
          pts,
        }
      : null,
  };
}
