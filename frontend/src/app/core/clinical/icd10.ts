/**
 * ICD-10 code as the server checks it (patient-svc): a letter, two characters, then an optional dot and one to four
 * characters. Lower case is accepted when typing and sent in upper case.
 */
const ICD10 = /^[A-Za-z][0-9][0-9A-Za-z](\.[0-9A-Za-z]{1,4})?$/;

export const ICD10_HINT = 'Enter a valid ICD-10 code, for example N18.3 or E11.22.';

export function isIcd10(code: string): boolean {
  return ICD10.test(code.trim());
}
