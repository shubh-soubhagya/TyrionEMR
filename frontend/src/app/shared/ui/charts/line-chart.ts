import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import {
  flagColor,
  fmtVal,
  LAB_TESTS,
  TestCode,
  TrendPoint,
} from '../../../core/clinical/lab-tests';
import { DAY, fmtDate } from '../../../core/format';
import { FLAG_VIEWS } from '../lab-flag/lab-flag';
import { EmrTip } from '../tooltip/tooltip';

const niceStep = (r: number): number => {
  const p = Math.pow(10, Math.floor(Math.log10(r)));
  const f = r / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
};

const STAGE_BANDS: readonly (readonly [number, number, string])[] = [
  [90, 100, 'G1'],
  [60, 90, 'G2'],
  [45, 60, 'G3a'],
  [30, 45, 'G3b'],
  [15, 30, 'G4'],
  [0, 15, 'G5'],
];

/** [lower, upper, code] from the server's `{code, lower}` list (descending thresholds; the top band ends at 100). */
function serverBands(
  b: readonly { readonly code: string; readonly lower: number }[] | null,
): readonly (readonly [number, number, string])[] | null {
  if (!b || b.length === 0) return null;
  const sorted = [...b].sort((x, y) => y.lower - x.lower);
  return sorted.map(
    (x, i) => [x.lower, i === 0 ? 100 : (sorted[i - 1]?.lower ?? 100), x.code] as const,
  );
}

/**
 * Hand-built SVG line chart, ported from the HTML's `lineChart()` (html:983-1004) so the look is
 * identical: grid, reference band, optional KDIGO stage lines, series line, flag-coloured points.
 */
@Component({
  selector: 'emr-line-chart',
  imports: [EmrTip],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './line-chart.html',
})
export class EmrLineChart {
  readonly pts = input.required<readonly TrendPoint[]>();
  readonly test = input.required<TestCode>();
  readonly low = input<number | null>(null);
  readonly high = input<number | null>(null);
  readonly stage = input(false);
  /** eGFR stage thresholds from lab-svc (`stage_bands`); the built-in KDIGO list is only the fallback. */
  readonly bands = input<readonly { readonly code: string; readonly lower: number }[] | null>(null);

  protected readonly name = computed(() => LAB_TESTS[this.test()].name);

  protected readonly g = computed(() => {
    const pts = this.pts();
    if (!pts.length) return null;
    const test = this.test();
    const unit = LAB_TESTS[test].canon;
    const dec = LAB_TESTS[test].dec;
    const low = this.low();
    const high = this.high();
    const stage = this.stage();
    const stageBands = serverBands(this.bands()) ?? STAGE_BANDS;
    const W = 640;
    const H = 270;
    const m = { l: 48, r: stage ? 64 : 22, t: 16, b: 32 };
    let tmin = (pts[0] as TrendPoint).t;
    let tmax = (pts[pts.length - 1] as TrendPoint).t;
    if (tmax - tmin < 30 * DAY) {
      tmin -= 15 * DAY;
      tmax += 15 * DAY;
    }
    const vals = pts.map((p) => p.v);
    let ymin = Math.min(...vals, low == null ? Infinity : low);
    let ymax = Math.max(...vals, high == null ? -Infinity : high);
    if (stage) {
      ymin = 0;
      ymax = Math.max(ymax, 100);
    } else {
      const pd = (ymax - ymin || 1) * 0.18;
      ymin = Math.max(0, ymin - pd);
      ymax += pd;
    }
    const step = niceStep((ymax - ymin) / 4);
    const ticks: number[] = [];
    for (let t = Math.floor(ymin / step) * step; t <= ymax + step * 0.01; t += step) {
      ticks.push(Math.round(t * 1000) / 1000);
    }
    ymin = ticks[0] as number;
    ymax = ticks[ticks.length - 1] as number;
    const sx = (t: number) => m.l + ((t - tmin) / (tmax - tmin)) * (W - m.l - m.r);
    const sy = (v: number) => H - m.b - ((v - ymin) / (ymax - ymin)) * (H - m.t - m.b);
    const yTop = sy(Math.min(high == null ? ymax : high, ymax));
    const yBot = sy(Math.max(low == null ? ymin : low, ymin));

    const last = pts[pts.length - 1] as TrendPoint;
    return {
      W,
      H,
      m,
      unit,
      aria: `${this.name()} over time. ${pts.length} results. Latest ${fmtVal(test, last.v)} ${unit}.`,
      ticks: ticks.map((t) => ({ y: sy(t), label: String(+t.toFixed(dec + 1)) })),
      xlabels: [0, 1, 2, 3, 4].map((i) => {
        const t = tmin + ((tmax - tmin) * i) / 4;
        return {
          x: sx(t),
          label: new Date(t).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' }),
        };
      }),
      band:
        high != null || low != null ? { y: Math.min(yTop, yBot), h: Math.abs(yBot - yTop) } : null,
      stages: stage
        ? stageBands.map((b) => {
            const c = (Math.max(b[0], ymin) + Math.min(b[1], ymax)) / 2;
            return { line: b[0] > 0 && b[0] < ymax ? sy(b[0]) : null, ty: sy(c) + 4, label: b[2] };
          })
        : [],
      path: pts
        .map((p, i) => (i ? 'L' : 'M') + sx(p.t).toFixed(1) + ' ' + sy(p.v).toFixed(1))
        .join(' '),
      points: pts.map((p, i) => ({
        x: sx(p.t),
        y: sy(p.v),
        fill: flagColor(p.flag),
        tip: [
          `${fmtVal(test, p.v)} ${unit}`,
          p.flag ? (FLAG_VIEWS[p.flag]?.text ?? '') : '',
          fmtDate(p.t),
        ],
        label: i === pts.length - 1 ? fmtVal(test, p.v) : null,
      })),
    };
  });
}
