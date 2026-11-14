import { describe, expect, it } from 'vitest';
import { distTip, pointTip, sparkTip } from './chart-tips';

const t = Date.UTC(2026, 10, 1, 12);

describe('pointTip', () => {
  it('normal point: value with unit, flag label, date', () => {
    expect(pointTip('K', { t, v: 4.2, flag: 'normal' }, 'mmol/L')).toEqual([
      '4.2 mmol/L',
      'Normal',
      '01 Nov 2026',
    ]);
  });
  it('high point', () => {
    expect(pointTip('CREAT', { t, v: 1.9, flag: 'high' }, 'mg/dL')[1]).toBe('High');
  });
  it('unknown point says "No range"; a point without a flag has an empty line', () => {
    expect(pointTip('K', { t, v: 4, flag: 'unknown' }, 'mmol/L')[1]).toBe('No range');
    expect(pointTip('K', { t, v: 4 }, 'mmol/L')[1]).toBe('');
  });
});

describe('sparkTip', () => {
  const s = (n: number, direction: 'worsening' | 'insufficient_data') => ({
    n,
    first: 61,
    last: 44,
    direction,
  });
  it('one point is singular and a long series is plural', () => {
    expect(sparkTip(s(1, 'insufficient_data'))).toEqual([
      'eGFR 61 to 44',
      '1 result, insufficient data',
    ]);
    expect(sparkTip(s(12, 'worsening'))[1]).toBe('12 results, worsening');
  });
});

describe('distTip', () => {
  it('singular, plural and zero', () => {
    expect(distTip(1, 'G3b')).toEqual(['1 patient in G3b: Moderately to severely decreased']);
    expect(distTip(0, 'G1')).toEqual(['0 patients in G1: Normal or high']);
  });
});
