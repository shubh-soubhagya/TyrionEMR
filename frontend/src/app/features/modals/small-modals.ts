// html:885-889 (condition), 903-907 (medication), 909-913 (allergy), 640-642 (confirm)
import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { toFormProblem, type FormProblem } from '@core/api/form-errors';
import { ROUTE_OPTIONS } from '@core/api/mappers/patient.mapper';
import { ChartApi } from '@core/data/chart.api';
import { isoDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrModalShell } from '@shared/ui/modal-shell/modal-shell';
import { ToastService } from '@shared/ui/toast/toast.service';

// ICD-10 as the server checks it: a letter, two characters, then an optional dot and one to four characters
const ICD10 = /^[A-Za-z][0-9][0-9A-Za-z](\.[0-9A-Za-z]{1,4})?$/;
const NONE: FormProblem = { errors: {}, general: '', requestId: null, code: null, conflict: false };

@Component({
  selector: 'emr-condition-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell title="Add condition" (closed)="closed.emit()">
      <form [formGroup]="form" novalidate (ngSubmit)="submit()">
        <div>
          @if (problem().general) {
            <div class="alert danger" style="margin-bottom: 12px" role="alert">
              <div>
                <b>{{ problem().general }}</b>
                @if (problem().requestId; as id) {
                  <div class="small muted">Reference: {{ id }}</div>
                }
              </div>
            </div>
          }
        </div>
        <div class="f-row">
          <label class="fld"
            ><span class="fld-l">ICD-10 code</span>
            <input
              formControlName="icd"
              maxlength="10"
              placeholder="N18.32"
              [class.invalid]="problem().errors['icd']"
            /><span class="err">{{ problem().errors['icd'] }}</span></label
          >
          <label class="fld"
            ><span class="fld-l">Category</span>
            <select formControlName="cat">
              <option value="nephrology">Nephrology diagnosis</option>
              <option value="comorbidity">Comorbidity</option>
            </select></label
          >
        </div>
        <label class="fld"
          ><span class="fld-l">Description<b class="req">*</b></span>
          <input
            formControlName="desc"
            maxlength="160"
            [class.invalid]="problem().errors['desc']"
          />
          <span class="err">{{ problem().errors['desc'] }}</span></label
        >
        <label class="fld"
          ><span class="fld-l">Onset date</span>
          <input
            type="date"
            formControlName="onset"
            [max]="today"
            [class.invalid]="problem().errors['onset']"
          />
          <span class="err">{{ problem().errors['onset'] }}</span></label
        >
        <label class="chk" style="margin-bottom: 6px"
          ><input type="checkbox" formControlName="primary" /> Make this the primary
          diagnosis</label
        >
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit" [disabled]="busy()">Add condition</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class ConditionModal {
  private readonly api = inject(ChartApi);
  private readonly modals = inject(ModalService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly today = isoDate(Date.now());
  protected readonly busy = signal(false);
  protected readonly problem = signal<FormProblem>(NONE);
  protected readonly form = this.fb.group({
    icd: '',
    cat: 'nephrology' as 'nephrology' | 'comorbidity',
    desc: '',
    onset: '',
    primary: false,
  });

  protected submit(): void {
    if (this.busy()) return;
    const v = this.form.getRawValue();
    const errors: Record<string, string> = {};
    if (!v.desc.trim()) errors['desc'] = 'Description is required.';
    // same shape the server checks (ICD-10: a letter, two characters, then an optional dot and 1 to 4 characters)
    if (v.icd.trim() && !ICD10.test(v.icd.trim()))
      errors['icd'] = 'Enter a valid ICD-10 code, for example N18.3 or E11.22.';
    if (v.onset && new Date(v.onset) > new Date())
      errors['onset'] = 'Onset cannot be in the future.';
    const n = Object.keys(errors).length;
    this.problem.set({
      ...NONE,
      errors,
      general: n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '',
    });
    if (n) return;
    this.busy.set(true);
    this.api
      .addCondition(this.patientId(), {
        description: v.desc.trim(),
        category: v.cat,
        ...(v.icd.trim() ? { icd10_code: v.icd.trim().toUpperCase() } : {}),
        ...(v.onset ? { onset_date: v.onset } : {}),
        is_primary: v.primary,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.modals.notifyChanged('conditions', this.patientId());
          this.closed.emit();
          this.toast.show('Condition added.');
        },
        error: (e: unknown) => {
          this.busy.set(false);
          this.problem.set(
            toFormProblem(e, { icd10_code: 'icd', description: 'desc', onset_date: 'onset' }),
          );
        },
      });
  }
}

@Component({
  selector: 'emr-med-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell title="Add medication" (closed)="closed.emit()">
      <form [formGroup]="form" novalidate (ngSubmit)="submit()">
        <div>
          @if (problem().general) {
            <div class="alert danger" style="margin-bottom: 12px" role="alert">
              <div>
                <b>{{ problem().general }}</b>
                @if (problem().requestId; as id) {
                  <div class="small muted">Reference: {{ id }}</div>
                }
              </div>
            </div>
          }
        </div>
        <label class="fld"
          ><span class="fld-l">Medication name<b class="req">*</b></span>
          <input formControlName="name" maxlength="80" [class.invalid]="problem().errors['name']" />
          <span class="err">{{ problem().errors['name'] }}</span></label
        >
        <div class="f-row">
          <label class="fld"
            ><span class="fld-l">Dose<b class="req">*</b></span>
            <input
              formControlName="dose"
              placeholder="50 mg"
              [class.invalid]="problem().errors['dose']"
            />
            <span class="err">{{ problem().errors['dose'] }}</span></label
          >
          <label class="fld"
            ><span class="fld-l">Route</span>
            <select formControlName="route">
              @for (r of routes; track r) {
                <option>{{ r }}</option>
              }
            </select></label
          >
        </div>
        <label class="fld"
          ><span class="fld-l">Frequency<b class="req">*</b></span>
          <input
            formControlName="freq"
            placeholder="Once daily"
            [class.invalid]="problem().errors['freq']"
          />
          <span class="err">{{ problem().errors['freq'] }}</span></label
        >
        <label class="fld"
          ><span class="fld-l">Start date</span> <input type="date" formControlName="start" /><span
            class="err"
          ></span
        ></label>
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit" [disabled]="busy()">Add medication</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class MedModal {
  private readonly api = inject(ChartApi);
  private readonly modals = inject(ModalService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly routes = ROUTE_OPTIONS;
  protected readonly busy = signal(false);
  protected readonly problem = signal<FormProblem>(NONE);
  protected readonly form = this.fb.group({
    name: '',
    dose: '',
    route: 'Oral',
    freq: '',
    start: isoDate(Date.now()),
  });

  protected submit(): void {
    if (this.busy()) return;
    const v = this.form.getRawValue();
    const errors: Record<string, string> = {};
    if (!v.name.trim()) errors['name'] = 'Medication name is required.';
    if (!v.dose.trim()) errors['dose'] = 'Dose is required.';
    if (!v.freq.trim()) errors['freq'] = 'Frequency is required.';
    const n = Object.keys(errors).length;
    this.problem.set({
      ...NONE,
      errors,
      general: n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '',
    });
    if (n) return;
    this.busy.set(true);
    this.api
      .addMedication(this.patientId(), {
        name: v.name,
        dose: v.dose,
        route: v.route,
        freq: v.freq,
        start: v.start,
        end: null,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.modals.notifyChanged('medications', this.patientId());
          this.closed.emit();
          this.toast.show('Medication added.');
        },
        error: (e: unknown) => {
          this.busy.set(false);
          this.problem.set(
            toFormProblem(e, {
              name: 'name',
              dose: 'dose',
              frequency: 'freq',
              start_date: 'start',
            }),
          );
        },
      });
  }
}

@Component({
  selector: 'emr-allergy-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell title="Add allergy" (closed)="closed.emit()">
      <form [formGroup]="form" novalidate (ngSubmit)="submit()">
        <div>
          @if (problem().general) {
            <div class="alert danger" style="margin-bottom: 12px" role="alert">
              <div>
                <b>{{ problem().general }}</b>
                @if (problem().requestId; as id) {
                  <div class="small muted">Reference: {{ id }}</div>
                }
              </div>
            </div>
          }
        </div>
        <label class="fld"
          ><span class="fld-l">Allergen<b class="req">*</b></span>
          <input
            formControlName="allergen"
            maxlength="80"
            [class.invalid]="problem().errors['allergen']"
          />
          <span class="err">{{ problem().errors['allergen'] }}</span></label
        >
        <label class="fld"
          ><span class="fld-l">Reaction</span>
          <input formControlName="reaction" placeholder="Rash, anaphylaxis..." /><span
            class="err"
          ></span
        ></label>
        <label class="fld"
          ><span class="fld-l">Severity</span>
          <select formControlName="severity">
            <option value="mild">Mild</option>
            <option value="moderate">Moderate</option>
            <option value="severe">Severe</option>
          </select></label
        >
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit" [disabled]="busy()">Add allergy</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class AllergyModal {
  private readonly api = inject(ChartApi);
  private readonly modals = inject(ModalService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly busy = signal(false);
  protected readonly problem = signal<FormProblem>(NONE);
  protected readonly form = this.fb.group({
    allergen: '',
    reaction: '',
    severity: 'moderate' as 'mild' | 'moderate' | 'severe',
  });

  protected submit(): void {
    if (this.busy()) return;
    const v = this.form.getRawValue();
    if (!v.allergen.trim()) {
      this.problem.set({
        ...NONE,
        errors: { allergen: 'Allergen is required.' },
        general: 'Fix 1 field to continue.',
      });
      return;
    }
    this.busy.set(true);
    this.api
      .addAllergy(this.patientId(), {
        allergen: v.allergen.trim(),
        reaction: v.reaction.trim() || null,
        severity: v.severity,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.modals.notifyChanged('allergies', this.patientId());
          this.closed.emit();
          this.toast.show('Allergy added. Allergy status is now "has allergies".');
        },
        error: (e: unknown) => {
          this.busy.set(false);
          const p = toFormProblem(e, { allergen: 'allergen' });
          // 409 DUPLICATE_ALLERGY belongs on the allergen field, not in a banner
          this.problem.set(
            p.code === 'DUPLICATE_ALLERGY'
              ? { ...p, errors: { allergen: p.general }, general: '' }
              : p,
          );
        },
      });
  }
}

@Component({
  selector: 'emr-confirm-modal',
  imports: [EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell [title]="title()" size="sm" (closed)="modals.answerConfirm(false)">
      <p style="margin-bottom: 18px; color: var(--ink-2)">{{ message() }}</p>
      <div class="form-actions" style="border: 0; padding: 0; margin: 0">
        <button class="btn" type="button" (click)="modals.answerConfirm(false)">Cancel</button>
        <button
          class="btn"
          [class.danger]="danger()"
          [class.primary]="!danger()"
          type="button"
          (click)="modals.answerConfirm(true)"
        >
          {{ ok() }}
        </button>
      </div>
    </emr-modal-shell>
  `,
})
export class ConfirmModal {
  protected readonly modals = inject(ModalService);
  readonly title = input.required<string>();
  readonly message = input.required<string>();
  readonly ok = input('Confirm');
  readonly danger = input(false);
}
