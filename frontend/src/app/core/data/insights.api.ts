import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import type { DashboardDto, GapsDto, WorklistDto } from '../api/dto/ai.dto';
import { INSIGHTS } from '../api/endpoints';

/** ai-svc insights through the gateway: the dashboard aggregate, the attention worklist and one patient's gaps. */
@Injectable({ providedIn: 'root' })
export class InsightsApi {
  private readonly http = inject(HttpClient);

  /** `fresh` sends Cache-Control: no-cache, which makes ai-svc recompute instead of serving its 30 s snapshot. */
  dashboard(fresh = false): Observable<DashboardDto> {
    return this.http.get<DashboardDto>(INSIGHTS.dashboard, {
      headers: fresh ? new HttpHeaders({ 'Cache-Control': 'no-cache' }) : new HttpHeaders(),
    });
  }

  /** Ids (and reasons) of the patients who need attention, in attention order. */
  worklist(): Observable<WorklistDto> {
    return this.http.get<WorklistDto>(INSIGHTS.worklist, { params: { attention: true } });
  }

  gaps(patientId: string): Observable<GapsDto> {
    return this.http.get<GapsDto>(INSIGHTS.gaps(patientId));
  }
}
