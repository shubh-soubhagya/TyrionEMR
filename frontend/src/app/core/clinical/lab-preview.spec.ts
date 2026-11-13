// The shared vectors of lab-svc (HLD ADR-019): the browser's live preview must give exactly the server's canonical value
// and flag for every case. The file is mounted read-only into the web container (compose.yaml); this suite FAILS, it does
// not skip, when the file is missing, so a broken mount can never turn the check off.
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { classifyEgfr, classifyUacr } from './lab-tests';
import { exceedsPlausibleMax, previewResult, resolveUnit, unitKey } from './lab-preview';
import { cmp, formatDec, mul, parseDec, roundHalfUp } from './decimal';
import { CATALOG_BY_SEX } from './testing/catalog-fixture';

const VECTORS_PATH = '/lab-vectors/lab_cases.json';

interface VectorCase {
  id: string;
  test: string;
  value: string;
  unit: string;
  sex: 'M' | 'F' | 'O';
  age: number;
  expect: { canonical: string; flag: string; category?: string; uacr_category?: string };
}

const cases: VectorCase[] = existsSync(VECTORS_PATH)
  ? (JSON.parse(readFileSync(VECTORS_PATH, 'utf-8')) as VectorCase[])
  : [];

describe('shared lab vectors', () => {
  it('are mounted and complete (lab-svc/tests/vectors/lab_cases.json at /lab-vectors)', () => {
    expect(
      existsSync(VECTORS_PATH),
      `${VECTORS_PATH} is missing: mount ../lab-svc/tests/vectors`,
    ).toBe(true);
    expect(cases.length).toBeGreaterThanOrEqual(13);
  });

  it.each(cases.map((c) => [c.id, c] as const))('%s', (_id, c) => {
    const item = CATALOG_BY_SEX[c.sex].items.find((i) => i.code === c.test);
    expect(item, `${c.test} is in the catalog`).toBeDefined();
    if (!item) return;
    const out = previewResult(item, c.value, c.unit);
    expect(out).not.toBeNull();
    expect(out?.canonical).toBe(c.expect.canonical);
    expect(out?.flag).toBe(c.expect.flag);
    if (c.expect.category) expect(classifyEgfr(Number(out?.canonical))).toBe(c.expect.category);
    if (c.expect.uacr_category)
      expect(classifyUacr(Number(out?.canonical))).toBe(c.expect.uacr_category);
  });
});

describe('exact decimal arithmetic', () => {
  it('rounds half-up where binary floats would not', () => {
    // 1.005 * 1 to 2 places: a float gives 1.00; the exact value is 1.005 which rounds up
    const d = mul(parseDec('1.005') ?? { n: 0n, scale: 0 }, { n: 1n, scale: 0 });
    expect(formatDec(roundHalfUp(d, 2))).toBe('1.01');
    expect(formatDec(roundHalfUp({ n: 2675n, scale: 3 }, 2))).toBe('2.68');
    expect(formatDec(roundHalfUp({ n: 5n, scale: 0 }, 2))).toBe('5.00');
  });

  it('parses only plain non-negative decimals', () => {
    for (const bad of ['', ' ', '-1', '+1', '1e3', '1,5', 'abc', '.5', '5.'])
      expect(parseDec(bad), bad).toBeNull();
    expect(parseDec(' 12.50 ')).toEqual({ n: 1250n, scale: 2 });
  });

  it('compares across scales', () => {
    expect(cmp({ n: 60n, scale: 0 }, { n: 600n, scale: 1 })).toBe(0);
    expect(cmp({ n: 599n, scale: 1 }, { n: 60n, scale: 0 })).toBe(-1);
  });
});

describe('units and limits', () => {
  const creat = CATALOG_BY_SEX.M.items.find((i) => i.code === 'CREAT');

  it('matches unit spellings the way lab-svc does', () => {
    expect(unitKey('µmol/L')).toBe('umol/l');
    expect(unitKey('μmol/L')).toBe('umol/l');
    expect(unitKey('UMOL / L')).toBe('umol/l');
    if (!creat) throw new Error('catalog fixture has no CREAT');
    expect(resolveUnit(creat, 'umol/L')).toBe('µmol/L');
    expect(resolveUnit(creat, 'mg/dl')).toBe('mg/dL');
    expect(resolveUnit(creat, 'furlongs')).toBeNull();
  });

  it('flags nothing for an unknown unit or a non-number', () => {
    if (!creat) throw new Error('catalog fixture has no CREAT');
    expect(previewResult(creat, '1.0', 'furlongs')).toBeNull();
    expect(previewResult(creat, 'abc', 'mg/dL')).toBeNull();
    expect(previewResult(creat, '', 'mg/dL')).toBeNull();
  });

  it('knows when a value is beyond the plausible limit of the test', () => {
    if (!creat) throw new Error('catalog fixture has no CREAT');
    expect(exceedsPlausibleMax(creat, '30.000')).toBe(false);
    expect(exceedsPlausibleMax(creat, '30.001')).toBe(true);
  });
});
