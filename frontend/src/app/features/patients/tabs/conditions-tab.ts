// html:874-891. The list comes from patient-svc; "one primary diagnosis" and resolve/reactivate are server rules.
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { toFormProblem, type FormProblem } from '@core/api/form-errors';
import { remoteSignal } from '@core/api/remote-signal';
import { egfrLabel } from '@core/clinical/lab-tests';
import { ChartApi } from '@core/data/chart.api';
import type { Condition } from '@core/data/models';
import { PatientsApi } from '@core/data/patients.api';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { ToastService } from '@shared/ui/toast/toast.service';
import { PatientStore } from '../patient-store';

@Component({
  selector: 'emr-conditions-tab',
  imports: [EmrIcon, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './conditions-tab.html',
})
export class ConditionsTab {
  private readonly chart = inject(ChartApi);
  private readonly patients = inject(PatientsApi);
  private readonly toast = inject(ToastService);
  protected readonly store = inject(PatientStore);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly egfrLabel = egfrLabel;
  protected readonly stages = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'];

  protected readonly conditions = remoteSignal<Condition[]>(
    this.id,
    () => this.chart.conditions(this.id()),
    () => false,
  );

  /** A failed write: shown above the table, with a Reload button after a version conflict. */
  protected readonly problem = signal<FormProblem | null>(null);

  protected readonly sections = computed(() => {
    const c = this.conditions.state();
    const rows = c.state === 'ok' ? c.data : [];
    return [
      { title: 'Nephrology diagnoses', rows: rows.filter((x) => x.category === 'nephrology') },
      { title: 'Comorbidities', rows: rows.filter((x) => x.category === 'comorbidity') },
    ];
  });

  protected readonly established = computed(() => {
    const d = this.store.detail();
    return d.state === 'ok' ? d.data.established_ckd_stage : null;
  });

  private lastChange = 0;

  constructor() {
    effect(() => {
      const c = this.modals.changed();
      if (
        c &&
        c.kind === 'conditions' &&
        c.n !== this.lastChange &&
        c.patientId === untracked(this.id)
      ) {
        this.lastChange = c.n;
        untracked(() => this.conditions.reload());
      }
    });
  }

  protected setStage(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    const version = this.store.version();
    if (version === null) return;
    this.problem.set(null);
    this.patients.setEstablishedStage(this.id(), value || null, version).subscribe({
      next: () => {
        this.store.reloadDetail();
        this.toast.show(
          value ? `Established CKD stage set to ${value}.` : 'Established CKD stage cleared.',
        );
      },
      error: (e: unknown) => {
        this.problem.set(toFormProblem(e));
        (event.target as HTMLSelectElement).value = this.established() ?? '';
      },
    });
  }

  protected setPrimary(condId: string): void {
    this.problem.set(null);
    this.chart.patchCondition(this.id(), condId, { is_primary: true }).subscribe({
      next: (r) => {
        this.conditions.reload();
        this.store.reloadDetail();
        this.toast.show(
          r.primaryCleared
            ? 'Primary diagnosis updated. Primary cleared on the previous one: only one primary is allowed.'
            : 'Primary diagnosis updated. Only one primary diagnosis is allowed per patient.',
        );
      },
      error: (e: unknown) => this.problem.set(toFormProblem(e)),
    });
  }

  protected toggle(c: Condition): void {
    this.problem.set(null);
    this.chart
      .patchCondition(this.id(), c.id, { status: c.status === 'active' ? 'resolved' : 'active' })
      .subscribe({
        next: () => {
          this.conditions.reload();
          this.store.reloadDetail();
          this.toast.show('Condition status updated.');
        },
        error: (e: unknown) => this.problem.set(toFormProblem(e)),
      });
  }

  protected reloadAfterConflict(): void {
    this.problem.set(null);
    this.store.reloadDetail();
    this.conditions.reload();
  }
}
