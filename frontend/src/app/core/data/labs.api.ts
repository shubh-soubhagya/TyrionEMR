import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import type {
  CatalogDto,
  CreatedReportDto,
  LatestDto,
  ReportInDto,
  ResultsPageDto,
  SummaryDto,
  SummaryItemDto,
  TrendsDto,
} from '../api/dto/lab.dto';
import { LABS } from '../api/endpoints';
import { labResultFromDto } from '../api/mappers/lab.mapper';
import type { TrendStats } from '../clinical/lab-tests';
import type { LabResult } from './models';

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
  latest(patientId: string): Observable<LatestDto> {
    return this.http.get<LatestDto>(LABS.latest(patientId));
  }

  /** `from` (ISO date) limits the window: the range chips map to it (6 months, 1 year, 2 years, all). */
  trends(patientId: string, tests: readonly string[], from?: string): Observable<TrendsDto> {
    let params = new HttpParams().set('tests', tests.join(','));
    if (from) params = params.set('from', from);
    return this.http.get<TrendsDto>(LABS.trends(patientId), { params });
  }

  results(
    patientId: string,
    q: { test?: string; abnormalOnly?: boolean; page?: number; size?: number },
  ): Observable<{ items: LabResult[]; total: number; page: number; size: number }> {
    let params = new HttpParams().set('page', q.page ?? 1).set('size', q.size ?? 10);
    if (q.test) params = params.set('test', q.test);
    if (q.abnormalOnly) params = params.set('flag', 'abnormal');
    return this.http.get<ResultsPageDto>(LABS.results(patientId), { params }).pipe(
      map((d) => ({
        items: d.items.map((r) => labResultFromDto(r, patientId)),
        total: d.total,
        page: d.page,
        size: d.size,
      })),
    );
  }

  /** The catalog for ONE patient: ranges for their sex and age, units with exact string factors. Loaded once per patient. */
  catalog(sex: string, age: number): Observable<CatalogDto> {
    return this.http.get<CatalogDto>(LABS.tests, { params: { sex, age } });
  }

  addReport(patientId: string, body: ReportInDto): Observable<CreatedReportDto> {
    return this.http.post<CreatedReportDto>(LABS.reports(patientId), body);
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
