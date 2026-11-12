import { ValidationErrors } from '@angular/forms';

/**
 * The single map from Angular/custom validation error keys to readable messages.
 * Each entry receives the error value (e.g. `{ min: 60, actual: 40 }` for `min`).
 * A custom validator can also return `{ someKey: 'Its own message' }` or `{ someKey: { message } }`
 * and that text is shown as is, so one-off validators need no entry here.
 */
type Formatter = (value: unknown) => string;

const num = (value: unknown, key: string): string => {
  const v = (value as Record<string, unknown> | null)?.[key];
  return typeof v === 'number' || typeof v === 'string' ? String(v) : '';
};

export const ERROR_MESSAGES: Readonly<Record<string, Formatter>> = {
  required: () => 'This field is required.',
  email: () => 'Enter a valid email address.',
  min: (v) => `Enter a value of at least ${num(v, 'min')}.`,
  max: (v) => `Enter a value of at most ${num(v, 'max')}.`,
  minlength: (v) => `Enter at least ${num(v, 'requiredLength')} characters.`,
  maxlength: (v) => `Enter at most ${num(v, 'requiredLength')} characters.`,
  pattern: () => 'The format is not valid.',
  // Custom keys used by our validators (built in later phases):
  range: (v) => `Enter ${num(v, 'min')} to ${num(v, 'max')}${unitSuffix(v)}.`,
  futureDate: () => 'The date cannot be in the future.',
  bpOrder: () => 'Systolic must be higher than diastolic.',
  passwordMismatch: () => 'Passwords do not match.',
  icd10: () => 'Use an ICD-10 code such as N18.32.',
};

function unitSuffix(value: unknown): string {
  const unit = (value as Record<string, unknown> | null)?.['unit'];
  return typeof unit === 'string' && unit ? ` ${unit}` : '';
}

/** First readable message for a control's errors, or null when there are none. */
export function firstErrorMessage(errors: ValidationErrors | null | undefined): string | null {
  if (!errors) return null;
  for (const [key, value] of Object.entries(errors)) {
    if (typeof value === 'string' && value) return value;
    const message = (value as { message?: unknown } | null)?.message;
    if (typeof message === 'string' && message) return message;
    const format = ERROR_MESSAGES[key];
    if (format) return format(value);
  }
  return 'This value is not valid.';
}
