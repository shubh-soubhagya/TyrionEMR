// html:802-833
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormBuilder } from '@angular/forms';
import { ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Sex } from '../../core/clinical/lab-tests';
import { AppError, DbService } from '../../core/data/db.service';
import { AllergyStatus } from '../../core/data/models';
import { ageOf, isoDate } from '../../core/format';
import { EmrModalShell } from '../../shared/ui/modal-shell/modal-shell';
import { ToastService } from '../../shared/ui/toast/toast.service';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^[+0-9 ()-]{7,20}$/;

@Component({
  selector: 'emr-patient-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-modal.html',
})
export class PatientModal {
  private readonly db = inject(DbService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;

  /** Existing patient id for edit, null to register. */
  readonly patientId = input<string | null>(null);
  readonly closed = output<void>();

  protected readonly today = isoDate(Date.now());
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');

  protected readonly patient = computed(() => {
    const id = this.patientId();
    return id ? this.db.patient(id) : null;
  });

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
    als: 'unknown' as AllergyStatus,
  });

  constructor() {
    queueMicrotask(() => {
      const p = this.patient();
      if (p) {
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
      }
    });
  }

  protected submit(): void {
    const v = this.form.getRawValue();
    const t = (s: string) => s.trim();
    const errs: Record<string, string> = {};
    if (!t(v.first)) errs['first'] = 'First name is required.';
    if (!t(v.last)) errs['last'] = 'Last name is required.';
    if (!t(v.dob)) errs['dob'] = 'Date of birth is required.';
    else if (new Date(t(v.dob)) > new Date()) errs['dob'] = 'Date of birth cannot be in the future.';
    else if (ageOf(t(v.dob)) > 120) errs['dob'] = 'Check the date of birth. Age would exceed 120.';
    if (t(v.email) && !EMAIL.test(t(v.email))) errs['email'] = 'Enter a valid email address.';
    if (t(v.phone) && !PHONE.test(t(v.phone))) errs['phone'] = 'Use digits, spaces and + only (7 to 20 characters).';
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    if (n) {
      queueMicrotask(() => document.querySelector<HTMLElement>('.modal .invalid')?.focus());
      return;
    }
    const input = {
      first: t(v.first),
      last: t(v.last),
      dob: t(v.dob),
      sex: v.sex,
      phone: t(v.phone),
      email: t(v.email),
      address: t(v.address),
      pmh: t(v.pmh),
      fh: t(v.fh),
      sh: t(v.sh),
      als: v.als,
    };
    try {
      const p = this.patient();
      if (p) {
        this.db.updatePatient(p.id, p.version, input);
        this.closed.emit();
        this.toast.show('Patient details saved.');
      } else {
        const np = this.db.createPatient(input);
        this.closed.emit();
        this.toast.show(`Patient ${np.mrn} registered.`);
        void this.router.navigate(['/patients', np.id, 'overview']);
      }
    } catch (e) {
      this.general.set(e instanceof AppError ? e.message : 'Something went wrong.');
    }
  }
}
