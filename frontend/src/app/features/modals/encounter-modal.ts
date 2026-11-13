// html:925-979
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
} from '@angular/forms';
import { typeLabel } from '../../core/data/analysis';
import { DbService } from '../../core/data/db.service';
import { Encounter, EncounterType, Vitals } from '../../core/data/models';
import { fmtDate, fmtDT, localInput } from '../../core/format';
import { ModalService } from '../../core/ui/modal.service';
import { EmrIcon } from '../../shared/ui/icon/icon';
import { EmrModalShell } from '../../shared/ui/modal-shell/modal-shell';
import { ToastService } from '../../shared/ui/toast/toast.service';

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
  { key: 'sys', label: 'Systolic BP', unit: 'mmHg', min: 60, max: 260, step: 'any' },
  { key: 'dia', label: 'Diastolic BP', unit: 'mmHg', min: 30, max: 160, step: 'any' },
  { key: 'hr', label: 'Heart rate', unit: 'bpm', min: 30, max: 220, step: 'any' },
  { key: 'temp', label: 'Temperature', unit: '°C', min: 34, max: 42, step: '0.1' },
  { key: 'wt', label: 'Weight', unit: 'kg', min: 2, max: 300, step: 'any' },
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

/** Read-only view of a final encounter (html `encView`, html:925). */
@Component({
  selector: 'emr-encounter-view-modal',
  imports: [EmrModalShell, EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (e(); as enc) {
      <emr-modal-shell
        [title]="'Encounter on ' + fmtDate(enc.date)"
        [sub]="sub()"
        size="lg"
        (closed)="closed.emit()"
      >
        <div class="vit" style="margin-bottom: 16px">
          @for (x of vit; track x.key) {
            <div class="vit-tile">
              <div class="t">{{ x.label }}</div>
              <div class="v">
                @if (enc.vitals && enc.vitals[x.key] !== null && enc.vitals[x.key] !== undefined) {
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
      </emr-modal-shell>
    }
  `,
})
export class EncounterViewModal {
  private readonly db = inject(DbService);
  readonly encounterId = input.required<string>();
  readonly sub = input<string>();
  readonly closed = output<void>();
  protected readonly vit = VIT;
  protected readonly fmtDate = fmtDate;
  protected readonly fmtDT = fmtDT;
  protected readonly typeLabel = typeLabel;
  protected readonly e = computed(() => this.db.encounterById(this.encounterId()));
}

@Component({
  selector: 'emr-encounter-modal',
  imports: [ReactiveFormsModule, EmrModalShell, EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './encounter-modal.html',
})
export class EncounterModal {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly fb = inject(FormBuilder).nonNullable;

  readonly patientId = input.required<string>();
  readonly encounterId = input<string | null>(null);
  readonly closed = output<void>();

  protected readonly vit = VIT;
  protected readonly suggestions = SYMPTOM_SUGGESTIONS;
  protected readonly typeLabel = typeLabel;
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly symptoms = signal<string[]>([]);
  protected readonly symptomText = signal('');
  protected readonly editing = computed<Encounter | null>(() => {
    const id = this.encounterId();
    return id ? (this.db.encounterById(id) ?? null) : null;
  });
  protected readonly patientMrn = computed(() => this.db.patient(this.patientId()).mrn);
  protected readonly clinician = this.db.clinician;

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
      const e = this.editing();
      if (!e) return;
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
      e.diagnoses.forEach((d) => this.dxRows.push(this.newDx(d.icd, d.desc)));
    });
  }

  protected get dxRows(): FormArray<DxGroup> {
    return this.form.controls.dx;
  }

  protected newDx(icd = '', desc = ''): DxGroup {
    return this.fb.group({ icd, desc, prob: false as boolean });
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
    const sys = parseFloat(v.sys);
    const dia = parseFloat(v.dia);
    const hr = parseFloat(v.hr);
    const temp = parseFloat(v.temp);
    const out: string[] = [];
    if (sys >= 140 || dia >= 90)
      out.push(`Blood pressure ${v.sys || '?'}/${v.dia || '?'} is above the usual range.`);
    else if (sys < 90 || dia < 60)
      out.push(`Blood pressure ${v.sys || '?'}/${v.dia || '?'} is below the usual range.`);
    if (hr < 50 || hr > 100) out.push(`Heart rate ${hr} bpm is outside 50 to 100.`);
    if (temp >= 38 || temp < 36) out.push(`Temperature ${temp} °C is outside 36 to 38.`);
    return out;
  });

  protected async submit(mode: 'draft' | 'final'): Promise<void> {
    const v = this.form.getRawValue();
    const errs: Record<string, string> = {};
    const t = (s: string) => s.trim();
    if (!v.date) errs['date'] = 'Visit date is required.';
    else if (new Date(v.date).getTime() > Date.now() + 60000)
      errs['date'] = 'Visit date cannot be in the future.';

    const vitals: Vitals = { sys: null, dia: null, hr: null, temp: null, wt: null };
    VIT.forEach((x) => {
      const raw = t(v[x.key]);
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
    if (mode === 'final') {
      if (!t(v.cc)) errs['cc'] = 'Chief complaint is required to finalize.';
      if (!t(v.assessment)) errs['assessment'] = 'Assessment is required to finalize.';
      if (!t(v.plan)) errs['plan'] = 'Plan is required to finalize.';
    }
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    if (n) {
      queueMicrotask(() => document.querySelector<HTMLElement>('.modal .invalid')?.focus());
      return;
    }
    if (mode === 'final') {
      const ok = await this.modals.confirm({
        title: 'Finalize encounter',
        message:
          'Once finalized, this encounter becomes read-only. Diagnoses marked "Add to problem list" are added to the patient\'s conditions in the same step.',
        ok: 'Finalize',
      });
      if (!ok) {
        // confirm() replaced this modal; reopen it with the same draft target.
        return;
      }
    }
    const result = this.db.saveEncounter(
      this.patientId(),
      this.encounterId(),
      {
        date: v.date,
        type: v.type,
        cc: t(v.cc),
        symptoms: this.symptoms(),
        exam: t(v.exam),
        assessment: t(v.assessment),
        plan: t(v.plan),
        followUp: v.followUp,
        vitals: Object.values(vitals).some((x) => x != null) ? vitals : null,
        diagnoses: dx,
      },
      mode,
    );
    this.modals.close();
    this.toast.show(
      mode === 'final'
        ? `Encounter finalized${result.added ? `. ${result.added} condition${result.added > 1 ? 's' : ''} added to the problem list` : ''}.`
        : 'Draft saved.',
    );
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
    this.db.deleteDraft(id);
    this.toast.show('Draft deleted.');
  }
}
