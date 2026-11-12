// html:1036-1067
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormArray, FormBuilder, FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  flagFor,
  fmtVal,
  LAB_TESTS,
  rangeFor,
  TEST_ORDER,
  TestCode,
  toCanon,
} from '../../core/clinical/lab-tests';
import { DbService } from '../../core/data/db.service';
import { fmtDate, localInput } from '../../core/format';
import { EmrLabFlag } from '../../shared/ui/lab-flag/lab-flag';
import { EmrIcon } from '../../shared/ui/icon/icon';
import { EmrModalShell } from '../../shared/ui/modal-shell/modal-shell';
import { ToastService } from '../../shared/ui/toast/toast.service';
import { ModalService } from '../../core/ui/modal.service';

type RowGroup = FormGroup<{ test: FormControl<TestCode>; value: FormControl<string>; unit: FormControl<string> }>;

@Component({
  selector: 'emr-lab-modal',
  imports: [ReactiveFormsModule, EmrModalShell, EmrIcon, EmrLabFlag],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './lab-modal.html',
})
export class LabModal {
  private readonly db = inject(DbService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly fb = inject(FormBuilder).nonNullable;

  readonly patientId = input.required<string>();
  readonly closed = output<void>();

  protected readonly LAB = LAB_TESTS;
  protected readonly ORDER = TEST_ORDER;
  protected readonly nowLocal = localInput();
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly general = signal('');
  protected readonly patient = computed(() => this.db.patient(this.patientId()));

  protected readonly form = this.fb.group({
    date: localInput(),
    lab: 'Metro Diagnostics Laboratory',
    notes: '',
    rows: this.fb.array<RowGroup>([]),
  });

  constructor() {
    this.rows.push(this.newRow('CREAT'));
    this.rows.push(this.newRow('EGFR'));
  }

  protected get rows(): FormArray<RowGroup> {
    return this.form.controls.rows;
  }

  protected newRow(test: TestCode): RowGroup {
    return this.fb.group({ test, value: '', unit: LAB_TESTS[test].canon });
  }

  protected units(test: TestCode): string[] {
    return Object.keys(LAB_TESTS[test].units);
  }

  protected addRow(): void {
    const used = this.rows.controls.map((r) => r.controls.test.value);
    this.rows.push(this.newRow(TEST_ORDER.find((t) => !used.includes(t)) ?? 'K'));
  }

  protected removeRow(i: number): void {
    if (this.rows.length > 1) this.rows.removeAt(i);
  }

  protected onTestChange(row: RowGroup): void {
    row.controls.unit.setValue(LAB_TESTS[row.controls.test.value].canon);
  }

  /** Live flag preview for one row (html `labPreview`, html:1043). */
  protected preview(row: RowGroup): { flag: ReturnType<typeof flagFor>; converted: string | null } | null {
    const raw = row.controls.value.value;
    if (raw === '' || isNaN(+raw)) return null;
    const t = row.controls.test.value;
    const u = row.controls.unit.value;
    const c = toCanon(t, +raw, u);
    return {
      flag: flagFor(c, rangeFor(t, this.patient().sex)),
      converted: u !== LAB_TESTS[t].canon ? `= ${fmtVal(t, c)} ${LAB_TESTS[t].canon}` : null,
    };
  }

  protected submit(): void {
    const v = this.form.getRawValue();
    const p = this.patient();
    const errs: Record<string, string> = {};
    const rows = v.rows.filter((r) => r.value !== '');
    if (!v.date) errs['date'] = 'Collection date is required.';
    else if (new Date(v.date).getTime() > Date.now() + 60000) errs['date'] = 'Collection date cannot be in the future.';
    else if (new Date(v.date) < new Date(p.dob)) errs['date'] = 'Collection date is before the patient was born.';
    const msgs: string[] = [];
    if (!rows.length) msgs.push('Enter at least one result value.');
    const seen: Record<string, boolean> = {};
    rows.forEach((r) => {
      const T = LAB_TESTS[r.test];
      const n = +r.value;
      if (isNaN(n) || n < 0) msgs.push(`${T.name}: enter a number of zero or more.`);
      else if (toCanon(r.test, n, r.unit) > T.max)
        msgs.push(`${T.name}: ${r.value} ${r.unit} is outside the plausible range. Check the value and unit.`);
      if (seen[r.test]) msgs.push(`${T.name} appears twice in this report.`);
      seen[r.test] = true;
    });
    if (msgs.length) errs['rows'] = msgs.join(' ');
    this.errors.set(errs);
    const n = Object.keys(errs).length;
    this.general.set(n ? `Fix ${n} field${n > 1 ? 's' : ''} to continue.` : '');
    if (n) return;
    const out = this.db.addLabReport(this.patientId(), {
      collectedAt: v.date,
      labName: v.lab,
      notes: v.notes,
      rows: rows.map((r) => ({ test: r.test, value: +r.value, unit: r.unit })),
    });
    this.modals.close();
    this.toast.show(
      `Lab report saved with ${out.n} result${out.n > 1 ? 's' : ''}${out.abn ? `. ${out.abn} abnormal.` : '. All within range.'}`,
    );
    void this.router.navigate(['/patients', this.patientId(), 'labs']);
  }

  protected fmtDate = fmtDate;
}
