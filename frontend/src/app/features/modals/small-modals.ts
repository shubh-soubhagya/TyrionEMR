// html:885-889 (condition), 903-907 (medication), 909-913 (allergy), 640-642 (confirm)
import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { DbService } from '../../core/data/db.service';
import { isoDate } from '../../core/format';
import { ModalService } from '../../core/ui/modal.service';
import { EmrModalShell } from '../../shared/ui/modal-shell/modal-shell';
import { ToastService } from '../../shared/ui/toast/toast.service';

@Component({
  selector: 'emr-condition-modal',
  imports: [ReactiveFormsModule, EmrModalShell],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell title="Add condition" (closed)="closed.emit()">
      <form [formGroup]="form" novalidate (ngSubmit)="submit()">
        <div>
          @if (general()) {
            <div class="alert danger" style="margin-bottom: 12px"><div><b>{{ general() }}</b></div></div>
          }
        </div>
        <div class="f-row">
          <label class="fld"><span class="fld-l">ICD-10 code</span>
            <input formControlName="icd" maxlength="10" placeholder="N18.32" /><span class="err"></span></label>
          <label class="fld"><span class="fld-l">Category</span>
            <select formControlName="cat">
              <option value="nephrology">Nephrology diagnosis</option>
              <option value="comorbidity">Comorbidity</option>
            </select></label>
        </div>
        <label class="fld"><span class="fld-l">Description<b class="req">*</b></span>
          <input formControlName="desc" maxlength="160" [class.invalid]="errors()['desc']" />
          <span class="err">{{ errors()['desc'] }}</span></label>
        <label class="fld"><span class="fld-l">Onset date</span>
          <input type="date" formControlName="onset" [max]="today" [class.invalid]="errors()['onset']" />
          <span class="err">{{ errors()['onset'] }}</span></label>
        <label class="chk" style="margin-bottom: 6px"><input type="checkbox" formControlName="primary" /> Make this the primary diagnosis</label>
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit">Add condition</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class ConditionModal {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly today = isoDate(Date.now());
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly form = this.fb.group({
    icd: '',
    cat: 'nephrology' as 'nephrology' | 'comorbidity',
    desc: '',
    onset: '',
    primary: false,
  });

  protected submit(): void {
    const v = this.form.getRawValue();
    const errs: Record<string, string> = {};
    if (!v.desc.trim()) errs['desc'] = 'Description is required.';
    if (v.onset && new Date(v.onset) > new Date()) errs['onset'] = 'Onset cannot be in the future.';
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    if (n) return;
    this.db.addCondition(this.patientId(), { icd: v.icd, desc: v.desc, cat: v.cat, onset: v.onset, primary: v.primary });
    this.closed.emit();
    this.toast.show('Condition added.');
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
          @if (general()) {
            <div class="alert danger" style="margin-bottom: 12px"><div><b>{{ general() }}</b></div></div>
          }
        </div>
        <label class="fld"><span class="fld-l">Medication name<b class="req">*</b></span>
          <input formControlName="name" maxlength="80" [class.invalid]="errors()['name']" />
          <span class="err">{{ errors()['name'] }}</span></label>
        <div class="f-row">
          <label class="fld"><span class="fld-l">Dose<b class="req">*</b></span>
            <input formControlName="dose" placeholder="50 mg" [class.invalid]="errors()['dose']" />
            <span class="err">{{ errors()['dose'] }}</span></label>
          <label class="fld"><span class="fld-l">Route</span>
            <select formControlName="route">
              <option>Oral</option><option>SC</option><option>IV</option><option>Topical</option><option>Inhaled</option>
            </select></label>
        </div>
        <label class="fld"><span class="fld-l">Frequency<b class="req">*</b></span>
          <input formControlName="freq" placeholder="Once daily" [class.invalid]="errors()['freq']" />
          <span class="err">{{ errors()['freq'] }}</span></label>
        <label class="fld"><span class="fld-l">Start date</span>
          <input type="date" formControlName="start" /><span class="err"></span></label>
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit">Add medication</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class MedModal {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly form = this.fb.group({
    name: '',
    dose: '',
    route: 'Oral',
    freq: '',
    start: isoDate(Date.now()),
  });

  protected submit(): void {
    const v = this.form.getRawValue();
    const errs: Record<string, string> = {};
    if (!v.name.trim()) errs['name'] = 'Medication name is required.';
    if (!v.dose.trim()) errs['dose'] = 'Dose is required.';
    if (!v.freq.trim()) errs['freq'] = 'Frequency is required.';
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    if (n) return;
    this.db.addMedication(this.patientId(), {
      name: v.name.trim(),
      dose: v.dose.trim(),
      route: v.route,
      freq: v.freq.trim(),
      start: v.start,
    });
    this.closed.emit();
    this.toast.show('Medication added.');
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
          @if (general()) {
            <div class="alert danger" style="margin-bottom: 12px"><div><b>{{ general() }}</b></div></div>
          }
        </div>
        <label class="fld"><span class="fld-l">Allergen<b class="req">*</b></span>
          <input formControlName="allergen" maxlength="80" [class.invalid]="errors()['allergen']" />
          <span class="err">{{ errors()['allergen'] }}</span></label>
        <label class="fld"><span class="fld-l">Reaction</span>
          <input formControlName="reaction" placeholder="Rash, anaphylaxis..." /><span class="err"></span></label>
        <label class="fld"><span class="fld-l">Severity</span>
          <select formControlName="severity">
            <option value="mild">Mild</option>
            <option value="moderate">Moderate</option>
            <option value="severe">Severe</option>
          </select></label>
        <div class="form-actions">
          <button type="button" class="btn" (click)="closed.emit()">Cancel</button>
          <button class="btn primary" type="submit">Add allergy</button>
        </div>
      </form>
    </emr-modal-shell>
  `,
})
export class AllergyModal {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;
  readonly patientId = input.required<string>();
  readonly closed = output<void>();
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly form = this.fb.group({
    allergen: '',
    reaction: '',
    severity: 'moderate' as 'mild' | 'moderate' | 'severe',
  });

  protected submit(): void {
    const v = this.form.getRawValue();
    if (!v.allergen.trim()) {
      this.errors.set({ allergen: 'Allergen is required.' });
      this.general.set('Fix 1 field to continue.');
      return;
    }
    this.db.addAllergy(this.patientId(), {
      allergen: v.allergen.trim(),
      reaction: v.reaction.trim(),
      severity: v.severity,
    });
    this.closed.emit();
    this.toast.show('Allergy added. Allergy status is now "has allergies".');
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
        <button class="btn" [class.danger]="danger()" [class.primary]="!danger()" type="button" (click)="modals.answerConfirm(true)">
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
