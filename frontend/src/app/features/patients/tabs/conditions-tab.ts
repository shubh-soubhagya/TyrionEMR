// html:874-891
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { egfrLabel } from '../../../core/clinical/lab-tests';
import { DbService } from '../../../core/data/db.service';
import { CkdStage } from '../../../core/data/models';
import { fmtDate } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrIcon } from '../../../shared/ui/icon/icon';
import { ToastService } from '../../../shared/ui/toast/toast.service';

@Component({
  selector: 'emr-conditions-tab',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './conditions-tab.html',
})
export class ConditionsTab {
  private readonly db = inject(DbService);
  private readonly toast = inject(ToastService);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly egfrLabel = egfrLabel;
  protected readonly stages = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'];

  protected readonly v = computed(() => {
    const id = this.id();
    const conds = this.db.conds(id);
    return {
      a: this.db.analysis(id),
      sections: [
        { title: 'Nephrology diagnoses', rows: conds.filter((c) => c.category === 'nephrology') },
        { title: 'Comorbidities', rows: conds.filter((c) => c.category === 'comorbidity') },
      ],
    };
  });

  protected setStage(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.db.setCkdStage(this.id(), (value || null) as CkdStage | null);
    this.toast.show(value ? `Established CKD stage set to ${value}.` : 'Established CKD stage cleared.');
  }

  protected setPrimary(condId: string): void {
    this.db.setPrimary(this.id(), condId);
    this.toast.show('Primary diagnosis updated. Only one primary diagnosis is allowed per patient.');
  }

  protected toggle(condId: string): void {
    this.db.toggleCondition(condId);
    this.toast.show('Condition status updated.');
  }
}
