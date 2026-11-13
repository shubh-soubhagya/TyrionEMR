import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import type { DashboardEncountersDto } from '../api/dto/patient.dto';
import { ENCOUNTERS } from '../api/endpoints';

/** Cross-patient encounter queries behind the dashboard (patient-svc `GET /encounters`). */
@Injectable({ providedIn: 'root' })
export class EncountersApi {
  private readonly http = inject(HttpClient);

  drafts(limit: number): Observable<DashboardEncountersDto> {
    return this.http.get<DashboardEncountersDto>(ENCOUNTERS.list, {
      params: { status: 'draft', limit },
    });
  }

  upcomingFollowUps(limit: number): Observable<DashboardEncountersDto> {
    return this.http.get<DashboardEncountersDto>(ENCOUNTERS.list, {
      params: { upcoming_followups: true, limit },
    });
  }
}
