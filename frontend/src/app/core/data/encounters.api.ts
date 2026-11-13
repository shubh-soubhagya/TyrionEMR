import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import type {
  DashboardEncountersDto,
  EncounterListDto,
  EncounterDetailDto,
  EncounterResultDto,
  EncounterWriteDto,
} from '../api/dto/patient.dto';
import { ENCOUNTERS, PATIENTS } from '../api/endpoints';
import { encounterFromDetail, encounterFromListItem } from '../api/mappers/patient.mapper';
import type { Encounter } from './models';

export interface EncounterPage {
  readonly items: readonly Encounter[];
  readonly total: number;
  readonly page: number;
  readonly size: number;
}

/** What a create, edit or finalize returns: the saved encounter and what the server did to the problem list. */
export interface EncounterSaved {
  readonly encounter: Encounter;
  /** Diagnoses the server added to the problem list (shown in the finalize toast). */
  readonly added: number;
  readonly linked: number;
  readonly reactivated: number;
}

const saved = (d: EncounterResultDto): EncounterSaved => ({
  encounter: encounterFromDetail(d.encounter),
  added: d.problem_list_changes.added ?? 0,
  linked: d.problem_list_changes.linked ?? 0,
  reactivated: d.problem_list_changes.reactivated ?? 0,
});

/** patient-svc encounters through the gateway. The server owns draft/final rules and the problem-list linkage. */
@Injectable({ providedIn: 'root' })
export class EncountersApi {
  private readonly http = inject(HttpClient);

  // ---- dashboard (cross-patient) ----
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

  // ---- one patient ----
  list(patientId: string, page = 1, size = 10): Observable<EncounterPage> {
    return this.http
      .get<EncounterListDto>(PATIENTS.encounters(patientId), { params: { page, size } })
      .pipe(
        map((d) => ({
          items: d.items.map((i) => encounterFromListItem(i, patientId)),
          total: d.total,
          page: d.page,
          size: d.size,
        })),
      );
  }

  get(patientId: string, encounterId: string): Observable<Encounter> {
    return this.http
      .get<EncounterDetailDto>(PATIENTS.encounter(patientId, encounterId))
      .pipe(map(encounterFromDetail));
  }

  create(patientId: string, body: EncounterWriteDto): Observable<EncounterSaved> {
    return this.http
      .post<EncounterResultDto>(PATIENTS.encounters(patientId), body)
      .pipe(map(saved));
  }

  /** `vitals` and `diagnoses`, when present, REPLACE the whole set; `version` is required. */
  update(
    patientId: string,
    encounterId: string,
    body: EncounterWriteDto,
    version: number,
  ): Observable<EncounterSaved> {
    return this.http
      .patch<EncounterResultDto>(PATIENTS.encounter(patientId, encounterId), { ...body, version })
      .pipe(map(saved));
  }

  finalize(patientId: string, encounterId: string, version: number): Observable<EncounterSaved> {
    return this.http
      .post<EncounterResultDto>(PATIENTS.finalize(patientId, encounterId), { version })
      .pipe(map(saved));
  }

  delete(patientId: string, encounterId: string): Observable<void> {
    return this.http.delete<void>(PATIENTS.encounter(patientId, encounterId));
  }
}
