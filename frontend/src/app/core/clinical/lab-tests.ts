// Display helpers and types for lab tests. NO clinical data lives here any more: reference ranges, critical limits, unit
// factors and plausible limits come from lab-svc (`GET /labs/tests`, HLD ADR-019) and flags, categories and trends are
// computed by the services. What is left is how a value is shown.

export type TestCode = 'CREAT' | 'EGFR' | 'BUN' | 'K' | 'HB' | 'CA' | 'PHOS' | 'UACR';
export type Sex = 'M' | 'F' | 'O';
export type Flag = 'normal' | 'low' | 'high' | 'critical_low' | 'critical_high' | 'unknown';

/** Name, canonical unit and number of decimals to show: presentation only (the server rounds what it stores). */
export const LAB_TESTS: Record<TestCode, { name: string; canon: string; dec: number }> = {
  CREAT: { name: 'Serum creatinine', canon: 'mg/dL', dec: 2 },
  EGFR: { name: 'eGFR', canon: 'mL/min/1.73m²', dec: 0 },
  BUN: { name: 'Blood urea nitrogen', canon: 'mg/dL', dec: 1 },
  K: { name: 'Potassium', canon: 'mmol/L', dec: 1 },
  HB: { name: 'Hemoglobin', canon: 'g/dL', dec: 1 },
  CA: { name: 'Calcium', canon: 'mg/dL', dec: 1 },
  PHOS: { name: 'Phosphorus', canon: 'mg/dL', dec: 1 },
  UACR: { name: 'Urine albumin-creatinine ratio', canon: 'mg/g', dec: 0 },
};

export function refText(r: { low: number | null; high: number | null }): string {
  if (r.low != null && r.high != null) return `${r.low}–${r.high}`;
  if (r.low != null) return `≥ ${r.low}`;
  if (r.high != null) return `< ${r.high}`;
  return '-';
}

export const fmtVal = (test: TestCode, v: number): string => Number(v).toFixed(LAB_TESTS[test].dec);

export type EgfrCat = 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5';

/** KDIGO eGFR categories: used for labels on screen and by the shared-vector test of the live preview. */
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

/** One point of a chart, as the chart components draw it (time in ms). */
export interface TrendPoint {
  t: number;
  v: number;
  flag?: Flag;
  id?: string;
}

/** Trend numbers as the chips and the sparkline show them. All values come from lab-svc. */
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

export const uacrLabel = (c: string): string =>
  ({ A1: 'Normal to mildly increased', A2: 'Moderately increased', A3: 'Severely increased' })[
    c as UacrCat
  ] ?? '';

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
