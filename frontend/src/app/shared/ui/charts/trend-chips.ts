import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { TestCode, LAB_TESTS, TrendStats } from '../../../core/clinical/lab-tests';
import { signed } from '../../../core/format';
import { EmrIcon } from '../icon/icon';

/** Chips under a trend chart: direction, change, per-year slope, rapid decline (html:1269, `dirChip`). */
@Component({
  selector: 'emr-trend-chips',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (stats().n) {
      <div class="stat-row">
        @switch (stats().direction) {
          @case ('insufficient_data') {
            <span class="chip warn">Insufficient data (needs 3+ results)</span>
          }
          @case ('worsening') {
            <span class="chip danger"><emr-icon name="dn" [size]="13" />Worsening</span>
          }
          @case ('improving') {
            <span class="chip ok"><emr-icon name="up" [size]="13" />Improving</span>
          }
          @default {
            <span class="chip">Stable</span>
          }
        }
        @if (stats().n >= 2) {
          <span class="chip"
            >Change {{ signed(stats().abs, dec()) }} ({{ signed(stats().pct, 0) }}%)</span
          >
        }
        @if (stats().slope !== null) {
          <span class="chip"
            >{{ signed(stats().slope ?? 0, test() === 'EGFR' ? 1 : 2) }} per year</span
          >
        }
        @if (stats().rapid) {
          <span class="chip danger"><emr-icon name="alert" [size]="13" />Rapid decline</span>
        }
      </div>
    }
  `,
})
export class EmrTrendChips {
  readonly stats = input.required<TrendStats>();
  readonly test = input.required<TestCode>();
  protected readonly signed = signed;
  protected dec(): number {
    return LAB_TESTS[this.test()].dec;
  }
}
