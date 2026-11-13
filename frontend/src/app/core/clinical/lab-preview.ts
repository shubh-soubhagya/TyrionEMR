// The lab form's live preview (HLD ADR-019): convert to the canonical unit and flag, using the SERVER's catalog
// (`GET /labs/tests?sex=&age=`). It is a preview only; lab-svc recomputes everything when the report is saved.
// `lab-svc/tests/vectors/lab_cases.json` is run through these functions in lab-preview.spec.ts.
import type { CatalogItemDto, RangeDto } from '../api/dto/lab.dto';
import { cmp, decFromNumber, formatDec, mul, parseDec, roundHalfUp, type Dec } from './decimal';
import type { Flag } from './lab-tests';

/** Matching key for a unit spelling, as lab-svc does: 'µmol/L', 'μmol/L', 'umol/L' -> 'umol/l'; '…m²' -> '…m2'. */
export function unitKey(unit: string): string {
  return unit.normalize('NFKC').replace(/μ/g, 'u').replace(/\s+/g, '').toLowerCase();
}

/** The catalog's spelling of `unit` for this test, or null when it is not an accepted unit. */
export function resolveUnit(item: CatalogItemDto, unit: string): string | null {
  const key = unitKey(unit);
  return item.units.find((u) => unitKey(u.unit) === key)?.unit ?? null;
}

export interface LabPreview {
  /** The value in the canonical unit, as text with `decimals + 1` places (the server's rule). */
  readonly canonical: string;
  readonly flag: Flag;
}

/** `null` when the value is not a plain non-negative decimal or the unit is not in the catalog. */
export function previewResult(
  item: CatalogItemDto,
  value: string,
  unit: string,
): LabPreview | null {
  const v = parseDec(value);
  const display = resolveUnit(item, unit);
  if (!v || !display) return null;
  const factor = parseDec(item.units.find((u) => u.unit === display)?.factor ?? '');
  if (!factor) return null;
  const canonical = roundHalfUp(mul(v, factor), item.decimals + 1);
  return { canonical: formatDec(canonical), flag: flagFor(canonical, item.range) };
}

const lim = (n: number | null): Dec | null => (n === null ? null : decFromNumber(n));

/** Critical limits first, then the normal range; limits are exclusive. No range means `unknown`, never `normal`. */
export function flagFor(value: Dec, range: RangeDto | null): Flag {
  if (!range) return 'unknown';
  const critLow = lim(range.critical_low);
  const critHigh = lim(range.critical_high);
  const low = lim(range.low);
  const high = lim(range.high);
  if (critLow && cmp(value, critLow) < 0) return 'critical_low';
  if (critHigh && cmp(value, critHigh) > 0) return 'critical_high';
  if (low && cmp(value, low) < 0) return 'low';
  if (high && cmp(value, high) > 0) return 'high';
  return 'normal';
}

/** Whether the canonical value is above the plausibility limit of the test (blocks saving, like the server). */
export function exceedsPlausibleMax(item: CatalogItemDto, canonical: string): boolean {
  const c = parseDec(canonical);
  return c !== null && cmp(c, decFromNumber(item.plausible_max)) > 0;
}
