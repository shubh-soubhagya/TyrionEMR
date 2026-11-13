// Port of the clinical domain in reference/emr-ui.html (html:377-414). Pure functions, no Angular.

export type TestCode = 'CREAT' | 'EGFR' | 'BUN' | 'K' | 'HB' | 'CA' | 'PHOS' | 'UACR';
export type Sex = 'M' | 'F' | 'O';
export type Flag = 'normal' | 'low' | 'high' | 'critical_low' | 'critical_high' | 'unknown';

interface LabTest {
  name: string;
  canon: string;
  dec: number;
  units: Record<string, number>;
  ranges: Partial<Record<'M' | 'F' | 'any', readonly [number | null, number | null]>>;
  crit: [number | null, number | null];
  max: number;
}

export const LAB_TESTS: Record<TestCode, LabTest> = {
  CREAT: {
    name: 'Serum creatinine',
    canon: 'mg/dL',
    dec: 2,
    units: { 'mg/dL': 1, 'µmol/L': 0.0113 },
    ranges: { M: [0.7, 1.3], F: [0.6, 1.1] },
    crit: [null, 5.0],
    max: 30,
  },
  EGFR: {
    name: 'eGFR',
    canon: 'mL/min/1.73m²',
    dec: 0,
    units: { 'mL/min/1.73m²': 1 },
    ranges: { any: [90, null] },
    crit: [10, null],
    max: 200,
  },
  BUN: {
    name: 'Blood urea nitrogen',
    canon: 'mg/dL',
    dec: 1,
    units: { 'mg/dL': 1, 'mmol/L (urea)': 2.8 },
    ranges: { any: [7, 20] },
    crit: [null, 100],
    max: 300,
  },
  K: {
    name: 'Potassium',
    canon: 'mmol/L',
    dec: 1,
    units: { 'mmol/L': 1, 'mEq/L': 1 },
    ranges: { any: [3.5, 5.0] },
    crit: [2.8, 6.0],
    max: 12,
  },
  HB: {
    name: 'Hemoglobin',
    canon: 'g/dL',
    dec: 1,
    units: { 'g/dL': 1, 'g/L': 0.1 },
    ranges: { M: [13.5, 17.5], F: [12.0, 15.5] },
    crit: [7.0, null],
    max: 25,
  },
  CA: {
    name: 'Calcium',
    canon: 'mg/dL',
    dec: 1,
    units: { 'mg/dL': 1, 'mmol/L': 4.008 },
    ranges: { any: [8.5, 10.5] },
    crit: [6.5, 13.0],
    max: 20,
  },
  PHOS: {
    name: 'Phosphorus',
    canon: 'mg/dL',
    dec: 1,
    units: { 'mg/dL': 1, 'mmol/L': 3.097 },
    ranges: { any: [2.5, 4.5] },
    crit: [1.0, 8.0],
    max: 20,
  },
  UACR: {
    name: 'Urine albumin-creatinine ratio',
    canon: 'mg/g',
    dec: 0,
    units: { 'mg/g': 1, 'mg/mmol': 8.84 },
    ranges: { any: [null, 30] },
    crit: [null, null],
    max: 20000,
  },
};

export const TEST_ORDER: readonly TestCode[] = [
  'CREAT',
  'EGFR',
  'BUN',
  'K',
  'HB',
  'CA',
  'PHOS',
  'UACR',
];

export interface Range {
  low: number | null;
  high: number | null;
  critLow: number | null;
  critHigh: number | null;
}

export function rangeFor(test: TestCode, sex: Sex): Range {
  const t = LAB_TESTS[test];
  const r = (sex === 'M' || sex === 'F' ? t.ranges[sex] : undefined) ??
    t.ranges.any ?? [null, null];
  return { low: r[0], high: r[1], critLow: t.crit[0], critHigh: t.crit[1] };
}

export function flagFor(v: number, r: Range | null): Flag {
  if (!r) return 'unknown';
  if (r.critLow != null && v < r.critLow) return 'critical_low';
  if (r.critHigh != null && v > r.critHigh) return 'critical_high';
  if (r.low != null && v < r.low) return 'low';
  if (r.high != null && v > r.high) return 'high';
  return 'normal';
}

export function refText(r: { low: number | null; high: number | null }): string {
  if (r.low != null && r.high != null) return `${r.low}–${r.high}`;
  if (r.low != null) return `≥ ${r.low}`;
  if (r.high != null) return `< ${r.high}`;
  return '-';
}

export function toCanon(test: TestCode, v: number, unit: string): number {
  const t = LAB_TESTS[test];
  const p = Math.pow(10, t.dec + 1);
  return Math.round(v * (t.units[unit] ?? 1) * p) / p;
}

