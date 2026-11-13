// html:1006-1034
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import {
  egfrLabel,
  fmtVal,
  LAB_TESTS,
  rangeFor,
  refText,
  TEST_ORDER,
  TestCode,
  trendStats,
  uacrLabel,
} from '../../../core/clinical/lab-tests';
import { DbService } from '../../../core/data/db.service';
import { DAY, fmtDate } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrLineChart } from '../../../shared/ui/charts/line-chart';
import { EmrTrendChips } from '../../../shared/ui/charts/trend-chips';
import { EmrIcon } from '../../../shared/ui/icon/icon';
import { EmrLabFlag } from '../../../shared/ui/lab-flag/lab-flag';

const RANGE_DAYS: Record<string, number> = { '6m': 182, '1y': 365, '2y': 730 };
const PER = 10;

@Component({
  selector: 'emr-labs-tab',
  imports: [EmrIcon, EmrLabFlag, EmrLineChart, EmrTrendChips],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './labs-tab.html',
})
export class LabsTab {
  private readonly db = inject(DbService);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  // html `ui.labs`
  protected readonly range = signal('all');
  protected readonly test = signal<'ALL' | TestCode>('ALL');
  protected readonly abn = signal(false);
  protected readonly page = signal(1);
  protected readonly bands = signal(true);

  protected readonly LAB = LAB_TESTS;
  protected readonly ORDER = TEST_ORDER;
  protected readonly fmtDate = fmtDate;
  protected readonly fmtVal = fmtVal;
  protected readonly refText = refText;
  protected readonly egfrLabel = egfrLabel;
  protected readonly uacrLabel = uacrLabel;

  protected readonly v = computed(() => {
    const id = this.id();
    const a = this.db.analysis(id);
    const days = RANGE_DAYS[this.range()];
    const cut = days ? Date.now() - days * DAY : 0;
    const all = this.db.results(id).filter((r) => new Date(r.collectedAt).getTime() >= cut);

    const chart = (t: 'EGFR' | 'CREAT', stage: boolean) => {
      const pts = this.db
        .results(id)
        .filter((r) => r.test === t && new Date(r.collectedAt).getTime() >= cut)
        .sort((x, y) => new Date(x.collectedAt).getTime() - new Date(y.collectedAt).getTime())
        .map((r) => ({ t: new Date(r.collectedAt).getTime(), v: r.value, flag: r.flag }));
      const rg = rangeFor(t, a.p.sex);
      return { t, s: trendStats(pts, t), rg, stage };
    };

    let rows = all.filter(
      (r) =>
        (this.test() === 'ALL' || r.test === this.test()) && (!this.abn() || r.flag !== 'normal'),
    );
    const pages = Math.max(1, Math.ceil(rows.length / PER));
    const page = Math.min(this.page(), pages);
    rows = rows.slice((page - 1) * PER, page * PER);
    const total = all.filter(
      (r) =>
        (this.test() === 'ALL' || r.test === this.test()) && (!this.abn() || r.flag !== 'normal'),
    ).length;
    return {
      a,
      charts: [chart('EGFR', this.bands()), chart('CREAT', false)],
      rows,
      total,
      pages,
      page,
      reports: new Map(this.db.raw().labReports.map((r) => [r.id, r.labName])),
    };
  });

  protected select(event: Event, key: 'range' | 'test'): void {
    const value = (event.target as HTMLSelectElement).value;
    if (key === 'range') this.range.set(value);
    else this.test.set(value as 'ALL' | TestCode);
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

  protected go(delta: number): void {
    this.page.set(this.v().page + delta);
  }
}
