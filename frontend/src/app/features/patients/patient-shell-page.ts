// html:837-858
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { egfrLabel } from '../../core/clinical/lab-tests';
import { Analysis, fullName, sexLabel } from '../../core/data/analysis';
import { DbService } from '../../core/data/db.service';
import { fmtDate } from '../../core/format';
import { ModalService } from '../../core/ui/modal.service';
import { EmrAvatar } from '../../shared/ui/avatar/avatar';
import { EmrCkdStageBadge } from '../../shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrIcon } from '../../shared/ui/icon/icon';
import { IconName } from '../../shared/ui/icon/icons';

const TABS: readonly { key: string; label: string; icon: IconName }[] = [
  { key: 'overview', label: 'Overview', icon: 'user' },
  { key: 'conditions', label: 'Conditions', icon: 'clip' },
  { key: 'meds', label: 'Medications and allergies', icon: 'pill' },
  { key: 'encounters', label: 'Encounters', icon: 'file' },
  { key: 'labs', label: 'Labs', icon: 'flask' },
  { key: 'ai', label: 'AI summary', icon: 'spark' },
];

@Component({
  selector: 'emr-patient-shell-page',
  imports: [RouterLink, RouterLinkActive, RouterOutlet, EmrIcon, EmrAvatar, EmrCkdStageBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-shell-page.html',
})
export class PatientShellPage {
  private readonly db = inject(DbService);
  protected readonly modals = inject(ModalService);

  /** `:id` route param, bound by withComponentInputBinding. */
  readonly id = input.required<string>();

  protected readonly tabs = TABS;
  protected readonly fullName = fullName;
  protected readonly sexLabel = sexLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly egfrLabel = egfrLabel;

  protected readonly a = computed<Analysis | null>(() => {
    try {
      return this.db.analysis(this.id());
    } catch {
      return null;
    }
  });

  protected readonly counts = computed(() => {
    const id = this.id();
    const a = this.a();
    if (!a) return {};
    return {
      conditions: this.db.conds(id).length,
      meds: this.db.meds(id).filter((m) => m.status === 'active').length,
      encounters: this.db.encounters(id).length,
      labs: a.res.length,
    } as Record<string, number>;
  });

  protected readonly allergyNames = computed(() =>
    this.db
      .allergies(this.id())
      .map((x) => x.allergen)
      .join(', '),
  );
}
