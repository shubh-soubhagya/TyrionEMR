// html:894-915. Medications and allergies come from patient-svc; "no known allergies" is a PATCH on the patient with
// the version the page holds (409 ALLERGIES_PRESENT if allergies exist, 409 VERSION_CONFLICT if someone else saved).
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
import { ChartApi, type AllergyList } from '@core/data/chart.api';
import type { Med } from '@core/data/models';
import { cap, fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { ToastService } from '@shared/ui/toast/toast.service';
import { PatientStore } from '../patient-store';

@Component({
  selector: 'emr-meds-tab',
  imports: [EmrIcon, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meds-tab.html',
})
export class MedsTab {
  private readonly api = inject(ChartApi);
  private readonly toast = inject(ToastService);
  protected readonly store = inject(PatientStore);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly cap = cap;
  /** "Show discontinued": status=all instead of status=active. */
  protected readonly showAll = signal(false);
  protected readonly problem = signal<FormProblem | null>(null);

  protected readonly meds = remoteSignal<Med[]>(
    () => [this.id(), this.showAll()],
    () => this.api.medications(this.id(), this.showAll() ? 'all' : 'active'),
    () => false,
  );
  protected readonly allergies = remoteSignal<AllergyList>(
    this.id,
    () => this.api.allergies(this.id()),
    () => false,
  );

  protected readonly status = computed(() => {
    const a = this.allergies.state();
    return a.state === 'ok' ? a.data.status : null;
  });

  private lastChange = 0;

  constructor() {
    effect(() => {
      const c = this.modals.changed();
      if (!c || c.n === this.lastChange || c.patientId !== untracked(this.id)) return;
      this.lastChange = c.n;
      untracked(() => {
        if (c.kind === 'medications') this.meds.reload();
        if (c.kind === 'allergies') this.allergies.reload();
      });
    });
  }

  protected toggleAll(event: Event): void {
    this.showAll.set((event.target as HTMLInputElement).checked);
  }

  protected async stop(medId: string): Promise<void> {
    const ok = await this.modals.confirm({
      title: 'Discontinue medication',
      message: 'This sets the end date to today and moves it to discontinued. The record is kept.',
      ok: 'Discontinue',
    });
    if (!ok) return;
    this.problem.set(null);
    this.api.discontinueMedication(this.id(), medId).subscribe({
      next: () => {
        this.meds.reload();
        this.store.reloadDetail();
        this.toast.show('Medication discontinued.');
      },
      error: (e: unknown) => this.problem.set(toFormProblem(e)),
    });
  }

  protected async removeAllergy(allergyId: string): Promise<void> {
    const ok = await this.modals.confirm({
      title: 'Remove allergy',
      message:
        'Remove this allergy from the chart? If it is the last one, allergy status returns to unknown.',
      ok: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.problem.set(null);
    this.api.removeAllergy(this.id(), allergyId).subscribe({
      next: (r) => {
        this.store.setVersion(r.patientVersion);
        this.allergies.reload();
        this.store.reloadDetail();
        this.toast.show('Allergy removed.');
      },
      error: (e: unknown) => this.problem.set(toFormProblem(e)),
    });
  }

  protected markNka(): void {
    const version = this.store.version();
    if (version === null) return;
    this.problem.set(null);
    this.api.markNoKnownAllergies(this.id(), version).subscribe({
      next: () => {
        this.allergies.reload();
        this.store.reloadDetail();
        this.toast.show('Marked as no known allergies.');
      },
      error: (e: unknown) => this.problem.set(toFormProblem(e)),
    });
  }

  protected reloadAfterConflict(): void {
    this.problem.set(null);
    this.store.reloadDetail();
    this.allergies.reload();
    this.meds.reload();
  }
}