export const fmtVal = (test: TestCode, v: number): string => Number(v).toFixed(LAB_TESTS[test].dec);

export type EgfrCat = 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5';
export const EGFR_CATS: readonly (readonly [EgfrCat, number, string])[] = [
  ['G1', 90, 'Normal or high'],
  ['G2', 60, 'Mildly decreased'],
  ['G3a', 45, 'Mild to moderately decreased'],
  ['G3b', 30, 'Moderately to severely decreased'],
  ['G4', 15, 'Severely decreased'],
  ['G5', -1, 'Kidney failure'],
];

export const classifyEgfr = (v: number): EgfrCat => EGFR_CATS.find((c) => v >= c[1])?.[0] ?? 'G5';

export const egfrLabel = (c: string): string => EGFR_CATS.find((x) => x[0] === c)?.[2] ?? '';

export type UacrCat = 'A1' | 'A2' | 'A3';
export const classifyUacr = (v: number): UacrCat => (v < 30 ? 'A1' : v <= 300 ? 'A2' : 'A3');
export const uacrLabel = (c: string): string =>
  ({ A1: 'Normal to mildly increased', A2: 'Moderately increased', A3: 'Severely increased' })[
    c as UacrCat
  ] ?? '';

/** CKD-EPI 2021 race-free equation (html:400). */
export function ckdEpi(scr: number, age: number, sex: Sex): number {
  const k = sex === 'F' ? 0.7 : 0.9;
  const a = sex === 'F' ? -0.241 : -0.302;
  return (
    142 *
    Math.pow(Math.min(scr / k, 1), a) *
    Math.pow(Math.max(scr / k, 1), -1.2) *
    Math.pow(0.9938, age) *
    (sex === 'F' ? 1.012 : 1)
  );
}

export function creatFromEgfr(e: number, age: number, sex: Sex): number {
  let lo = 0.3;
  let hi = 20;
  for (let i = 0; i < 40; i++) {
    const m = (lo + hi) / 2;
    if (ckdEpi(m, age, sex) > e) lo = m;
    else hi = m;
  }
  return Math.round(((lo + hi) / 2) * 100) / 100;
}

export interface TrendPoint {
  t: number;
  v: number;
  flag?: Flag;
  id?: string;
}

export interface TrendStats {
  n: number;
  first: number;
  last: number;
  abs: number;
  pct: number;
  slope: number | null;
  direction: 'no_data' | 'insufficient_data' | 'worsening' | 'improving' | 'stable';
  rapid: boolean;
  spanDays: number;
  pts: TrendPoint[];
}

const DAY = 86400000;
const avg = (a: number[]): number => a.reduce((s, x) => s + x, 0) / a.length;

export function trendStats(pts: TrendPoint[], test: TestCode): TrendStats {
  const n = pts.length;
  if (!n) {
    return {
      n: 0,
      first: 0,
      last: 0,
      abs: 0,
      pct: 0,
      slope: null,
      direction: 'no_data',
      rapid: false,
      spanDays: 0,
      pts: [],
    };
  }
  const first = pts[0] as TrendPoint;
  const last = pts[n - 1] as TrendPoint;
  const abs = last.v - first.v;
  const pct = first.v ? (abs / first.v) * 100 : 0;
  const spanDays = Math.round((last.t - first.t) / DAY);
  let slope: number | null = null;
  let direction: TrendStats['direction'] = 'insufficient_data';
  let rapid = false;
  if (n >= 3) {
    const xs = pts.map((p) => (p.t - first.t) / (365.25 * DAY));
    const ys = pts.map((p) => p.v);
    const mx = avg(xs);
    const my = avg(ys);
    let nu = 0;
    let de = 0;
    xs.forEach((x, i) => {
      nu += (x - mx) * ((ys[i] as number) - my);
      de += (x - mx) * (x - mx);
    });
    slope = de ? nu / de : 0;
    if (test === 'EGFR') {
      direction = slope <= -2 ? 'worsening' : slope >= 2 ? 'improving' : 'stable';
      rapid = slope <= -5;
    } else {
      direction = slope > 0.1 ? 'worsening' : slope < -0.1 ? 'improving' : 'stable';
    }
  }
  return { n, first: first.v, last: last.v, abs, pct, slope, direction, rapid, spanDays, pts };
}

/** Point colour for charts (html:373). */
export const flagColor = (f: Flag | undefined): string =>
  f === 'normal'
    ? '#12805c'
    : f === 'low'
      ? '#1560a8'
      : f === 'high'
        ? '#a86400'
        : f && f.startsWith('critical')
          ? '#be2f3b'
          : '#6b7f8c';
