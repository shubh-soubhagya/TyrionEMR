// Turns the raw wording of a server validation message (pydantic's) into a sentence a clinician can act on. The server stays
// the authority; this only rewords what it says. Unknown messages pass through unchanged.

const FIELD_HINTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/icd/i, 'Enter a valid ICD-10 code, for example N18.3 or E11.22.'],
  [/phone/i, 'Enter a valid phone number, for example +91 98200 10101.'],
  [/email/i, 'Enter a valid email address.'],
];

export function friendlyIssue(field: string, issue: string): string {
  if (/^String should match pattern/i.test(issue)) {
    return FIELD_HINTS.find(([re]) => re.test(field))?.[1] ?? 'Check the format of this value.';
  }
  const least = /^String should have at least (\d+) character/i.exec(issue);
  if (least) return `Enter at least ${least[1]} characters.`;
  const most = /^String should have at most (\d+) character/i.exec(issue);
  if (most) return `Use at most ${most[1]} characters.`;
  if (/^Field required/i.test(issue)) return 'This field is required.';
  if (/^Input should be a valid (date|datetime)/i.test(issue)) return 'Enter a valid date.';
  if (/^Input should be a valid (integer|number)/i.test(issue)) return 'Enter a valid number.';
  return issue;
}
