import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '../api/endpoints';
import { EncountersApi } from './encounters.api';

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return { api: TestBed.inject(EncountersApi), ctrl: TestBed.inject(HttpTestingController) };
}

const detail = (over: Record<string, unknown> = {}) => ({
  id: 'e1',
  patient_id: 'p1',
  encounter_date: '2026-11-13T04:30:00Z',
  encounter_type: 'follow_up',
  clinician_id: 'u',
  clinician_name: 'Dr. Anita Rao',
  chief_complaint: 'Review',
  symptoms: [],
  examination_notes: null,
  assessment: 'ok',
  plan: 'continue',
  follow_up_date: null,
  status: 'draft',
  vitals: null,
  diagnoses: [
    {
      seq: 1,
      icd10_code: 'I10',
      description: 'Hypertension',
      category: null,
      add_to_problem_list: true,
      condition_id: null,
    },
  ],
  finalized_at: null,
  finalized_by: null,
  version: 2,
  created_at: '',
  updated_at: '',
  ...over,
});

describe('EncountersApi', () => {
  it('creates as draft or final and reports the problem-list changes', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(
      api.create('p1', { encounter_date: '2026-11-13T04:30:00Z', status: 'final' }),
    );
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/encounters`);
    expect(req.request.body).toMatchObject({ status: 'final' });
    req.flush({
      encounter: detail({ status: 'final' }),
      problem_list_changes: { added: 1, linked: 0, reactivated: 0 },
    });
    const saved = await p;
    expect(saved).toMatchObject({ added: 1, linked: 0, reactivated: 0 });
    expect(saved.encounter).toMatchObject({
      status: 'final',
      clinician: 'Dr. Anita Rao',
      version: 2,
    });
    expect(saved.encounter.diagnoses[0]).toMatchObject({ icd: 'I10', prob: true });
  });

  it('edits with PATCH and the version, replacing vitals and diagnoses when sent', async () => {
    const { api, ctrl } = setup();
    void firstValueFrom(
      api.update('p1', 'e1', { encounter_date: '2026-11-13T04:30:00Z', diagnoses: [] }, 2),
    );
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/encounters/e1`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toMatchObject({ version: 2, diagnoses: [] });
    req.flush({ encounter: detail(), problem_list_changes: {} });
  });

  it('finalizes with POST .../finalize and the version', async () => {
    const { api, ctrl } = setup();
    void firstValueFrom(api.finalize('p1', 'e1', 3));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/encounters/e1/finalize`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ version: 3 });
    req.flush({ encounter: detail({ status: 'final' }), problem_list_changes: { added: 2 } });
  });

  it('pages the list of one patient and maps the brief vitals', async () => {
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.list('p1', 2, 10));
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/patients/p1/encounters`);
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('size')).toBe('10');
    req.flush({
      items: [
        {
          id: 'e1',
          encounter_date: '2026-11-13T04:30:00Z',
          encounter_type: 'new',
          clinician_name: null,
          chief_complaint: null,
          assessment: null,
          follow_up_date: null,
          status: 'final',
          vitals_brief: { systolic_bp: 130, diastolic_bp: 80, heart_rate: 70 },
        },
      ],
      page: 2,
      size: 10,
      total: 11,
    });
    const page = await p;
    expect(page.total).toBe(11);
    expect(page.items[0]).toMatchObject({
      clinician: 'Not documented',
      vitals: { sys: 130, dia: 80, hr: 70 },
    });
  });

  it('deletes a draft', () => {
    const { api, ctrl } = setup();
    void firstValueFrom(api.delete('p1', 'e1'));
    const req = ctrl.expectOne(`${API_BASE}/patients/p1/encounters/e1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });
});
