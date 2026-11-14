// html:925-979. View a final encounter; create, edit and finalize a draft.
// patient-svc owns the rules (draft/final, the problem-list linkage, version checks); the form keeps only the vitals
// limits of docs/decisions.md D1, which are tighter than the server's.
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
} from '@angular/forms';
import { ApiError } from '@core/api/api-error';
import { toFormProblem, type FormProblem } from '@core/api/form-errors';
import { encounterToWriteDto } from '@core/api/mappers/patient.mapper';
import { remoteSignal } from '@core/api/remote-signal';
import { AuthService } from '@core/auth/auth.service';
import { EncountersApi, type EncounterSaved } from '@core/data/encounters.api';
import type { Encounter, EncounterType, Vitals } from '@core/data/models';
import { PatientsApi } from '@core/data/patients.api';
import { ICD10_HINT, isIcd10 } from '@core/clinical/icd10';
import { fmtDate, fmtDT, localInput } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrNonNegative } from '@shared/ui/number-keys/number-keys';
import { EmrModalShell } from '@shared/ui/modal-shell/modal-shell';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { ToastService } from '@shared/ui/toast/toast.service';
import { typeLabel } from '@shared/utils/labels';
import { Observable, switchMap } from 'rxjs';

type VitalKey = keyof Vitals;
type DxGroup = FormGroup<{
  icd: FormControl<string>;
  desc: FormControl<string>;
  prob: FormControl<boolean>;
}>;
/** Blocking plausibility limits (docs/decisions.md D1). Out-of-normal but plausible values only warn. */
const VIT: readonly {
  key: VitalKey;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: string;
}[] = [
  { key: 'sys', label: 'Systolic BP', unit: 'mmHg', min: 60, max: 260, step: '1' },
  { key: 'dia', label: 'Diastolic BP', unit: 'mmHg', min: 30, max: 160, step: '1' },
  { key: 'hr', label: 'Heart rate', unit: 'bpm', min: 30, max: 220, step: '1' },
  { key: 'temp', label: 'Temperature', unit: '°C', min: 34, max: 42, step: '0.1' },
  { key: 'wt', label: 'Weight', unit: 'kg', min: 2, max: 300, step: '0.1' },
];
const SYMPTOM_SUGGESTIONS = [
  'Fatigue',
  'Ankle swelling',
  'Reduced urine output',
  'Nausea',
  'Itching',
  'Breathlessness',
  'Foamy urine',
];

/** API field path -> form control, so a 422 lands on the right input. */
const FIELD: Readonly<Record<string, string>> = {
  encounter_date: 'date',
  encounter_type: 'type',
  chief_complaint: 'cc',
  examination_notes: 'exam',
  assessment: 'assessment',
  plan: 'plan',
  follow_up_date: 'followUp',
  'vitals.systolic_bp': 'sys',
  'vitals.diastolic_bp': 'dia',
  'vitals.heart_rate': 'hr',
  'vitals.temperature_c': 'temp',
  'vitals.weight_kg': 'wt',
  diagnoses: 'dx',
  'diagnoses[].description': 'dx',
  'diagnoses[].icd10_code': 'dx',
};

const NONE: FormProblem = { errors: {}, general: '', requestId: null, code: null, conflict: false };

