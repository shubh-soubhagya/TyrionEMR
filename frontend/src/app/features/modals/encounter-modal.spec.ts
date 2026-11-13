import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { API_BASE } from '@core/api/endpoints';
import { errorInterceptor } from '@core/http/error.interceptor';
import { ModalService } from '@core/ui/modal.service';
import { ToastService } from '@shared/ui/toast/toast.service';
import { EncounterModal } from './encounter-modal';

const ENC = `${API_BASE}/patients/p1/encounters`;

function create(encounterId: string | null = null) {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  const fixture = TestBed.createComponent(EncounterModal);
  fixture.componentRef.setInput('patientId', 'p1');
  fixture.componentRef.setInput('encounterId', encounterId);
  fixture.detectChanges();
  const ctrl = TestBed.inject(HttpTestingController);
  const el = fixture.nativeElement as HTMLElement;
  return { fixture, ctrl, el };
}

const type = (el: HTMLElement, selector: string, value: string) => {
  const input = el.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (!input) throw new Error('missing ' + selector);
  input.value = value;
  input.dispatchEvent(new Event('input'));
};

const button = (el: HTMLElement, text: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === text);

async function flushLoads(ctrl: HttpTestingController) {
  await Promise.resolve();
  ctrl
    .match((r) => r.url === `${API_BASE}/patients/p1`)
    .forEach((r) =>
      r.flush({
        mrn: 'PT-000101',
        first_name: 'A',
        last_name: 'B',
        sex: 'M',
        date_of_birth: '1970-01-01',
        version: 1,
        allergy_status: 'unknown',
        phone: null,
        email: null,
        address: null,
        past_medical_history: null,
        family_history: null,
        social_history: null,
        created_at: '',
      }),
    );
}

describe('EncounterModal', () => {
  it('asks for the chief complaint, assessment and plan before finalizing, without calling the server', async () => {
    const { fixture, ctrl, el } = create();
    await flushLoads(ctrl);
    button(el, 'Finalize encounter')?.click();
    fixture.detectChanges();
    expect(el.textContent).toContain('Chief complaint is required to finalize.');
    expect(el.textContent).toContain('Fix 3 fields to continue.');
    ctrl.expectNone(ENC);
  });

  it('blocks implausible vitals on the client (decisions D1)', async () => {
    const { fixture, ctrl, el } = create();
    await flushLoads(ctrl);
    type(el, '.vit label:nth-child(1) input', '400');
    fixture.detectChanges();
    button(el, 'Save draft')?.click();
    fixture.detectChanges();
    expect(el.textContent).toContain('Enter 60 to 260 mmHg.');
    ctrl.expectNone(ENC);
  });

  it('asks inline before finalizing, then creates as final', async () => {
    const { fixture, ctrl, el } = create();
    await flushLoads(ctrl);
    type(el, 'input[formcontrolname=cc]', 'Review');
    type(el, 'textarea[formcontrolname=assessment]', 'Stable');
    type(el, 'textarea[formcontrolname=plan]', 'Continue');
    fixture.detectChanges();
    button(el, 'Finalize encounter')?.click();
    fixture.detectChanges();
    ctrl.expectNone(ENC); // nothing is sent until the person confirms
    expect(el.textContent).toContain('Finalize this encounter?');
    button(el, 'Finalize')?.click();
    const req = ctrl.expectOne(ENC);
    expect(req.request.body).toMatchObject({ status: 'final', chief_complaint: 'Review' });
    req.flush({
      encounter: {
        id: 'e1',
        patient_id: 'p1',
        encounter_date: '2026-11-13T04:30:00Z',
        encounter_type: 'follow_up',
        clinician_id: 'u',
        clinician_name: 'Dr',
        chief_complaint: 'Review',
        symptoms: [],
        examination_notes: null,
        assessment: 'Stable',
        plan: 'Continue',
        follow_up_date: null,
        status: 'final',
        vitals: null,
        diagnoses: [],
        finalized_at: 'x',
        finalized_by: 'u',
        version: 2,
        created_at: '',
        updated_at: '',
      },
      problem_list_changes: { added: 1 },
    });
    const modals = TestBed.inject(ModalService);
    expect(modals.changed()).toMatchObject({ kind: 'conditions', patientId: 'p1' });
  });

  it('puts a 422 on the right field and keeps what was typed', async () => {
    const { fixture, ctrl, el } = create();
    await flushLoads(ctrl);
    type(el, '.vit label:nth-child(1) input', '120');
    type(el, '.vit label:nth-child(2) input', '80');
    fixture.detectChanges();
    button(el, 'Save draft')?.click();
    ctrl.expectOne(ENC).flush(
      {
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Invalid.',
          request_id: 'req-5',
          details: [{ field: 'vitals.systolic_bp', issue: 'Too high for the server' }],
        },
      },
      { status: 422, statusText: 'Unprocessable' },
    );
    fixture.detectChanges();
    expect(el.textContent).toContain('Too high for the server');
    expect(el.textContent).toContain('req-5');
    expect(el.querySelector<HTMLInputElement>('.vit label:nth-child(1) input')?.value).toBe('120');
  });
});

describe('EncounterModal editing a draft', () => {
  const detail = (over: Record<string, unknown> = {}) => ({
    id: 'e1',
    patient_id: 'p1',
    encounter_date: '2026-11-13T04:30:00Z',
    encounter_type: 'follow_up',
    clinician_id: 'u',
    clinician_name: 'Dr',
    chief_complaint: 'Review',
    symptoms: [],
    examination_notes: null,
    assessment: 'ok',
    plan: 'go',
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
    version: 1,
    created_at: '',
    updated_at: '',
    ...over,
  });

  it('saves the edits, then finalizes with the new version, and reports the conditions the server added', async () => {
    const { fixture, ctrl, el } = create('e1');
    await Promise.resolve();
    ctrl.expectOne(`${ENC}/e1`).flush(detail());
    await flushLoads(ctrl);
    fixture.detectChanges();
    expect(el.querySelector<HTMLInputElement>('.dx-row input[type=checkbox]')?.checked).toBe(true); // flag survives the reload
    button(el, 'Finalize encounter')?.click();
    fixture.detectChanges();
    button(el, 'Finalize')?.click();
    const patch = ctrl.expectOne(`${ENC}/e1`);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body.version).toBe(1);
    patch.flush({ encounter: detail({ version: 2 }), problem_list_changes: { added: 0 } });
    const fin = ctrl.expectOne(`${ENC}/e1/finalize`);
    expect(fin.request.body).toEqual({ version: 2 });
    fin.flush({
      encounter: detail({ status: 'final', version: 3 }),
      problem_list_changes: { added: 1 },
    });
    fixture.detectChanges();
    const toasts = TestBed.inject(ToastService)
      .toasts()
      .map((t) => t.message);
    expect(toasts).toContain('Encounter finalized. 1 condition added to the problem list.');
  });
});
