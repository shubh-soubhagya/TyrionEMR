// html:862-871
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DbService } from '../../../core/data/db.service';
import { sexLabel, typeLabel } from '../../../core/data/analysis';
import { fmtDate } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrIcon } from '../../../shared/ui/icon/icon';
import { EmrLabFlag } from '../../../shared/ui/lab-flag/lab-flag';
import { EmrKidneyPanel } from '../kidney-panel';

@Component({
  selector: 'emr-overview-tab',
  imports: [RouterLink, EmrIcon, EmrLabFlag, EmrKidneyPanel],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './overview-tab.html',
})
export class OverviewTab {
  private readonly db = inject(DbService);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly sexLabel = sexLabel;
  protected readonly typeLabel = typeLabel;

  protected readonly v = computed(() => {
    const id = this.id();
    const a = this.db.analysis(id);
    const encs = this.db.encounters(id);
    return {
      a,
      encs,
      primary: this.db.primary(id),
      activeConds: this.db.conds(id).filter((c) => c.status === 'active').length,
      activeMeds: this.db.meds(id).filter((m) => m.status === 'active').length,
      lastFinal: encs.find((e) => e.status === 'final'),
      highGaps: a.gaps.filter((g) => g.sev !== 'low').length,
    };
  });
}
