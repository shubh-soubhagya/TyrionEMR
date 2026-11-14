import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  untracked,
  viewChild,
} from '@angular/core';
import {
  Chart,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  type ChartEvent,
  type Plugin,
} from 'chart.js';
import {
  flagColor,
  fmtVal,
  LAB_TESTS,
  TestCode,
  TrendPoint,
} from '../../../core/clinical/lab-tests';
import { bandRanges, DEFAULT_STAGE_BANDS, trendAxes, type StageBand } from '../../utils/chart-axes';
import { pointTip } from '../../utils/chart-tips';
import { TooltipService } from '../tooltip/tooltip';

// Only what a line chart needs, so the bundle stays small (tree-shaken registration).
Chart.register(LineController, LineElement, PointElement, LinearScale);

interface Xy {
  x: number;
  y: number;
}

/**
 * Lab trend line chart, drawn with Chart.js (the assignment asks for a charting library). The look follows the HTML
 * hand-drawn `lineChart()` (html:983-1004): grid, reference band, optional KDIGO stage lines, teal series line,
 * flag-coloured points with a white ring, a hover crosshair and a label on the last value. The band, stage lines,
 * crosshair, unit and last-value label are one small Chart.js plugin; the tooltip text comes from `chart-tips.ts` and
 * is shown by the shared tooltip component, so it looks and behaves like every other tooltip.
 */
@Component({
  selector: 'emr-line-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './line-chart.html',
  styles: `
    .lc {
      position: relative;
      width: 100%;
    }
  `,
})
export class EmrLineChart {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly tooltip = inject(TooltipService);
  private readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('cv');
  private chart: Chart<'line', Xy[]> | null = null;

  readonly pts = input.required<readonly TrendPoint[]>();
  readonly test = input.required<TestCode>();
  readonly low = input<number | null>(null);
  readonly high = input<number | null>(null);
  readonly stage = input(false);
  /** eGFR stage thresholds from lab-svc (`stage_bands`); the built-in KDIGO list is only the fallback. */
  readonly bands = input<readonly StageBand[] | null>(null);

  protected readonly name = computed(() => LAB_TESTS[this.test()].name);
  protected readonly hasData = computed(() => this.pts().length > 0);
  protected readonly aria = computed(() => {
    const pts = this.pts();
    const last = pts[pts.length - 1];
    if (!last) return '';
    const t = this.test();
    return `${this.name()} over time. ${pts.length} results. Latest ${fmtVal(t, last.v)} ${LAB_TESTS[t].canon}.`;
  });

  constructor() {
    effect(() => {
      const cv = this.canvas()?.nativeElement;
      const pts = this.pts();
      const test = this.test();
      const low = this.low();
      const high = this.high();
      const stage = this.stage();
      const bands = this.bands();
      untracked(() => {
        this.chart?.destroy();
        this.chart = null;
        // no 2D context (a test DOM without a canvas): skip drawing, the aria label still describes the series
        if (cv && pts.length && cv.getContext('2d')) {
          this.chart = this.build(cv, pts, test, low, high, stage, bands);
        }
      });
    });
    inject(DestroyRef).onDestroy(() => {
      this.chart?.destroy();
      this.tooltip.hide();
    });
  }

