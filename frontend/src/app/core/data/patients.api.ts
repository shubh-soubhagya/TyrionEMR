import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import type { PatientDetailDto, PatientListDto } from '../api/dto/patient.dto';
import { PATIENTS } from '../api/endpoints';
import {
  patientCreateToDto,
  patientFromDetail,
  patientFromList,
  patientPatchToDto,
  type PatientForm,
} from '../api/mappers/patient.mapper';
import type { Patient } from './models';

export type ListSort = 'name' | 'mrn' | 'age' | 'dx' | 'visit';

/** Everything the list page can ask the server for. Filtering, sorting and paging are all server-side (F6). */
export interface PatientQuery {
  readonly q?: string;
  readonly sex?: string;
  readonly stage?: string;
  readonly ids?: readonly string[];
  readonly sort?: ListSort;
  readonly dir?: 'asc' | 'desc';
  readonly page?: number;
  readonly size?: number;
}

export interface PatientRow {
  readonly patient: Patient;
  readonly age: number;
  readonly primaryDiagnosis: string;
  readonly lastVisit: string | null;
}

export interface PatientPage {
  readonly rows: readonly PatientRow[];
  readonly total: number;
  readonly page: number;
  readonly pages: number;
  readonly size: number;
}

/** patient-svc patients through the gateway. Components never build these requests themselves. */
@Injectable({ providedIn: 'root' })
export class PatientsApi {
  private readonly http = inject(HttpClient);

  list(query: PatientQuery): Observable<PatientPage> {
    let params = new HttpParams();
    const set = (k: string, v: string | number | undefined): void => {
      if (v !== undefined && v !== '') params = params.set(k, String(v));
    };
    set('q', query.q?.trim());
    set('sex', query.sex);
    set('stage', query.stage);
    if (query.ids) set('ids', query.ids.join(','));
    set('sort', query.sort);
    set('dir', query.dir);
    set('page', query.page ?? 1);
    set('size', query.size ?? 8);
    return this.http.get<PatientListDto>(PATIENTS.list, { params }).pipe(
      map((d) => ({
        rows: d.items.map((i) => ({
          patient: patientFromList(i),
          age: i.age,
          primaryDiagnosis: i.primary_diagnosis?.description ?? '',
          lastVisit: i.last_visit,
        })),
        total: d.total,
        page: d.page,
        pages: Math.max(1, Math.ceil(d.total / d.size)),
        size: d.size,
      })),
    );
  }

  /** The full chart header: the view model plus what the shell needs (counts, allergy chip, age, version). */
  get(id: string): Observable<PatientDetailDto> {
    return this.http.get<PatientDetailDto>(PATIENTS.one(id));
  }

  detail(id: string): Observable<Patient> {
    return this.get(id).pipe(map(patientFromDetail));
  }

  create(form: PatientForm): Observable<Patient> {
    return this.http
      .post<PatientDetailDto>(PATIENTS.list, patientCreateToDto(form))
      .pipe(map(patientFromDetail));
  }

  /** Needs the version the person was looking at: a 409 VERSION_CONFLICT means someone else saved first. */
  update(id: string, form: PatientForm, version: number): Observable<Patient> {
    return this.http
      .patch<PatientDetailDto>(PATIENTS.one(id), patientPatchToDto(form, version))
      .pipe(map(patientFromDetail));
  }

  setEstablishedStage(id: string, stage: string | null, version: number): Observable<Patient> {
    return this.http
      .patch<PatientDetailDto>(PATIENTS.one(id), { version, established_ckd_stage: stage })
      .pipe(map(patientFromDetail));
  }
}