/** Read-only view of a final encounter (html `encView`, html:925). */
@Component({
  selector: 'emr-encounter-view-modal',
  imports: [EmrModalShell, EmrIcon, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-modal-shell
      [title]="'Encounter' + (e() ? ' on ' + fmtDate(e()!.date) : '')"
      [sub]="sub()"
      size="lg"
      (closed)="closed.emit()"
    >
      <emr-remote-state [remote]="enc.state()" (retry)="enc.reload()">
        @if (e(); as enc) {
          <div class="vit" style="margin-bottom: 16px">
            @for (x of vit; track x.key) {
              <div class="vit-tile">
                <div class="t">{{ x.label }}</div>
                <div class="v">
                  @if (
                    enc.vitals && enc.vitals[x.key] !== null && enc.vitals[x.key] !== undefined
                  ) {
                    {{ enc.vitals[x.key] }}
                  } @else {
                    -
                  }
                  <span class="muted small">{{ x.unit }}</span>
                </div>
              </div>
            }
          </div>
          <dl class="dl" style="grid-template-columns: 150px 1fr">
            <dt>Visit</dt>
            <dd>{{ fmtDT(enc.date) }}, {{ typeLabel(enc.type) }} with {{ enc.clinician }}</dd>
            <dt>Chief complaint</dt>
            <dd>
              @if (enc.cc) {
                {{ enc.cc }}
              } @else {
                <span class="nd">Not documented</span>
              }
            </dd>
            <dt>Symptoms</dt>
            <dd>
              @for (s of enc.symptoms; track s) {
                <span class="chip">{{ s }}</span>&ngsp;
              } @empty {
                <span class="nd">Not documented</span>
              }
            </dd>
            <dt>Examination</dt>
            <dd>
              @if (enc.exam) {
                {{ enc.exam }}
              } @else {
                <span class="nd">Not documented</span>
              }
            </dd>
            <dt>Assessment</dt>
            <dd>
              @if (enc.assessment) {
                {{ enc.assessment }}
              } @else {
                <span class="nd">Not documented</span>
              }
            </dd>
            <dt>Diagnoses</dt>
            <dd>
              @for (d of enc.diagnoses; track $index) {
                <div>
                  <span class="mono">{{ d.icd }}</span> {{ d.desc }}
                </div>
              } @empty {
                <span class="nd">None recorded</span>
              }
            </dd>
            <dt>Plan</dt>
            <dd>
              @if (enc.plan) {
                {{ enc.plan }}
              } @else {
                <span class="nd">Not documented</span>
              }
            </dd>
            <dt>Follow-up</dt>
            <dd>
              @if (enc.followUp) {
                {{ fmtDate(enc.followUp) }}
              } @else {
                <span class="nd">Not set</span>
              }
            </dd>
          </dl>
          <div class="alert info" style="margin-top: 14px">
            <emr-icon name="lock" [size]="16" />
            <div>
              This encounter is final and read-only. Corrections are recorded as a new encounter.
            </div>
          </div>
        }
      </emr-remote-state>
    </emr-modal-shell>
  `,
})
export class EncounterViewModal {
  private readonly api = inject(EncountersApi);
  readonly patientId = input.required<string>();
  readonly encounterId = input.required<string>();
  readonly sub = input<string>();
  readonly closed = output<void>();
  protected readonly vit = VIT;
  protected readonly fmtDate = fmtDate;
  protected readonly fmtDT = fmtDT;
  protected readonly typeLabel = typeLabel;
  protected readonly enc = remoteSignal<Encounter>(
    () => [this.patientId(), this.encounterId()],
    () => this.api.get(this.patientId(), this.encounterId()),
    () => false,
  );
  protected readonly e = computed(() => {
    const s = this.enc.state();
    return s.state === 'ok' ? s.data : null;
  });
}

@Component({
  selector: 'emr-encounter-modal',
  imports: [ReactiveFormsModule, EmrModalShell, EmrIcon, EmrNonNegative],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './encounter-modal.html',
})
export class EncounterModal {
  private readonly api = inject(EncountersApi);
  private readonly patients = inject(PatientsApi);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder).nonNullable;

  readonly patientId = input.required<string>();
  readonly encounterId = input<string | null>(null);
  readonly closed = output<void>();

  protected readonly vit = VIT;
  protected readonly suggestions = SYMPTOM_SUGGESTIONS;
  protected readonly typeLabel = typeLabel;
  protected readonly problem = signal<FormProblem>(NONE);
  protected readonly errors = computed(() => this.problem().errors);
  protected readonly general = computed(() => this.problem().general);
  protected readonly symptoms = signal<string[]>([]);
  protected readonly symptomText = signal('');
  protected readonly busy = signal(false);
  /** Finalizing asks first, inline, so the typed form is never lost to a second dialog. */
  protected readonly confirmingFinal = signal(false);
  /** The draft being edited, as loaded (its version is what the next save sends). */
  protected readonly editing = signal<Encounter | null>(null);
  protected readonly loadFailed = signal(false);
  protected readonly patientMrn = signal('');
  protected readonly clinician = computed(() => this.auth.user()?.fullName ?? '');

  protected readonly form = this.fb.group({
    date: localInput(new Date()),
    type: 'follow_up' as EncounterType,
    sys: '',
    dia: '',
    hr: '',
    temp: '',
    wt: '',
    cc: '',
    exam: '',
    assessment: '',
    plan: '',
    followUp: '',
    dx: this.fb.array<DxGroup>([]),
  });

  constructor() {
    queueMicrotask(() => {
      this.patients
        .detail(this.patientId())
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ next: (p) => this.patientMrn.set(p.mrn), error: () => undefined });
      this.load();
    });
  }

  /** Loads (or reloads after a conflict) the draft being edited. */
  protected load(): void {
    const id = this.encounterId();
    if (!id) return;
    this.api
      .get(this.patientId(), id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (e) => this.fill(e),
        error: (e: unknown) => {
          this.loadFailed.set(true);
          this.problem.set(toFormProblem(e));
        },
      });
  }

  private fill(e: Encounter): void {
    this.editing.set(e);
    this.loadFailed.set(false);
    this.problem.set(NONE);
    const v = e.vitals;
    this.form.patchValue({
      date: localInput(new Date(e.date)),
      type: e.type,
      sys: v?.sys != null ? String(v.sys) : '',
      dia: v?.dia != null ? String(v.dia) : '',
      hr: v?.hr != null ? String(v.hr) : '',
      temp: v?.temp != null ? String(v.temp) : '',
      wt: v?.wt != null ? String(v.wt) : '',
      cc: e.cc,
      exam: e.exam,
      assessment: e.assessment,
      plan: e.plan,
      followUp: e.followUp,
    });
    this.symptoms.set([...e.symptoms]);
    this.dxRows.clear();
    e.diagnoses.forEach((d) => this.dxRows.push(this.newDx(d.icd, d.desc, d.prob === true)));
  }

  protected get dxRows(): FormArray<DxGroup> {
    return this.form.controls.dx;
  }

  protected newDx(icd = '', desc = '', prob = false): DxGroup {
    return this.fb.group({ icd, desc, prob: prob as boolean });
  }

  protected addDx(): void {
    this.dxRows.push(this.newDx());
  }

  protected removeDx(i: number): void {
    this.dxRows.removeAt(i);
  }

  protected onSymptomInput(event: Event): void {
    this.symptomText.set((event.target as HTMLInputElement).value);
  }

  protected addSymptom(event?: Event): void {
    event?.preventDefault();
    const s = this.symptomText().trim();
    if (!s) return;
    if (!this.symptoms().some((x) => x.toLowerCase() === s.toLowerCase()))
      this.symptoms.update((l) => [...l, s]);
    this.symptomText.set('');
    const el = document.getElementById('sym-in') as HTMLInputElement | null;
    if (el) {
      el.value = '';
      el.focus();
    }
  }

  protected removeSymptom(s: string): void {
    this.symptoms.update((l) => l.filter((x) => x !== s));
  }

  /** Soft warning: plausible but outside the usual range. Never blocks saving (docs/decisions.md D1). */
  protected readonly softWarning = computed(() => {
    const v = this.form.getRawValue();
    const sys = parseFloat(String(v.sys));
    const dia = parseFloat(String(v.dia));
    const hr = parseFloat(String(v.hr));
    const temp = parseFloat(String(v.temp));
    const out: string[] = [];
    if (sys >= 140 || dia >= 90)
      out.push(`Blood pressure ${v.sys || '?'}/${v.dia || '?'} is above the usual range.`);
    else if (sys < 90 || dia < 60)
      out.push(`Blood pressure ${v.sys || '?'}/${v.dia || '?'} is below the usual range.`);
    if (hr < 50 || hr > 100) out.push(`Heart rate ${hr} bpm is outside 50 to 100.`);
    if (temp >= 38 || temp < 36) out.push(`Temperature ${temp} °C is outside 36 to 38.`);
    return out;
  });

  /** Validates, then saves a draft or (after the inline confirmation) finalizes. */
  protected submit(mode: 'draft' | 'final', confirmed = false): void {
    if (this.busy()) return;
    const v = this.form.getRawValue();
    const errs: Record<string, string> = {};
    const t = (s: string) => s.trim();
    if (!v.date) errs['date'] = 'Visit date is required.';
    else if (new Date(v.date).getTime() > Date.now() + 60000)
      errs['date'] = 'Visit date cannot be in the future.';

    const vitals: Vitals = { sys: null, dia: null, hr: null, temp: null, wt: null };
    VIT.forEach((x) => {
      // number inputs hand the form a number (or null), not a string
      const raw = String(v[x.key] ?? '').trim();
      if (raw === '') return;
      const n = parseFloat(raw);
      if (isNaN(n) || n < x.min || n > x.max) errs[x.key] = `Enter ${x.min} to ${x.max} ${x.unit}.`;
      else vitals[x.key] = n;
    });
    if (
      vitals.sys != null &&
      vitals.dia != null &&
      !errs['sys'] &&
      !errs['dia'] &&
      vitals.sys <= vitals.dia
    )
      errs['sys'] = 'Systolic must be higher than diastolic.';
    if (v.followUp && v.date && v.followUp < v.date.slice(0, 10))
      errs['followUp'] = 'Follow-up cannot be before the visit.';
    const dx = v.dx
      .map((d) => ({ icd: t(d.icd).toUpperCase(), desc: t(d.desc), prob: d.prob }))
      .filter((d) => d.icd || d.desc);
    if (dx.some((d) => !d.desc)) errs['dx'] = 'Each diagnosis needs a description.';
    else {
      const bad = dx.findIndex((d) => d.icd && !isIcd10(d.icd));
      if (bad >= 0)
        errs['dx'] =
          `Diagnosis ${bad + 1}: ${ICD10_HINT} Leave the code empty if you do not have one.`;
    }
    if (mode === 'final') {
      if (!t(v.cc)) errs['cc'] = 'Chief complaint is required to finalize.';
      if (!t(v.assessment)) errs['assessment'] = 'Assessment is required to finalize.';
      if (!t(v.plan)) errs['plan'] = 'Plan is required to finalize.';
    }
    const n = Object.keys(errs).length;
    this.problem.set({
      ...NONE,
      errors: errs,
      general: n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '',
    });
    this.confirmingFinal.set(false);
    if (n) {
      queueMicrotask(() => document.querySelector<HTMLElement>('.modal .invalid')?.focus());
      return;
    }
    if (mode === 'final' && !confirmed) {
      this.confirmingFinal.set(true);
      return;
    }
    const body = encounterToWriteDto({
      date: new Date(v.date).toISOString(),
      type: v.type,
      cc: t(v.cc),
      symptoms: this.symptoms(),
      exam: t(v.exam),
      assessment: t(v.assessment),
      plan: t(v.plan),
      followUp: v.followUp,
      vitals: Object.values(vitals).some((x) => x != null) ? vitals : null,
      diagnoses: dx,
      status: 'draft',
    });
    const pid = this.patientId();
    const existing = this.editing();
    let call: Observable<EncounterSaved>;
    if (!existing) {
      call = this.api.create(pid, { ...body, status: mode });
    } else if (mode === 'draft') {
      call = this.api.update(pid, existing.id, body, existing.version);
    } else {
      // Save the edits, then finalize with the version the save returned.
      call = this.api
        .update(pid, existing.id, body, existing.version)
        .pipe(switchMap((s) => this.api.finalize(pid, existing.id, s.encounter.version)));
    }
    this.busy.set(true);
    call.subscribe({
      next: (saved) => this.saved(saved, mode),
      error: (e: unknown) => this.failed(e),
    });
  }

  private saved(s: EncounterSaved, mode: 'draft' | 'final'): void {
    this.busy.set(false);
    this.modals.notifyChanged('encounters', this.patientId());
    if (s.added > 0 || s.reactivated > 0) this.modals.notifyChanged('conditions', this.patientId());
    this.modals.close();
    this.toast.show(
      mode === 'final'
        ? `Encounter finalized${s.added ? `. ${s.added} condition${s.added > 1 ? 's' : ''} added to the problem list` : ''}.`
        : 'Draft saved.',
    );
  }

  private failed(e: unknown): void {
    this.busy.set(false);
    this.confirmingFinal.set(false);
    if (e instanceof ApiError && e.code === 'ENCOUNTER_FINAL') {
      // Someone finalized it meanwhile: say so and show the saved encounter instead.
      this.toast.show(e.message, 'err');
      this.modals.notifyChanged('encounters', this.patientId());
      this.modals.open({
        kind: 'encounter-view',
        patientId: this.patientId(),
        encounterId: this.encounterId() ?? '',
        sub: 'Final',
      });
      return;
    }
    this.problem.set(toFormProblem(e, FIELD));
  }

  protected async deleteDraft(): Promise<void> {
    const id = this.encounterId();
    if (!id) return;
    const ok = await this.modals.confirm({
      title: 'Delete draft encounter',
      message: 'The draft is removed from the chart. This cannot be undone from the UI.',
      ok: 'Delete draft',
      danger: true,
    });
    if (!ok) return;
    this.api.delete(this.patientId(), id).subscribe({
      next: () => {
        this.modals.notifyChanged('encounters', this.patientId());
        this.toast.show('Draft deleted.');
      },
      error: (e: unknown) => this.toast.show(toFormProblem(e).general, 'err'),
    });
  }
}
