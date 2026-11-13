// html:862-871. Demographics and counts come from the patient header (PatientStore), the kidney panel from lab-svc,
// the gap alert from ai-svc and the recent encounters from patient-svc. Each panel loads and fails on its own.
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  untracked,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import type { GapsDto } from '@core/api/dto/ai.dto';
import { remoteSignal } from '@core/api/remote-signal';
import type { Flag } from '@core/clinical/lab-tests';
import { EncountersApi } from '@core/data/encounters.api';
import { InsightsApi } from '@core/data/insights.api';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { sexLabel, typeLabel } from '@shared/utils/labels';
import { EmrKidneyPanel } from '../kidney-panel';
import { PatientStore } from '../patient-store';

@Component({
  selector: 'emr-overview-tab',
  imports: [RouterLink, EmrIcon, EmrLabFlag, EmrKidneyPanel, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './overview-tab.html',
})
export class OverviewTab {
  private readonly insights = inject(InsightsApi);
  private readonly encountersApi = inject(EncountersApi);
  protected readonly store = inject(PatientStore);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly sexLabel = sexLabel;
  protected readonly typeLabel = typeLabel;
  protected readonly flag = (f: string): Flag => f as Flag;

  protected readonly gaps = remoteSignal<GapsDto>(
    this.id,
    () => this.insights.gaps(this.id()),
    () => false,
  );
  protected readonly recent = remoteSignal(
    this.id,
    () => this.encountersApi.list(this.id(), 1, 3),
    (p) => p.items.length === 0,
  );

  /** Findings worth a banner: everything except low severity (the HTML's rule). */
  protected readonly highGaps = computed(() => {
    const g = this.gaps.state();
    return g.state === 'ok' ? g.data.findings.filter((f) => f.severity !== 'low').length : 0;
  });

  protected readonly latestEgfr = computed(() => {
    const l = this.store.latest();
    return l.state === 'ok'
      ? (l.data.tests.find((t) => t.test_code === 'EGFR')?.result ?? null)
      : null;
  });

  private lastChange = 0;

  constructor() {
    // A saved encounter changes the recent list and the gap findings; a lab report changes the gaps.
    effect(() => {
      const c = this.modals.changed();
      if (!c || c.n === this.lastChange || c.patientId !== untracked(this.id)) return;
      this.lastChange = c.n;
      untracked(() => {
        if (c.kind === 'encounters') this.recent.reload();
        if (c.kind !== 'patient') this.gaps.reload();
      });
    });
  }
}
