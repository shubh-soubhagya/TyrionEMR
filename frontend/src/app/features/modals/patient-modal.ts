// html:802-833. Register (POST /patients) and edit (PATCH /patients/{id} with the version that was loaded).
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiError } from '@core/api/api-error';
import { describeError } from '@core/api/error-messages';
import type { PatientForm } from '@core/api/mappers/patient.mapper';
import type { Sex } from '@core/clinical/lab-tests';
import { PatientsApi } from '@core/data/patients.api';
import type { Patient } from '@core/data/models';
import { ageOf, isoDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrModalShell } from '@shared/ui/modal-shell/modal-shell';
import { ToastService } from '@shared/ui/toast/toast.service';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^[+0-9 ()-]{7,20}$/;

/** API field name -> form control name, so a 422 lands on the right input. */
const FIELD: Readonly<Record<string, string>> = {
  first_name: 'first',
  last_name: 'last',
  date_of_birth: 'dob',
  phone: 'phone',
  email: 'email',
  address: 'address',
  past_medical_history: 'pmh',
  family_history: 'fh',
  social_history: 'sh',
  allergy_status: 'als',
};

@Component({
  selector: 'emr-patient-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-modal.html',
})
export class PatientModal {
  private readonly api = inject(PatientsApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder).nonNullable;

  /** Existing patient id for edit, null to register. */
  readonly patientId = input<string | null>(null);
  readonly closed = output<void>();

  protected readonly today = isoDate(Date.now());
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly requestId = signal<string | null>(null);
  /** Set after a 409: someone else saved first, so the person must reload before saving again. */
  protected readonly conflict = signal(false);
  protected readonly busy = signal(false);
  /** The patient being edited (loaded from the server, with its version). */
  protected readonly patient = signal<Patient | null>(null);

  protected readonly form = this.fb.group({
    first: '',
    last: '',
    dob: '',
    sex: 'M' as Sex,
    phone: '',
    email: '',
    address: '',
    pmh: '',
    fh: '',
    sh: '',
    als: 'unknown' as 'unknown' | 'nka',
  });

  constructor() {
    queueMicrotask(() => this.load());
  }

  /** Loads (or reloads after a conflict) the patient being edited. */
  protected load(): void {
    const id = this.patientId();
    if (!id) return;
    this.api
      .detail(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.patient.set(p);
          this.conflict.set(false);
          this.general.set('');
          this.form.patchValue({
            first: p.first,
            last: p.last,
            dob: p.dob,
            sex: p.sex,
            phone: p.phone,
            email: p.email,
            address: p.address,
            pmh: p.pmh,
            fh: p.fh,
            sh: p.sh,
          });
        },
        error: (e: unknown) => this.fail(e),
      });
  }

  protected submit(): void {
    if (this.busy() || this.conflict()) return;
    const v = this.form.getRawValue();
    const t = (s: string) => s.trim();
    const errs: Record<string, string> = {};
    if (!t(v.first)) errs['first'] = 'First name is required.';
    if (!t(v.last)) errs['last'] = 'Last name is required.';
    if (!t(v.dob)) errs['dob'] = 'Date of birth is required.';
    else if (new Date(t(v.dob)) > new Date())
      errs['dob'] = 'Date of birth cannot be in the future.';
    else if (ageOf(t(v.dob)) > 120) errs['dob'] = 'Check the date of birth. Age would exceed 120.';
    if (t(v.email) && !EMAIL.test(t(v.email))) errs['email'] = 'Enter a valid email address.';
    if (t(v.phone) && !PHONE.test(t(v.phone)))
      errs['phone'] = 'Use digits, spaces and + only (7 to 20 characters).';
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    this.requestId.set(null);
    if (n) {
      queueMicrotask(() => document.querySelector<HTMLElement>('.modal .invalid')?.focus());
      return;
    }
    const input: PatientForm = {
      first: v.first,
      last: v.last,
      dob: v.dob,
      sex: v.sex,
      phone: v.phone,
      email: v.email,
      address: v.address,
      pmh: v.pmh,
      fh: v.fh,
      sh: v.sh,
      allergyStatus: v.als,
    };
    this.busy.set(true);
    const existing = this.patient();
    if (this.patientId() && existing) {
      this.api.update(existing.id, input, existing.version).subscribe({
        next: () => {
          this.busy.set(false);
          this.modals.notifyChanged('patient', existing.id);
          this.closed.emit();
          this.toast.show('Patient details saved.');
        },
        error: (e: unknown) => this.fail(e),
      });
    } else {
      this.api.create(input).subscribe({
        next: (np) => {
          this.busy.set(false);
          this.closed.emit();
          this.toast.show(`Patient ${np.mrn} registered.`);
          void this.router.navigate(['/patients', np.id, 'overview']);
        },
        error: (e: unknown) => this.fail(e),
      });
    }
  }

  private fail(e: unknown): void {
    this.busy.set(false);
    if (!(e instanceof ApiError)) {
      this.general.set('Something went wrong. Please try again.');
      return;
    }
    const view = describeError(e);
    this.requestId.set(view.requestId);
    if (e.code === 'VERSION_CONFLICT') {
      this.conflict.set(true);
      this.general.set(view.message);
    } else if (e.code === 'VALIDATION_ERROR') {
      const errs: Record<string, string> = {};
      let unplaced = false;
      for (const [field, issue] of e.fieldIssues()) {
        const control = FIELD[field];
        if (control) errs[control] = issue;
        else unplaced = true;
      }
      this.errors.set(errs);
      this.general.set(
        unplaced || Object.keys(errs).length === 0
          ? view.message
          : 'Fix the highlighted fields to continue.',
      );
    } else {
      this.general.set(view.message);
    }
  }
}
