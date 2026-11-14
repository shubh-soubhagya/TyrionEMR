import { describe, expect, it } from 'vitest';
import { DAY } from '../../core/format';
import { bandRanges, DEFAULT_STAGE_BANDS, trendAxes } from './chart-axes';

const T0 = Date.UTC(2026, 0, 1);

describe('trendAxes', () => {
  it('pads the value range by 18 percent and snaps the ticks to a nice step', () => {
    const a = trendAxes([T0, T0 + 90 * DAY], [1.2, 1.8], null, null, false);
    expect(a.ticks[0]).toBe(a.ymin);
    expect(a.ticks[a.ticks.length - 1]).toBe(a.ymax);
    expect(a.ymin).toBeLessThanOrEqual(1.2);
    expect(a.ymax).toBeGreaterThanOrEqual(1.8);
    const steps = new Set(
      a.ticks.slice(1).map((t, i) => Math.round((t - (a.ticks[i] ?? 0)) * 1000)),
    );
    expect(steps.size).toBe(1);
  });

  it('includes the reference range in the y range', () => {
    const a = trendAxes([T0, T0 + 90 * DAY], [1.2, 1.3], 0.7, 1.3, false);
    expect(a.ymin).toBeLessThanOrEqual(0.7);
  });

  it('uses 0 to at least 100 for the eGFR stage view', () => {
    const a = trendAxes([T0, T0 + 90 * DAY], [30, 50], null, null, true);
    expect(a.ymin).toBe(0);
    expect(a.ymax).toBeGreaterThanOrEqual(100);
  });

  it('widens a span shorter than 30 days by 15 days each side', () => {
    const a = trendAxes([T0], [4.2], null, null, false);
    expect(a.tmin).toBe(T0 - 15 * DAY);
    expect(a.tmax).toBe(T0 + 15 * DAY);
  });
});

describe('bandRanges', () => {
  it('turns the server list into [lower, upper, code], top band ending at 100', () => {
    const r = bandRanges([
      { code: 'G3a', lower: 45 },
      { code: 'G1', lower: 90 },
      { code: 'G2', lower: 60 },
    ]);
    expect(r).toEqual([
      [90, 100, 'G1'],
      [60, 90, 'G2'],
      [45, 60, 'G3a'],
    ]);
  });
  it('is null without a list, so the built-in KDIGO bands apply', () => {
    expect(bandRanges(null)).toBeNull();
    expect(bandRanges([])).toBeNull();
    expect(DEFAULT_STAGE_BANDS).toHaveLength(6);
  });
});
