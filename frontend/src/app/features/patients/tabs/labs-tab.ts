// html:1006-1034. Everything comes from lab-svc: the latest tiles and CKD block (`/latest`), the trend charts and chips
// (`/trends?tests=CREAT,EGFR&from=`), and the paged result history (`/results?test=&flag=abnormal&page=&size=10`).
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
import { chartSeriesFromDto } from '@core/api/mappers/trend.mapper';
import { remoteSignal } from '@core/api/remote-signal';
import { fmtVal, LAB_TESTS, refText, type Flag, type TestCode } from '@core/clinical/lab-tests';
import { LabsApi } from '@core/data/labs.api';
import { DAY, fmtDate, isoDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrLineChart } from '@shared/ui/charts/line-chart';
import { EmrTrendChips } from '@shared/ui/charts/trend-chips';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { PatientStore } from '../patient-store';

/** The date-range select: how many days back `from` is set. */
const RANGE_DAYS: Record<string, number> = { '6m': 182, '1y': 365, '2y': 730 };
const PER = 10;

@Component({
  selector: 'emr-labs-tab',
  imports: [EmrIcon, EmrLabFlag, EmrLineChart, EmrTrendChips, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './labs-tab.html',
})
export class LabsTab {
  private readonly api = inject(LabsApi);
  protected readonly store = inject(PatientStore);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  // html `ui.labs`
  protected readonly range = signal('all');
  protected readonly test = signal<'ALL' | string>('ALL');
  protected readonly abn = signal(false);
  protected readonly page = signal(1);
  protected readonly bands = signal(true);

  protected readonly LAB = LAB_TESTS;
  protected readonly fmtDate = fmtDate;
  protected readonly refText = refText;
  protected readonly flag = (f: string): Flag => f as Flag;
  protected readonly fmt = (code: string, v: number): string =>
    code in LAB_TESTS ? fmtVal(code as TestCode, v) : String(v);

  /** `from` of the trends request: the range chips map to it. Empty means all results. */
  private readonly from = computed(() => {
    const days = RANGE_DAYS[this.range()];
    return days ? isoDate(Date.now() - days * DAY) : undefined;
  });

  protected readonly trends = remoteSignal(
    () => [this.id(), this.from()],
    () => this.api.trends(this.id(), ['CREAT', 'EGFR'], this.from()),
    () => false,
  );
  protected readonly history = remoteSignal(
    () => [this.id(), this.test(), this.abn(), this.page()],
    () =>
      this.api.results(this.id(), {
        ...(this.test() !== 'ALL' ? { test: this.test() } : {}),
        abnormalOnly: this.abn(),
        page: this.page(),
        size: PER,
      }),
    (p) => p.total === 0,
  );

  protected readonly latest = computed(() => {
    const l = this.store.latest();
    return l.state === 'ok' ? l.data : null;
  });
  protected readonly established = computed(() => {
    const d = this.store.detail();
    return d.state === 'ok' ? d.data.established_ckd_stage : null;
  });

  /** eGFR first, then creatinine, each with its reference band and (for eGFR) the server's stage thresholds. */
  protected readonly charts = computed(() => {
    const t = this.trends.state();
    if (t.state !== 'ok') return [];
    return (['EGFR', 'CREAT'] as const).flatMap((code) => {
      const s = t.data.series.find((x) => x.test_code === code);
      return s
        ? [
            {
              t: code as TestCode,
              s: chartSeriesFromDto(s),
              stage: code === 'EGFR' && this.bands(),
              bands: code === 'EGFR' ? (s.stage_bands ?? null) : null,
            },
          ]
        : [];
    });
  });

  private lastChange = 0;

  constructor() {
    // A saved lab report changes the trends and the history: reload just those.
    effect(() => {
      const c = this.modals.changed();
      if (c && c.kind === 'labs' && c.n !== this.lastChange && c.patientId === untracked(this.id)) {
        this.lastChange = c.n;
        untracked(() => {
          this.trends.reload();
          this.history.reload();
        });
      }
    });
  }

  protected select(event: Event, key: 'range' | 'test'): void {
    const value = (event.target as HTMLSelectElement).value;
    if (key === 'range') this.range.set(value);
    else this.test.set(value);
    this.page.set(1);
  }

  protected check(event: Event, key: 'abn' | 'bands'): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (key === 'abn') {
      this.abn.set(checked);
      this.page.set(1);
    } else {
      this.bands.set(checked);
    }
  }

  protected pages(total: number): number {
    return Math.max(1, Math.ceil(total / PER));
  }

  protected go(delta: number): void {
    this.page.update((p) => Math.max(1, p + delta));
  }
}
