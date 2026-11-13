import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '@core/api/endpoints';
import { errorInterceptor } from '@core/http/error.interceptor';
import { DashboardPage } from './dashboard-page';

const DASH = `${API_BASE}/insights/dashboard`;
const ENC = `${API_BASE}/encounters`;

const dashboard = {
  as_of: '2026-11-13',
  generated_at: '2026-11-13T06:00:00Z',
  rules_version: 'r',
  kpis: { patients: 10, need_attention: 6, critical_results: 1, rapid_decline: 4 },
  attention: [
    {
      patient_id: 'p1',
      mrn: 'PT-000101',
      name: 'Ramesh Kulkarni',
      age: 61,
      reasons: [{ severity: 'danger', text: 'eGFR falling 8.2 per year' }],
    },
  ],
  egfr_distribution: { G1: 0, G2: 3, G3a: 2, G3b: 2, G4: 1, G5: 1, none: 1 },
  abnormal_results: [],
};

const encounters = (n: number) => ({
  total: n,
  items: Array.from({ length: n }, (_, i) => ({
    encounter_id: 'e' + i,
    patient_id: 'p' + i,
    patient_name: 'Patient ' + i,
    mrn: 'PT-' + i,
    encounter_date: '2026-11-01',
    encounter_type: 'follow_up',
    chief_complaint: 'Review',
    plan: null,
    follow_up_date: '2026-12-01',
  })),
});

function create() {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  const fixture = TestBed.createComponent(DashboardPage);
  fixture.detectChanges();
  return {
    fixture,
    ctrl: TestBed.inject(HttpTestingController),
    el: fixture.nativeElement as HTMLElement,
  };
}

const isDrafts = (r: { params: { get: (k: string) => string | null } }) =>
  r.params.get('status') === 'draft';

describe('DashboardPage', () => {
  it('asks for the three panels in parallel and renders all of them', () => {
    const { fixture, ctrl, el } = create();
    ctrl.expectOne(DASH).flush(dashboard);
    ctrl.expectOne((r) => r.url === ENC && isDrafts(r)).flush(encounters(3));
    ctrl
      .expectOne((r) => r.url === ENC && r.params.get('upcoming_followups') === 'true')
      .flush(encounters(2));
    fixture.detectChanges();

    expect(el.textContent).toContain('Ramesh Kulkarni');
    expect(el.textContent).toContain('eGFR falling 8.2 per year');
    const kpis = Array.from(el.querySelectorAll('.kpi .n')).map((n) => n.textContent?.trim());
    expect(kpis).toEqual(['10', '6', '1', '4', '3']);
  });

  it('shows a loading skeleton first', () => {
    const { el } = create();
    expect(el.querySelectorAll('emr-skeleton').length).toBeGreaterThan(0);
    expect(Array.from(el.querySelectorAll('.kpi .n')).map((n) => n.textContent?.trim())).toEqual([
      '–',
      '–',
      '–',
      '–',
      '–',
    ]);
  });

  it('one failing panel leaves the other two rendered, and shows the request id, not the code', () => {
    const { fixture, ctrl, el } = create();
    ctrl.expectOne(DASH).flush(dashboard);
    ctrl
      .expectOne((r) => r.url === ENC && isDrafts(r))
      .flush(
        {
          error: { code: 'UPSTREAM_UNAVAILABLE', message: 'x', details: [], request_id: 'req-77' },
        },
        { status: 502, statusText: 'Bad Gateway' },
      );
    ctrl
      .expectOne((r) => r.url === ENC && r.params.get('upcoming_followups') === 'true')
      .flush(encounters(2));
    fixture.detectChanges();

    expect(el.textContent).toContain('Ramesh Kulkarni'); // attention panel still there
    expect(el.textContent).toContain('Patient 0'); // follow-ups still there
    expect(el.textContent).toContain('temporarily unavailable'); // the drafts panel says so
    expect(el.textContent).toContain('req-77');
    expect(el.textContent).not.toContain('UPSTREAM_UNAVAILABLE');
  });

  it('Refresh asks ai-svc to recompute with Cache-Control: no-cache', () => {
    const { fixture, ctrl, el } = create();
    ctrl.expectOne(DASH).flush(dashboard);
    ctrl.expectOne((r) => r.url === ENC && isDrafts(r)).flush(encounters(0));
    ctrl
      .expectOne((r) => r.url === ENC && r.params.get('upcoming_followups') === 'true')
      .flush(encounters(0));
    fixture.detectChanges();

    const refresh = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Refresh'),
    );
    refresh?.click();
    const again = ctrl.expectOne(DASH);
    expect(again.request.headers.get('Cache-Control')).toBe('no-cache');
    again.flush(dashboard);
    ctrl.match(() => true).forEach((r) => r.flush(encounters(0)));
  });
});
