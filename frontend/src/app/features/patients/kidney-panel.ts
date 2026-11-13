// html:1267-1273 (kidneyPanel). Charts and chips come from lab-svc `GET /labs/patients/{id}/trends?tests=CREAT,EGFR`;
// the CKD strip from `GET /labs/patients/{id}/latest` (held by PatientStore).
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import type { TrendsDto } from '@core/api/dto/lab.dto';
import { chartSeriesFromDto } from '@core/api/mappers/trend.mapper';
import { LOADING, toRemote, type Remote } from '@core/api/remote';
import { fmtVal, LAB_TESTS, type TestCode } from '@core/clinical/lab-tests';
import { LabsApi } from '@core/data/labs.api';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrLineChart } from '@shared/ui/charts/line-chart';
import { EmrTrendChips } from '@shared/ui/charts/trend-chips';
import { EmrCkdStageBadge } from '@shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { Subscription } from 'rxjs';
import { PatientStore } from './patient-store';

@Component({
  selector: 'emr-kidney-panel',
  imports: [RouterLink, EmrIcon, EmrLineChart, EmrTrendChips, EmrCkdStageBadge, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './kidney-panel.html',
})
export class EmrKidneyPanel {
  private readonly labs = inject(LabsApi);
  private readonly modals = inject(ModalService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly store = inject(PatientStore);

  readonly patientId = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly fmtVal = fmtVal;
  protected readonly LAB = LAB_TESTS;

  protected readonly trends = signal<Remote<TrendsDto>>(LOADING);
  private sub: Subscription | null = null;
  private lastChange = 0;

  protected readonly latest = computed(() => {
    const l = this.store.latest();
    return l.state === 'ok' ? l.data : null;
  });
  protected readonly established = computed(() => {
    const d = this.store.detail();
    return d.state === 'ok'
      ? (d.data.established_ckd_stage as 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5' | null)
      : null;
  });

  /** CREAT and EGFR series in the order the HTML shows them (eGFR first). */
  protected readonly charts = computed(() => {
    const t = this.trends();
    if (t.state !== 'ok') return [];
    return (['EGFR', 'CREAT'] as const).flatMap((code) => {
      const s = t.data.series.find((x) => x.test_code === code);
      return s ? [{ t: code as TestCode, s: chartSeriesFromDto(s), stage: code === 'EGFR' }] : [];
    });
  });

  constructor() {
    effect(() => {
      const id = this.patientId();
      untracked(() => this.load(id));
    });
    // A new lab report changes the trends: reload just this panel.
    effect(() => {
      const c = this.modals.changed();
      if (
        c &&
        c.kind === 'labs' &&
        c.n !== this.lastChange &&
        c.patientId === untracked(this.patientId)
      ) {
        this.lastChange = c.n;
        untracked(() => this.load(c.patientId));
      }
    });
    this.destroyRef.onDestroy(() => this.sub?.unsubscribe());
  }

  protected reload(): void {
    this.load(this.patientId());
  }

  private load(id: string): void {
    this.sub?.unsubscribe();
    this.sub = toRemote(this.labs.trends(id, ['CREAT', 'EGFR']), () => false).subscribe((s) =>
      this.trends.set(s),
    );
  }
}
