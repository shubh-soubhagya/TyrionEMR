import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '../api/endpoints';
import { LabsApi, toEgfrSummary } from './labs.api';
import { PatientsApi } from './patients.api';

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return { ctrl: TestBed.inject(HttpTestingController) };
}

const item = (over: Record<string, unknown> = {}) => ({
  id: 'p1',
  mrn: 'PT-000101',
  first_name: 'Ramesh',
  last_name: 'Kulkarni',
  age: 61,
  sex: 'M',
  phone: null,
  allergy_status: 'has_allergies',
  established_ckd_stage: 'G3b',
  last_visit: '2026-10-01',
  primary_diagnosis: { description: 'CKD stage 3b', icd10_code: 'N18.32' },
  ...over,
});

describe('PatientsApi.list', () => {
  it('sends every filter, sort and page to the server and nothing else', async () => {
    const { ctrl } = setup();
    const p = firstValueFrom(
      TestBed.inject(PatientsApi).list({
        q: ' kul ',
        sex: 'M',
        stage: 'none',
        sort: 'visit',
        dir: 'desc',
        page: 2,
        ids: ['a', 'b'],
      }),
    );
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/patients`);
    expect(
      Object.fromEntries(req.request.params.keys().map((k) => [k, req.request.params.get(k)])),
    ).toEqual({
      q: 'kul',
      sex: 'M',
      stage: 'none',
      sort: 'visit',
      dir: 'desc',
      page: '2',
      size: '8',
      ids: 'a,b',
    });
    req.flush({ items: [item()], page: 2, size: 8, total: 17 });
    const page = await p;
    expect(page).toMatchObject({ total: 17, page: 2, pages: 3 });
    expect(page.rows[0]).toMatchObject({
      age: 61,
      primaryDiagnosis: 'CKD stage 3b',
      lastVisit: '2026-10-01',
    });
    expect(page.rows[0]?.patient).toMatchObject({
      first: 'Ramesh',
      allergyStatus: 'has',
      ckd: 'G3b',
    });
  });

  it('omits empty filters', async () => {
    const { ctrl } = setup();
    void firstValueFrom(TestBed.inject(PatientsApi).list({ q: '', sex: '' }));
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/patients`);
    expect(req.request.params.keys().sort()).toEqual(['page', 'size']);
    req.flush({ items: [], page: 1, size: 8, total: 0 });
  });
});

describe('LabsApi.summary', () => {
  it('asks once for the visible ids and keys the answer by patient', async () => {
    const { ctrl } = setup();
    const p = firstValueFrom(TestBed.inject(LabsApi).summary(['a', 'b']));
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/labs/summary`);
    expect(req.request.params.get('patient_ids')).toBe('a,b');
    req.flush({
      items: [
        {
          patient_id: 'a',
          has_results: true,
          latest_egfr: { value: 38, flag: 'low', collected_at: '2026-10-24T09:00:00Z' },
          egfr_category: 'G3b',
          egfr_direction: 'worsening',
          spark: [
            { t: '2025-01-01T00:00:00Z', v: 54 },
            { t: '2026-01-01T00:00:00Z', v: 38 },
          ],
          has_critical: false,
          rapid_decline: true,
          last_result_at: null,
        },
        {
          patient_id: 'b',
          has_results: false,
          latest_egfr: null,
          egfr_category: null,
          egfr_direction: null,
          spark: [],
          has_critical: false,
          rapid_decline: false,
          last_result_at: null,
        },
      ],
    });
    const map = await p;
    expect(map.get('a')?.latest).toEqual({ value: 38, flag: 'low' });
    expect(map.get('a')?.spark).toMatchObject({
      n: 2,
      first: 54,
      last: 38,
      direction: 'worsening',
      rapid: true,
    });
    expect(map.get('b')).toMatchObject({ hasResults: false, latest: null, spark: null });
  });

  it('shows a patient without a trend direction as stable when points exist', () => {
    const s = toEgfrSummary({
      patient_id: 'x',
      has_results: true,
      latest_egfr: null,
      egfr_category: null,
      egfr_direction: null,
      spark: [{ t: '2026-01-01T00:00:00Z', v: 60 }],
      has_critical: false,
      rapid_decline: false,
      last_result_at: null,
    });
    expect(s.spark?.direction).toBe('stable');
  });
});
