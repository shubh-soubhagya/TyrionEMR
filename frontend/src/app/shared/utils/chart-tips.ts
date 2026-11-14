// Text of the chart tooltips (html:1000, 1265, 1300). Pure functions of service data; the tooltip component prints each
// line as text, so no markup from data can reach the page.
import {
  egfrLabel,
  fmtVal,
  type Flag,
  type TestCode,
  type TrendStats,
} from '@core/clinical/lab-tests';
import { fmtDate } from '@core/format';

// Same words as FLAG in html:371 and as the lab table's chips (`FLAG_VIEWS`); kept here so this file stays pure.
const FLAG_TEXT: Readonly<Record<Flag, string>> = {
  normal: 'Normal',
  low: 'Low',
  high: 'High',
  critical_low: 'Critical low',
  critical_high: 'Critical high',
  unknown: 'No range',
};

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`;

/** Direction as the trend chips say it ("insufficient data", not the wire value). */
export const directionText = (d: TrendStats['direction']): string => d.replace(/_/g, ' ');

/** Trend point: bold "<value> <unit>", the flag label, the date. */
export function pointTip(
  test: TestCode,
  p: { t: number; v: number; flag?: Flag },
  unit: string,
): readonly string[] {
  return [`${fmtVal(test, p.v)} ${unit}`, p.flag ? FLAG_TEXT[p.flag] : '', fmtDate(p.t)];
}

/** List sparkline. `n` is the number of points lab-svc returned for it (at most 12), not all eGFR results. */
export function sparkTip(
  s: Pick<TrendStats, 'n' | 'first' | 'last' | 'direction'>,
): readonly string[] {
  return [
    `eGFR ${fmtVal('EGFR', s.first)} to ${fmtVal('EGFR', s.last)}`,
    `${plural(s.n, 'result')}, ${directionText(s.direction)}`,
  ];
}

/** Dashboard eGFR category bar. */
export const distTip = (n: number, stage: string): readonly string[] => [
  `${plural(n, 'patient')} in ${stage}: ${egfrLabel(stage)}`,
];
