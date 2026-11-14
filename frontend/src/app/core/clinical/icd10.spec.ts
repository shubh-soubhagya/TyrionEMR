import { describe, expect, it } from 'vitest';
import { isIcd10 } from './icd10';

describe('isIcd10', () => {
  it('accepts codes the server accepts', () => {
    for (const c of ['N18', 'N18.3', 'n18.32', 'E11.22', 'I10', 'Z99.2'])
      expect(isIcd10(c)).toBe(true);
  });
  it('rejects the rest', () => {
    for (const c of ['IGDOJ', 'ICN-78', '18.3', 'N1', 'N18.', 'N18.12345', ''])
      expect(isIcd10(c)).toBe(false);
  });
});
