// html:1036-1067. The test catalog (units with exact string factors, the range for this patient's sex and age) comes from
// lab-svc once per patient. The live preview converts and flags with it using exact decimals (core/clinical/lab-preview),
// and the saved report is recomputed by lab-svc, which is the only authority.
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
} from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin, map, switchMap } from 'rxjs';
import { ApiError } from '@core/api/api-error';
import type { CatalogDto, CatalogItemDto } from '@core/api/dto/lab.dto';
import { toFormProblem, type FormProblem } from '@core/api/form-errors';
import { remoteSignal } from '@core/api/remote-signal';
import { exceedsPlausibleMax, previewResult } from '@core/clinical/lab-preview';
import { parseDec } from '@core/clinical/decimal';
import type { Flag } from '@core/clinical/lab-tests';
import { LabsApi } from '@core/data/labs.api';
import { PatientsApi } from '@core/data/patients.api';
import { localInput } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrModalShell } from '@shared/ui/modal-shell/modal-shell';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { ToastService } from '@shared/ui/toast/toast.service';

type RowGroup = FormGroup<{
  test: FormControl<string>;
  value: FormControl<string>;
  unit: FormControl<string>;
}>;

interface Loaded {
  readonly catalog: CatalogDto;
  readonly name: string;
  readonly mrn: string;
  readonly dob: string;
}

const NONE: FormProblem = { errors: {}, general: '', requestId: null, code: null, conflict: false };