  private build(
    cv: HTMLCanvasElement,
    pts: readonly TrendPoint[],
    test: TestCode,
    low: number | null,
    high: number | null,
    stage: boolean,
    bands: readonly StageBand[] | null,
  ): Chart<'line', Xy[]> {
    // canvas cannot read CSS variables, so resolve the few tokens it needs once per chart
    const css = getComputedStyle(this.host.nativeElement);
    const font = css.getPropertyValue('--font').trim() || 'sans-serif';
    const teal = css.getPropertyValue('--teal').trim() || '#0e6b75';
    const inkMuted = css.getPropertyValue('--ink-3').trim() || '#6b7f8c';
    const unit = LAB_TESTS[test].canon;
    const dec = LAB_TESTS[test].dec;
    const ax = trendAxes(
      pts.map((p) => p.t),
      pts.map((p) => p.v),
      low,
      high,
      stage,
    );
    const ranges = bandRanges(bands) ?? DEFAULT_STAGE_BANDS;
    const last = pts[pts.length - 1] as TrendPoint;
    const tip = this.tooltip;

    const decor: Plugin<'line'> = {
      id: 'emrDecor',
      beforeDatasetsDraw: (chart) => {
        const { ctx, chartArea: a, scales } = chart;
        const y = scales['y'];
        if (!y) return;
        ctx.save();
        if (high != null || low != null) {
          const top = y.getPixelForValue(Math.min(high ?? ax.ymax, ax.ymax));
          const bot = y.getPixelForValue(Math.max(low ?? ax.ymin, ax.ymin));
          ctx.globalAlpha = 0.75;
          ctx.fillStyle = '#e5f5ee'; // html .band
          ctx.fillRect(a.left, Math.min(top, bot), a.right - a.left, Math.abs(bot - top));
          ctx.globalAlpha = 1;
        }
        if (stage) {
          ctx.font = `10.5px ${font}`;
          ctx.fillStyle = inkMuted;
          ctx.textAlign = 'left';
          ctx.strokeStyle = '#b8c6cd'; // html .stage-l, token --color-chart-stage-line
          ctx.setLineDash([3, 4]);
          for (const [lower, upper, code] of ranges) {
            if (lower > 0 && lower < ax.ymax) {
              const py = y.getPixelForValue(lower);
              ctx.beginPath();
              ctx.moveTo(a.left, py);
              ctx.lineTo(a.right, py);
              ctx.stroke();
            }
            const centre = (Math.max(lower, ax.ymin) + Math.min(upper, ax.ymax)) / 2;
            ctx.fillText(code, a.right + 6, y.getPixelForValue(centre) + 4);
          }
          ctx.setLineDash([]);
        }
        const hot = chart.getActiveElements()[0];
        if (hot) {
          ctx.strokeStyle = '#9fb0b8'; // html .xhair
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(hot.element.x, a.top);
          ctx.lineTo(hot.element.x, a.bottom);
          ctx.stroke();
        }
        ctx.restore();
      },
      // pixel position of each point (CSS px, relative to the canvas), so the end-to-end test can hover a real point
      afterRender: (chart) => {
        cv.dataset['points'] = JSON.stringify(
          chart.getDatasetMeta(0).data.map((e) => ({ x: Math.round(e.x), y: Math.round(e.y) })),
        );
      },
      afterDatasetsDraw: (chart) => {
        const { ctx, chartArea: a } = chart;
        const el = chart.getDatasetMeta(0).data[pts.length - 1];
        ctx.save();
        if (el) {
          ctx.font = `600 12px ${font}`;
          ctx.fillStyle = '#10202b';
          ctx.textAlign = el.x > chart.width - 90 ? 'right' : 'center';
          // above the point, or below it when the point is too close to the top for the label to fit
          ctx.fillText(fmtVal(test, last.v), el.x, el.y - 12 < a.top + 4 ? el.y + 20 : el.y - 12);
        }
        ctx.font = `500 11px ${font}`;
        ctx.fillStyle = inkMuted;
        ctx.textAlign = 'left';
        ctx.fillText(unit, a.left, 11);
        ctx.restore();
      },
    };

    const onHover = (event: ChartEvent, active: readonly { index: number }[]): void => {
      const native = event.native;
      const hit = active[0];
      const p = hit ? pts[hit.index] : undefined;
      if (hit && p && native instanceof MouseEvent) tip.show(pointTip(test, p, unit), native);
      else tip.hide();
    };

    const chart = new Chart<'line', Xy[]>(cv, {
      type: 'line',
      data: {
        datasets: [
          {
            data: pts.map((p) => ({ x: p.t, y: p.v })),
            borderColor: teal,
            borderWidth: 2,
            borderJoinStyle: 'round',
            borderCapStyle: 'round',
            tension: 0,
            pointRadius: 5,
            pointHoverRadius: 5,
            pointHitRadius: 14,
            pointBackgroundColor: pts.map((p) => flagColor(p.flag)),
            pointBorderColor: '#fff', // html .pt: a white ring
            pointBorderWidth: 2,
            pointHoverBorderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 640 / 270, // the HTML's viewBox
        animation: false,
        layout: { padding: { top: 16, right: stage ? 56 : 14, bottom: 0, left: 0 } },
        interaction: { mode: 'nearest', intersect: true },
        events: ['mousemove', 'mouseout'],
        onHover,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: {
            type: 'linear',
            min: ax.tmin,
            max: ax.tmax,
            border: { display: false },
            grid: { display: false },
            afterBuildTicks: (s) => {
              s.ticks = [0, 1, 2, 3, 4].map((i) => ({
                value: ax.tmin + ((ax.tmax - ax.tmin) * i) / 4,
              }));
            },
            ticks: {
              color: inkMuted,
              font: { family: font, size: 11 },
              padding: 8,
              maxRotation: 0,
              callback: (v) =>
                new Date(Number(v)).toLocaleDateString('en-GB', {
                  month: 'short',
                  year: '2-digit',
                }),
            },
          },
          y: {
            type: 'linear',
            min: ax.ymin,
            max: ax.ymax,
            border: { display: false },
            grid: { color: '#e6ecef', lineWidth: 1 }, // html .grid-l
            afterBuildTicks: (s) => {
              s.ticks = ax.ticks.map((value) => ({ value }));
            },
            ticks: {
              color: inkMuted,
              font: { family: font, size: 11 },
              padding: 8,
              callback: (v) => String(+Number(v).toFixed(dec + 1)),
            },
          },
        },
      },
      plugins: [decor],
    });
    cv.addEventListener('mouseleave', () => tip.hide());
    return chart;
  }
}
