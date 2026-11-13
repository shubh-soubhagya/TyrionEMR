import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '@core/api/endpoints';
import { CATALOG_BY_SEX } from '@core/clinical/testing/catalog-fixture';
import { errorInterceptor } from '@core/http/error.interceptor';
import { ModalService } from '@core/ui/modal.service';
import { LabModal } from './lab-modal';

const PATIENT = {
  id: 'p1',
  mrn: 'PT-000101',
  first_name: 'Ramesh',
  last_name: 'Kulkarni',
  sex: 'M',
  age: 61,
  date_of_birth: '1965-05-02',
  version: 1,
};

async function open() {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'patients/:id/labs', children: [] }]),
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  const fixture = TestBed.createComponent(LabModal);
  fixture.componentRef.setInput('patientId', 'p1');
  fixture.detectChanges();
  const ctrl = TestBed.inject(HttpTestingController);
  ctrl.expectOne(`${API_BASE}/patients/p1`).flush(PATIENT);
  await Promise.resolve();
  const cat = ctrl.expectOne((r) => r.url === `${API_BASE}/labs/tests`);
  expect(cat.request.params.get('sex')).toBe('M'); // the catalog is asked for THIS patient's sex and age
  expect(cat.request.params.get('age')).toBe('61');
  cat.flush(CATALOG_BY_SEX.M);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, ctrl, el: fixture.nativeElement as HTMLElement };
}

const rows = (el: HTMLElement) => Array.from(el.querySelectorAll<HTMLElement>('.lab-row'));
const set = (input: HTMLInputElement | HTMLSelectElement, value: string, event = 'input') => {
  input.value = value;
  input.dispatchEvent(new Event(event));
};

describe('LabModal', () => {
  it('shows two rows with the catalog tests and previews the flag and the conversion with exact decimals', async () => {
    const { fixture, el } = await open();
    expect(rows(el)).toHaveLength(2);
    const first = rows(el)[0] as HTMLElement;
    set(first.querySelector('select[aria-label=Unit]') as HTMLSelectElement, 'µmol/L', 'change');
    set(first.querySelector('input[aria-label=Value]') as HTMLInputElement, '150');
    fixture.detectChanges();
    const prev = first.querySelector('.lab-prev')?.textContent ?? '';
    expect(prev).toContain('= 1.695 mg/dL'); // 150 x 0.0113, half-up to decimals + 1 places
    expect(prev).toContain('High');
  });

  it('sends the values as typed text, in the catalog unit spelling, with the report time as ISO', async () => {
    const { fixture, ctrl, el } = await open();
    const [creat, egfr] = rows(el) as [HTMLElement, HTMLElement];
    set(creat.querySelector('input[aria-label=Value]') as HTMLInputElement, '1.50');
    set(egfr.querySelector('input[aria-label=Value]') as HTMLInputElement, '38');
    fixture.detectChanges();
    el.querySelector<HTMLFormElement>('form')?.dispatchEvent(new Event('submit'));
    const req = ctrl.expectOne(`${API_BASE}/labs/patients/p1/reports`);
    expect(req.request.body.results).toEqual([
      { test_code: 'CREAT', value: '1.50', unit: 'mg/dL' },
      { test_code: 'EGFR', value: '38', unit: 'mL/min/1.73m²' },
    ]);
    expect(req.request.body.collected_at).toMatch(/Z$/);
    req.flush({
      report: {
        id: 'r',
        patient_id: 'p1',
        collected_at: '',
        lab_name: 'x',
        notes: null,
        entered_by: 'u',
        created_at: '',
      },
      results: [],
      summary: { n: 2, abnormal: 2, critical: 0 },
    });
    expect(TestBed.inject(ModalService).changed()).toMatchObject({ kind: 'labs', patientId: 'p1' });
  });

  it('refuses to send a value that is not a number or beyond the plausible limit', async () => {
    const { fixture, ctrl, el } = await open();
    const [creat] = rows(el) as [HTMLElement];
    set(creat.querySelector('input[aria-label=Value]') as HTMLInputElement, '99');
    fixture.detectChanges();
    el.querySelector<HTMLFormElement>('form')?.dispatchEvent(new Event('submit'));
    fixture.detectChanges();
    ctrl.expectNone(`${API_BASE}/labs/patients/p1/reports`);
    expect(el.textContent).toContain('outside the plausible range');
  });

  it('puts a 422 on results[1].unit on the second row that was sent, even when the first row was left blank', async () => {
    const { fixture, ctrl, el } = await open();
    const [, egfr] = rows(el) as [HTMLElement, HTMLElement];
    set(egfr.querySelector('input[aria-label=Value]') as HTMLInputElement, '38'); // row 0 (creatinine) stays blank
    fixture.detectChanges();
    el.querySelector<HTMLFormElement>('form')?.dispatchEvent(new Event('submit'));
    ctrl.expectOne(`${API_BASE}/labs/patients/p1/reports`).flush(
      {
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Invalid.',
          request_id: 'req-3',
          details: [{ field: 'results[0].unit', issue: 'Unit not accepted' }],
        },
      },
      { status: 422, statusText: 'x' },
    );
    fixture.detectChanges();
    const errs = Array.from(el.querySelectorAll('.lab-row .err')).map((e) => e.textContent?.trim());
    expect(errs).toEqual(['Unit not accepted']);
    expect(rows(el)[1]?.querySelector('.err')?.textContent).toContain('Unit not accepted'); // on the EGFR row
    expect(el.textContent).toContain('req-3');
  });
});
