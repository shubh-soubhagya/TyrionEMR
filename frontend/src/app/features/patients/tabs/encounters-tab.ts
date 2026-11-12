// html:919-923
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { typeLabel } from '../../../core/data/analysis';
import { DbService } from '../../../core/data/db.service';
import { Encounter } from '../../../core/data/models';
import { fmtDate } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrIcon } from '../../../shared/ui/icon/icon';

@Component({
  selector: 'emr-encounters-tab',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './encounters-tab.html',
})
export class EncountersTab {
  private readonly db = inject(DbService);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly typeLabel = typeLabel;
  protected readonly encs = computed(() => this.db.encounters(this.id()));

  protected short(text: string): string {
    return text.length > 90 ? text.slice(0, 90) + '…' : text;
  }

  protected open(e: Encounter): void {
    if (e.status === 'draft') {
      this.modals.open({ kind: 'encounter-form', patientId: this.id(), encounterId: e.id });
    } else {
      this.modals.open({
        kind: 'encounter-view',
        encounterId: e.id,
        sub: `${typeLabel(e.type)}, Final`,
      });
    }
  }
}
