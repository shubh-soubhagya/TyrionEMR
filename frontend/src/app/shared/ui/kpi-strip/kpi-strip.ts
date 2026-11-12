import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export interface KpiItem {
  readonly label: string;
  readonly value: number | string;
  /** Red number (html `.kpi.hot`) for things that need attention. */
  readonly hot?: boolean;
}

/** Row of headline numbers (html `.kpis`): 5 columns, 2 below 1100px. */
@Component({
  selector: 'emr-kpi-strip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (item of items(); track item.label) {
      <div class="kpi" [class.hot]="item.hot">
        <div class="n">{{ item.value }}</div>
        <div class="l">{{ item.label }}</div>
      </div>
    }
  `,
  styleUrl: './kpi-strip.scss',
})
export class EmrKpiStrip {
  readonly items = input.required<readonly KpiItem[]>();
}
