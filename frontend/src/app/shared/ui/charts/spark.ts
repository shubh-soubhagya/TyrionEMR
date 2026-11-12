import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { fmtVal, TrendStats } from '../../../core/clinical/lab-tests';
import { EmrTip } from '../tooltip/tooltip';

/** Tiny eGFR trend line for list rows (html `spark()`, html:1259). */
@Component({
  selector: 'emr-spark',
  imports: [EmrTip],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (view(); as v) {
      <svg
        class="spark"
        [attr.width]="v.W"
        [attr.height]="v.H"
        [attr.viewBox]="'0 0 ' + v.W + ' ' + v.H"
        role="img"
        [attr.aria-label]="'eGFR trend, ' + stats().direction"
        [emrTip]="v.tip"
      >
        <path [attr.d]="v.d" fill="none" [attr.stroke]="v.col" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round" />
        <circle [attr.cx]="v.cx" [attr.cy]="v.cy" r="2.6" [attr.fill]="v.col" />
      </svg>
    } @else {
      <span class="nd">-</span>
    }
  `,
  styles: `
    :host {
      display: inline;
    }
  `,
})
export class EmrSpark {
  readonly stats = input.required<TrendStats>();

  protected readonly view = computed(() => {
    const s = this.stats();
    if (!s || s.n < 2) return null;
    const W = 86;
    const H = 26;
    const pts = s.pts;
    const t0 = (pts[0] as { t: number }).t;
    const t1 = (pts[pts.length - 1] as { t: number }).t;
    const vs = pts.map((p) => p.v);
    const lo = Math.min(...vs);
    const hi = Math.max(...vs);
    const rg = hi - lo || 1;
    const x = (t: number) => 3 + ((t - t0) / (t1 - t0 || 1)) * (W - 6);
    const y = (v: number) => H - 4 - ((v - lo) / rg) * (H - 8);
    // Colors: html:1263. #6b7f89 is the prototype's own (one digit off --ink-3).
    const col = s.direction === 'worsening' ? '#be2f3b' : s.direction === 'improving' ? '#12805c' : '#6b7f89';
    const last = pts[pts.length - 1] as { t: number; v: number };
    return {
      W,
      H,
      col,
      d: pts.map((p, i) => (i ? 'L' : 'M') + x(p.t).toFixed(1) + ' ' + y(p.v).toFixed(1)).join(' '),
      cx: x(last.t).toFixed(1),
      cy: y(last.v).toFixed(1),
      tip: [`eGFR ${fmtVal('EGFR', s.first)} to ${fmtVal('EGFR', s.last)}`, `${s.n} results, ${s.direction}`],
    };
  });
}
