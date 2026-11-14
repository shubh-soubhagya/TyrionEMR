// Axis maths for the lab trend charts, kept pure so it is unit-tested without a canvas. Ported from the HTML
// `lineChart()` (html:983-1004): same padding rule, same "nice" tick step, same 30-day minimum span.
import { DAY } from '../../core/format';

export interface StageBand {
  readonly code: string;
  readonly lower: number;
}

/** [lower, upper, code], top band first. KDIGO G1..G5; used only when lab-svc sends no `stage_bands`. */
export type BandRange = readonly [number, number, string];

export const DEFAULT_STAGE_BANDS: readonly BandRange[] = [
  [90, 100, 'G1'],
  [60, 90, 'G2'],
  [45, 60, 'G3a'],
  [30, 45, 'G3b'],
  [15, 30, 'G4'],
  [0, 15, 'G5'],
];

/** Bands from the server's `{code, lower}` list (the top band ends at 100); null when there are none. */
export function bandRanges(b: readonly StageBand[] | null): readonly BandRange[] | null {
  if (!b || b.length === 0) return null;
  const sorted = [...b].sort((x, y) => y.lower - x.lower);
  return sorted.map((x, i) => [x.lower, i === 0 ? 100 : (sorted[i - 1]?.lower ?? 100), x.code]);
}

const niceStep = (r: number): number => {
  const p = Math.pow(10, Math.floor(Math.log10(r)));
  const f = r / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
};

export interface Axes {
  readonly tmin: number;
  readonly tmax: number;
  readonly ymin: number;
  readonly ymax: number;
  /** y tick values, ascending; the first is `ymin` and the last is `ymax`. */
  readonly ticks: readonly number[];
}

export function trendAxes(
  times: readonly number[],
  values: readonly number[],
  low: number | null,
  high: number | null,
  stage: boolean,
): Axes {
  let tmin = times[0] ?? 0;
  let tmax = times[times.length - 1] ?? 0;
  if (tmax - tmin < 30 * DAY) {
    tmin -= 15 * DAY;
    tmax += 15 * DAY;
  }
  let ymin = Math.min(...values, low == null ? Infinity : low);
  let ymax = Math.max(...values, high == null ? -Infinity : high);
  if (stage) {
    ymin = 0;
    ymax = Math.max(ymax, 100);
  } else {
    const pad = (ymax - ymin || 1) * 0.18;
    ymin = Math.max(0, ymin - pad);
    ymax += pad;
  }
  const step = niceStep((ymax - ymin) / 4);
  const ticks: number[] = [];
  for (let t = Math.floor(ymin / step) * step; t <= ymax + step * 0.01; t += step) {
    ticks.push(Math.round(t * 1000) / 1000);
  }
  // headroom: a value sitting on the top gridline would have its label cut off, so add one more step above it
  const top = Math.max(...values, high ?? -Infinity);
  const last = ticks[ticks.length - 1] ?? ymax;
  if (!stage && last - top < step * 0.4) ticks.push(Math.round((last + step) * 1000) / 1000);
  return { tmin, tmax, ymin: ticks[0] ?? ymin, ymax: ticks[ticks.length - 1] ?? ymax, ticks };
}