@Component({
  selector: 'emr-lab-modal',
  imports: [ReactiveFormsModule, EmrModalShell, EmrIcon, EmrLabFlag, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './lab-modal.html',
})
export class LabModal {
  private readonly labs = inject(LabsApi);
  private readonly patients = inject(PatientsApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly fb = inject(FormBuilder).nonNullable;

  readonly patientId = input.required<string>();
  readonly closed = output<void>();

  protected readonly nowLocal = localInput();
  protected readonly problem = signal<FormProblem>(NONE);
  /** Per-row messages (a 422 `results[1].unit` lands on row 1, not in a banner). */
  protected readonly rowErrors = signal<Readonly<Record<number, string>>>({});
  protected readonly busy = signal(false);

  /** Patient (sex, age, date of birth) and then that patient's catalog. */
  protected readonly data = remoteSignal<Loaded>(
    this.patientId,
    () =>
      this.patients.get(this.patientId()).pipe(
        switchMap((p) =>
          forkJoin([this.labs.catalogFor(p.id, p.sex, p.age)]).pipe(
            map(([catalog]) => ({
              catalog,
              name: p.first_name + ' ' + p.last_name,
              mrn: p.mrn,
              dob: p.date_of_birth,
            })),
          ),
        ),
      ),
    () => false,
  );
  protected readonly loaded = computed(() => {
    const d = this.data.state();
    return d.state === 'ok' ? d.data : null;
  });
  protected readonly items = computed(() =>
    [...(this.loaded()?.catalog.items ?? [])].sort((a, b) => a.display_order - b.display_order),
  );

  protected readonly form = this.fb.group({
    date: localInput(),
    lab: 'Metro Diagnostics Laboratory',
    notes: '',
    rows: this.fb.array<RowGroup>([]),
  });

  protected get rows(): FormArray<RowGroup> {
    return this.form.controls.rows;
  }

  constructor() {
    // The two default rows are added once the catalog is here (their units come from it).
    effect(() => {
      if (this.loaded()) untracked(() => this.ensureRows());
    });
  }

  private ensureRows(): void {
    if (this.rows.length === 0 && this.loaded()) {
      this.rows.push(this.newRow('CREAT'));
      this.rows.push(this.newRow('EGFR'));
    }
  }

  protected item(code: string): CatalogItemDto | undefined {
    return this.loaded()?.catalog.items.find((i) => i.code === code);
  }

  protected newRow(code: string): RowGroup {
    const unit = this.item(code)?.canonical_unit ?? '';
    return this.fb.group({ test: code, value: '', unit });
  }

  protected units(code: string): string[] {
    return this.item(code)?.units.map((u) => u.unit) ?? [];
  }

  protected addRow(): void {
    if (this.rows.length >= 8) return;
    const used = this.rows.controls.map((r) => r.controls.test.value);
    this.rows.push(this.newRow(this.items().find((i) => !used.includes(i.code))?.code ?? 'K'));
  }

  protected removeRow(i: number): void {
    if (this.rows.length > 1) this.rows.removeAt(i);
  }

  protected onTestChange(row: RowGroup): void {
    row.controls.unit.setValue(this.item(row.controls.test.value)?.canonical_unit ?? '');
  }

  /** Live flag preview for one row (html `labPreview`, html:1043), from the server's catalog. */
  protected preview(row: RowGroup): { flag: Flag; converted: string | null } | null {
    const item = this.item(row.controls.test.value);
    const raw = row.controls.value.value;
    if (!item || raw.trim() === '') return null;
    const p = previewResult(item, raw, row.controls.unit.value);
    if (!p) return null;
    const unit = row.controls.unit.value;
    return {
      flag: p.flag,
      converted: unit !== item.canonical_unit ? `= ${p.canonical} ${item.canonical_unit}` : null,
    };
  }

  protected submit(): void {
    if (this.busy()) return;
    const loaded = this.loaded();
    if (!loaded) return;
    const v = this.form.getRawValue();
    const errors: Record<string, string> = {};
    const filled = v.rows.map((r, index) => ({ ...r, index })).filter((r) => r.value.trim() !== '');
    if (!v.date) errors['date'] = 'Collection date is required.';
    else if (new Date(v.date).getTime() > Date.now() + 60000)
      errors['date'] = 'Collection date cannot be in the future.';
    else if (new Date(v.date) < new Date(loaded.dob))
      errors['date'] = 'Collection date is before the patient was born.';
    const msgs: string[] = [];
    if (!filled.length) msgs.push('Enter at least one result value.');
    const seen = new Set<string>();
    for (const r of filled) {
      const it = this.item(r.test);
      const name = it?.name ?? r.test;
      const dec = parseDec(r.value);
      const p = it && dec ? previewResult(it, r.value, r.unit) : null;
      if (!dec) msgs.push(`${name}: enter a number of zero or more.`);
      else if (it && p && exceedsPlausibleMax(it, p.canonical))
        msgs.push(
          `${name}: ${r.value} ${r.unit} is outside the plausible range. Check the value and unit.`,
        );
      if (seen.has(r.test)) msgs.push(`${name} appears twice in this report.`);
      seen.add(r.test);
    }
    if (msgs.length) errors['rows'] = msgs.join(' ');
    this.rowErrors.set({});
    const n = Object.keys(errors).length;
    this.problem.set({
      ...NONE,
      errors,
      general: n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '',
    });
    if (n) return;

    this.busy.set(true);
    this.labs
      .addReport(this.patientId(), {
        collected_at: new Date(v.date).toISOString(),
        lab_name: v.lab.trim() || null,
        notes: v.notes.trim() || null,
        // the value goes as typed, a string, so no float ever touches it
        results: filled.map((r) => ({ test_code: r.test, value: r.value.trim(), unit: r.unit })),
      })
      .subscribe({
        next: (out) => {
          this.busy.set(false);
          this.modals.notifyChanged('labs', this.patientId());
          this.modals.close();
          const { n: count, abnormal } = out.summary;
          this.toast.show(
            `Lab report saved with ${count} result${count > 1 ? 's' : ''}${abnormal ? `. ${abnormal} abnormal.` : '. All within range.'}`,
          );
          void this.router.navigate(['/patients', this.patientId(), 'labs']);
        },
        error: (e: unknown) => {
          this.busy.set(false);
          this.fail(
            e,
            filled.map((r) => r.index),
          );
        },
      });
  }

  /** `results[1].unit` refers to the 2nd SUBMITTED row; map it back to the row on screen. */
  private fail(e: unknown, submitted: number[]): void {
    const p = toFormProblem(e, { collected_at: 'date', lab_name: 'lab', notes: 'notes' });
    const rowErrs: Record<number, string> = {};
    let unplaced = false;
    if (e instanceof ApiError && p.code === 'VALIDATION_ERROR') {
      for (const [field, issue] of e.fieldIssues()) {
        const m = /^results\[(\d+)]\.(\w+)/.exec(field);
        const rowIndex = m ? submitted[Number(m[1])] : undefined;
        if (rowIndex !== undefined) rowErrs[rowIndex] = issue;
        else if (!(field in { collected_at: 1, lab_name: 1, notes: 1 })) unplaced = true;
      }
    }
    this.rowErrors.set(rowErrs);
    const placedRows = Object.keys(rowErrs).length > 0;
    this.problem.set({
      ...p,
      general: placedRows && !unplaced ? 'Fix the highlighted results to continue.' : p.general,
    });
  }
}
