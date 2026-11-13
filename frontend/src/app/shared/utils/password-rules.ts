/** The sign-up rules the checklist shows (reference html:619-620). The server is the authority; this only guides typing. */
export interface PasswordChecks {
  readonly length: boolean;
  readonly letterAndDigit: boolean;
  readonly notCommon: boolean;
}

const COMMON = ['password123', '1234567890', 'qwertyuiop', 'welcome123'];

export function passwordChecks(pw: string): PasswordChecks {
  return {
    length: pw.length >= 10,
    letterAndDigit: /[A-Za-z]/.test(pw) && /\d/.test(pw),
    notCommon: pw.length > 0 && !COMMON.includes(pw.toLowerCase()),
  };
}

export function passwordOk(pw: string): boolean {
  const c = passwordChecks(pw);
  return c.length && c.letterAndDigit && c.notCommon;
}

/** Server rule codes (`details[].code` of a 422) mapped to the checklist line they break. */
export type RuleLine = 'length' | 'letterAndDigit' | 'notCommon';

export function ruleLineForServerCode(code: string): RuleLine | null {
  switch (code) {
    case 'TOO_SHORT':
    case 'TOO_LONG':
      return 'length';
    case 'NEEDS_LETTER':
    case 'NEEDS_DIGIT':
      return 'letterAndDigit';
    case 'TOO_COMMON':
    case 'CONTAINS_EMAIL':
      return 'notCommon';
    default:
      return null;
  }
}
