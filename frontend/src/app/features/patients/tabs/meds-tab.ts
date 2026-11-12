// html:894-915
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { DbService } from '../../../core/data/db.service';
import { cap, fmtDate } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrIcon } from '../../../shared/ui/icon/icon';
import { ToastService } from '../../../shared/ui/toast/toast.service';

@Component({
  selector: 'emr-meds-tab',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meds-tab.html',
})
export class MedsTab {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly cap = cap;
  /** "Show discontinued" (html `ui.medsAll`), kept in the component. */
  protected readonly showAll = signal(false);

  protected readonly v = computed(() => {
    const id = this.id();
    return {
      p: this.db.patient(id),
      meds: this.db.meds(id).filter((m) => this.showAll() || m.status === 'active'),
      allergies: this.db.allergies(id),
    };
  });

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
    this.db.stopMedication(medId);
    this.toast.show('Medication discontinued.');
  }

  protected async removeAllergy(allergyId: string): Promise<void> {
    const ok = await this.modals.confirm({
      title: 'Remove allergy',
      message: 'Remove this allergy from the chart? If it is the last one, allergy status returns to unknown.',
      ok: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.db.removeAllergy(this.id(), allergyId);
    this.toast.show('Allergy removed.');
  }

  protected markNka(): void {
    this.db.markNoKnownAllergies(this.id());
    this.toast.show('Marked as no known allergies.');
  }
}
