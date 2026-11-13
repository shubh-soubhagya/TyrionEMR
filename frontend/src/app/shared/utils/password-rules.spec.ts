import { describe, expect, it } from 'vitest';
import { passwordChecks, passwordOk, ruleLineForServerCode } from './password-rules';

describe('passwordChecks', () => {
  it('needs 10 characters, a letter and a digit, and not a common password', () => {
    expect(passwordChecks('short1')).toMatchObject({
      length: false,
      letterAndDigit: true,
      notCommon: true,
    });
    expect(passwordChecks('onlyletterss')).toMatchObject({ length: true, letterAndDigit: false });
    expect(passwordChecks('1234567890')).toMatchObject({
      length: true,
      letterAndDigit: false,
      notCommon: false,
    });
    expect(passwordChecks('Password123').notCommon).toBe(true);
    expect(passwordChecks('PASSWORD123').notCommon).toBe(false);
    expect(passwordChecks('').notCommon).toBe(false);
  });

  it('passwordOk needs every line', () => {
    expect(passwordOk('Nephro#2026')).toBe(true);
    expect(passwordOk('nopeletters')).toBe(false);
  });
});

describe('ruleLineForServerCode', () => {
  it.each([
    ['TOO_SHORT', 'length'],
    ['TOO_LONG', 'length'],
    ['NEEDS_LETTER', 'letterAndDigit'],
    ['NEEDS_DIGIT', 'letterAndDigit'],
    ['TOO_COMMON', 'notCommon'],
    ['CONTAINS_EMAIL', 'notCommon'],
    ['OTHER', null],
  ])('%s -> %s', (code, line) => {
    expect(ruleLineForServerCode(code)).toBe(line);
  });
});
