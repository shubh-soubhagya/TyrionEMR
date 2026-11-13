import { describe, expect, it } from 'vitest';
import { ageOf, cap, fmtDate, fmtDT, isoDate, signed } from './format';

describe('format helpers (display only)', () => {
  it('formats dates in the en-GB style of the reference and shows a dash when missing', () => {
    expect(fmtDate('2026-11-13T04:30:00Z')).toBe('13 Nov 2026');
    expect(fmtDate(null)).toBe('-');
    expect(fmtDate(undefined)).toBe('-');
    expect(fmtDT(null)).toBe('-');
    expect(isoDate(new Date(2026, 10, 3))).toBe('2026-11-03');
  });

  it('prints a signed number with a real minus sign', () => {
    expect(signed(-8.24)).toBe('−8.2');
    expect(signed(0.5)).toBe('+0.5');
    expect(signed(0)).toBe('0.0');
    expect(signed(-29.6, 0)).toBe('−30');
  });

  it('capitalizes the first letter only', () => {
    expect(cap('severe')).toBe('Severe');
    expect(cap('')).toBe('');
  });

  it('computes age in whole years on a date (used only to validate the date of birth field)', () => {
    expect(ageOf('1965-05-02', '2026-05-01')).toBe(60);
    expect(ageOf('1965-05-02', '2026-05-02')).toBe(61);
  });
});
