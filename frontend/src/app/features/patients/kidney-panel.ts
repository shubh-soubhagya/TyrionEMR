// html:1267-1273 (kidneyPanel)
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { egfrLabel, fmtVal, LAB_TESTS, rangeFor, TestCode, uacrLabel } from '../../core/clinical/lab-tests';
import { Analysis } from '../../core/data/analysis';
import { fmtDate } from '../../core/format';
import { EmrLineChart } from '../../shared/ui/charts/line-chart';
import { EmrTrendChips } from '../../shared/ui/charts/trend-chips';
import { EmrCkdStageBadge } from '../../shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrIcon } from '../../shared/ui/icon/icon';

@Component({
  selector: 'emr-kidney-panel',
  imports: [RouterLink, EmrIcon, EmrLineChart, EmrTrendChips, EmrCkdStageBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './kidney-panel.html',
})
export class EmrKidneyPanel {
  readonly a = input.required<Analysis>();
  readonly patientId = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly fmtVal = fmtVal;
  protected readonly egfrLabel = egfrLabel;
  protected readonly uacrLabel = uacrLabel;
  protected readonly LAB = LAB_TESTS;

  protected readonly charts = computed(() =>
    (['EGFR', 'CREAT'] as TestCode[]).map((t) => {
      const a = this.a();
      const rg = rangeFor(t, a.p.sex);
      return { t, s: a.trends[t as 'EGFR' | 'CREAT'], low: rg.low, high: rg.high, stage: t === 'EGFR' };
    }),
  );
}
