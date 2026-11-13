// Exact decimal arithmetic for the lab form's live preview (HLD ADR-019). The server converts with exact decimals and
// rounds half-up to `decimals + 1` places; floats would disagree with it on values like 1.005, so the browser uses
// scaled BigInt integers instead. No decimal library is needed for multiply, round and compare.

/** A non-negative decimal as an integer and a count of digits after the point: 1.695 is {n: 1695n, scale: 3}. */
export interface Dec {
  readonly n: bigint;
  readonly scale: number;
}

const PLAIN = /^\d+(\.\d+)?$/;

/** Parses "150", "0.0113", "1.5". Returns null for anything else (signs, exponents, blanks, text). */
export function parseDec(text: string): Dec | null {
  const t = text.trim();
  if (!PLAIN.test(t)) return null;
  const [whole = '0', frac = ''] = t.split('.');
  return { n: BigInt(whole + frac), scale: frac.length };
}

/** Same as parseDec for a JSON number (a range limit such as 0.7 or 5.0). */
export function decFromNumber(v: number): Dec {
  const d = parseDec(String(v));
  if (!d) throw new Error('not a plain decimal: ' + String(v));
  return d;
}

export const mul = (a: Dec, b: Dec): Dec => ({ n: a.n * b.n, scale: a.scale + b.scale });

const pow10 = (k: number): bigint => 10n ** BigInt(k);

/** Rounds half-up (ties go away from zero; values are never negative) to `places` decimals. */
export function roundHalfUp(d: Dec, places: number): Dec {
  if (d.scale <= places) return { n: d.n * pow10(places - d.scale), scale: places };
  const div = pow10(d.scale - places);
  const q = d.n / div;
  const r = d.n % div;
  return { n: r * 2n >= div ? q + 1n : q, scale: places };
}

/** "1.695", with exactly `d.scale` digits after the point (none when the scale is 0). */
export function formatDec(d: Dec): string {
  if (d.scale === 0) return d.n.toString();
  const s = d.n.toString().padStart(d.scale + 1, '0');
  return s.slice(0, -d.scale) + '.' + s.slice(-d.scale);
}

/** -1, 0 or 1, exact across different scales. */
export function cmp(a: Dec, b: Dec): -1 | 0 | 1 {
  const s = Math.max(a.scale, b.scale);
  const x = a.n * pow10(s - a.scale);
  const y = b.n * pow10(s - b.scale);
  return x < y ? -1 : x > y ? 1 : 0;
}
