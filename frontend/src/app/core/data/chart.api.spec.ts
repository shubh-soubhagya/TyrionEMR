import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '../api/endpoints';
import { ChartApi } from './chart.api';

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return { api: TestBed.inject(ChartApi), ctrl: TestBed.inject(HttpTestingController) };
}

const cond = (over: Record<string, unknown> = {}) => ({
  id: 'c1',
  icd10_code: 'N18.4',
  description: 'CKD 4',
  category: 'nephrology',
  is_primary: true,
  status: 'active',
  onset_date: null,
  resolved_date: null,
  source_encounter_id: null,
  created_at: '',
  updated_at: '',
  ...over,
});

describe('ChartApi', () => {
  it('sets primary with {is_primary: true} and reports when another primary was cleared', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.patchCondition('p1', 'c1', { is_primary: true }));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/conditions/c1`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ is_primary: true });
    req.flush(cond({ primary_cleared: true }));
    expect(await p).toMatchObject({
      primaryCleared: true,
      condition: { isPrimary: true, icd10: 'N18.4' },
    });
  });

  it('resolves and reactivates with {status}', async () => {
    const { api, ctrl } = setup();
    void firstValueFrom(api.patchCondition('p1', 'c1', { status: 'resolved' }));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/conditions/c1`);
    expect(req.request.body).toEqual({ status: 'resolved' });
    req.flush(cond({ status: 'resolved', is_primary: false }));
  });

  it('asks for status=active or status=all and maps the route code to a label', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.medications('p1', 'all'));
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/patients/p1/medications`);
    expect(req.request.params.get('status')).toBe('all');
    req.flush({
      items: [
        {
          id: 'm1',
          name: 'Insulin',
          dose: '10 u',
          route: 'sc',
          frequency: 'Daily',
          start_date: null,
          end_date: null,
          status: 'active',
          created_at: '',
          updated_at: '',
        },
      ],
    });
    expect((await p)[0]).toMatchObject({ route: 'SC', freq: 'Daily' });
  });

  it('discontinues with {action: "discontinue"}', () => {
    const { api, ctrl } = setup();
    void firstValueFrom(api.discontinueMedication('p1', 'm1'));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/medications/m1`);
    expect(req.request.body).toEqual({ action: 'discontinue' });
    req.flush({
      id: 'm1',
      name: 'x',
      dose: 'x',
      route: 'oral',
      frequency: 'x',
      start_date: null,
      end_date: '2026-11-13',
      status: 'discontinued',
      created_at: '',
      updated_at: '',
    });
  });

  it('returns the new allergy status and patient version from an allergy change', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.removeAllergy('p1', 'a1'));
    ctrl
      .expectOne(`${API_BASE}/patients/p1/allergies/a1`)
      .flush({ allergy_status: 'unknown', patient_version: 7 });
    expect(await p).toEqual({ status: 'unknown', patientVersion: 7, allergy: null });
  });

  it('marks no known allergies with a PATCH carrying the version', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.markNoKnownAllergies('p1', 5));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1`);
    expect(req.request.body).toEqual({ version: 5, allergy_status: 'nka' });
    req.flush({ allergy_status: 'nka' });
    expect(await p).toBe('nka');
  });
});
