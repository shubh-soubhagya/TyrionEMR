import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import type {
  AllergyChangeDto,
  AllergyCreateDto,
  AllergyDto,
  ConditionCreateDto,
  ConditionDto,
  ConditionPatchDto,
  MedicationDto,
  PatientDetailDto,
} from '../api/dto/patient.dto';
import { PATIENTS } from '../api/endpoints';
import {
  allergyFromDto,
  allergyStatusFromDto,
  conditionFromDto,
  medFromDto,
  medToCreateDto,
} from '../api/mappers/patient.mapper';
import type { Allergy, AllergyStatus, Condition, Med } from './models';

export interface ConditionChange {
  readonly condition: Condition;
  /** True when making this one primary cleared another condition's primary flag. */
  readonly primaryCleared: boolean;
}

export interface AllergyList {
  readonly status: AllergyStatus;
  readonly items: readonly Allergy[];
}

export interface AllergyChange {
  readonly status: AllergyStatus;
  /** The patient's new version: the next PATCH /patients/{id} must send this one. */
  readonly patientVersion: number;
  readonly allergy: Allergy | null;
}

export interface MedInput {
  name: string;
  dose: string;
  route: string;
  freq: string;
  start: string;
  end: string | null;
}

/** patient-svc chart sections: conditions, medications and allergies. The server owns every rule (one primary, links). */
@Injectable({ providedIn: 'root' })
export class ChartApi {
  private readonly http = inject(HttpClient);

  // ---- conditions ----
  conditions(patientId: string): Observable<Condition[]> {
    return this.http
      .get<{ items: ConditionDto[] }>(PATIENTS.conditions(patientId))
      .pipe(map((d) => d.items.map((c) => conditionFromDto(c, patientId))));
  }

  addCondition(patientId: string, body: ConditionCreateDto): Observable<Condition> {
    return this.http
      .post<ConditionDto>(PATIENTS.conditions(patientId), body)
      .pipe(map((c) => conditionFromDto(c, patientId)));
  }

  /** `{is_primary: true}` sets primary; `{status}` resolves or reactivates. */
  patchCondition(
    patientId: string,
    conditionId: string,
    body: ConditionPatchDto,
  ): Observable<ConditionChange> {
    return this.http.patch<ConditionDto>(PATIENTS.condition(patientId, conditionId), body).pipe(
      map((c) => ({
        condition: conditionFromDto(c, patientId),
        primaryCleared: c.primary_cleared === true,
      })),
    );
  }

  // ---- medications ----
  medications(patientId: string, status: 'active' | 'all'): Observable<Med[]> {
    return this.http
      .get<{ items: MedicationDto[] }>(PATIENTS.medications(patientId), {
        params: new HttpParams().set('status', status),
      })
      .pipe(map((d) => d.items.map((m) => medFromDto(m, patientId))));
  }

  addMedication(patientId: string, m: MedInput): Observable<Med> {
    return this.http
      .post<MedicationDto>(PATIENTS.medications(patientId), medToCreateDto(m))
      .pipe(map((d) => medFromDto(d, patientId)));
  }

  discontinueMedication(patientId: string, medId: string): Observable<Med> {
    return this.http
      .patch<MedicationDto>(PATIENTS.medication(patientId, medId), { action: 'discontinue' })
      .pipe(map((d) => medFromDto(d, patientId)));
  }

  // ---- allergies ----
  allergies(patientId: string): Observable<AllergyList> {
    return this.http
      .get<{ allergy_status: 'unknown' | 'nka' | 'has_allergies'; items: AllergyDto[] }>(
        PATIENTS.allergies(patientId),
      )
      .pipe(
        map((d) => ({
          status: allergyStatusFromDto(d.allergy_status),
          items: d.items.map((a) => allergyFromDto(a, patientId)),
        })),
      );
  }

  addAllergy(patientId: string, body: AllergyCreateDto): Observable<AllergyChange> {
    return this.http
      .post<AllergyChangeDto>(PATIENTS.allergies(patientId), body)
      .pipe(map((d) => toAllergyChange(d, patientId)));
  }

  removeAllergy(patientId: string, allergyId: string): Observable<AllergyChange> {
    return this.http
      .delete<AllergyChangeDto>(PATIENTS.allergy(patientId, allergyId))
      .pipe(map((d) => toAllergyChange(d, patientId)));
  }

  /** "No known allergies": a PATCH on the patient with the version the person is looking at. */
  markNoKnownAllergies(patientId: string, version: number): Observable<AllergyStatus> {
    return this.http
      .patch<PatientDetailDto>(PATIENTS.one(patientId), { version, allergy_status: 'nka' })
      .pipe(map((d) => allergyStatusFromDto(d.allergy_status)));
  }
}

function toAllergyChange(d: AllergyChangeDto, patientId: string): AllergyChange {
  return {
    status: allergyStatusFromDto(d.allergy_status),
    patientVersion: d.patient_version,
    allergy: d.allergy ? allergyFromDto(d.allergy, patientId) : null,
  };
}
