import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { ApiError } from '@core/api/api-error';
import type { LatestDto } from '@core/api/dto/lab.dto';
import type { PatientDetailDto } from '@core/api/dto/patient.dto';
import { LOADING, type Remote } from '@core/api/remote';
import { PatientShellPage } from './patient-shell-page';
import { PatientStore } from './patient-store';

const detail: PatientDetailDto = {
  id: 'p1',
  mrn: 'PT-000101',
  first_name: 'Ramesh',
  last_name: 'Kulkarni',
  age: 67,
  sex: 'M',
  phone: null,
  allergy_status: 'nka',
  established_ckd_stage: 'G3b',
  last_visit: null,
  primary_diagnosis: null,
  date_of_birth: '1959-01-01',
  email: null,
  address: null,
  past_medical_history: null,
  family_history: null,
  social_history: null,
  allergy_summary: [],
  counts: { conditions: 3, active_conditions: 2, active_medications: 4, encounters: 5 },
  next_follow_up: null,
  version: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const latest = (result_count: number): LatestDto => ({
  patient_id: 'p1',
  tests: [],
  ckd: {
    egfr_category: 'G3b',
    egfr_label: null,
    egfr_value: 40,
    egfr_collected_at: null,
    uacr_category: null,
    uacr_label: null,
    uacr_value: null,
    uacr_collected_at: null,
  },
  has_critical: false,
  rapid_decline: false,
  last_result_at: null,
  first_result_at: null,
  egfr_lt60_run: null,
  status_version: 1,
  result_count,
});

function setup(initial: Remote<LatestDto>) {
  const lat = signal<Remote<LatestDto>>(initial);
  const store = {
    id: signal(''),
    detail: signal<Remote<PatientDetailDto>>({ state: 'ok', data: detail }),
    latest: lat,
    egfrCategory: signal<string | null>('G3b'),
    mismatch: signal(false),
    reloadDetail: () => undefined,
  };
  TestBed.configureTestingModule({ providers: [provideRouter([])] });
  TestBed.overrideComponent(PatientShellPage, {
    set: { providers: [{ provide: PatientStore, useValue: store }] },
  });
  const fixture = TestBed.createComponent(PatientShellPage);
  fixture.componentRef.setInput('id', 'p1');
  fixture.detectChanges();
  const pill = (): string | null => {
    const tab = [...fixture.nativeElement.querySelectorAll('nav.tabs a.tab')].find((a) =>
      (a as HTMLElement).textContent?.includes('Labs'),
    ) as HTMLElement;
    return tab.querySelector('.ct')?.textContent?.trim() ?? null;
  };
  return { fixture, lat, pill };
}

describe('PatientShellPage Labs count pill', () => {
  it('shows result_count from lab-svc, including 0', () => {
    const { pill } = setup({ state: 'ok', data: latest(7) });
    expect(pill()).toBe('7');
    TestBed.resetTestingModule();
    expect(setup({ state: 'ok', data: latest(0) }).pill()).toBe('0');
  });

  it('is absent while lab-svc is loading and when it failed', () => {
    expect(setup(LOADING).pill()).toBeNull();
    TestBed.resetTestingModule();
    const err = new ApiError(500, 'UPSTREAM_ERROR', 'x', [], null, null);
    expect(setup({ state: 'error', error: err }).pill()).toBeNull();
  });

  it('updates when the shell latest signal changes', () => {
    const { fixture, lat, pill } = setup({ state: 'ok', data: latest(3) });
    expect(pill()).toBe('3');
    lat.set({ state: 'ok', data: latest(5) });
    fixture.detectChanges();
    expect(pill()).toBe('5');
  });

  it('keeps the patient-svc counts on the other tabs', () => {
    const { fixture } = setup(LOADING);
    const pills = [...fixture.nativeElement.querySelectorAll('nav.tabs .ct')].map((e) =>
      (e as HTMLElement).textContent?.trim(),
    );
    expect(pills).toEqual(['3', '4', '5']);
  });
});
