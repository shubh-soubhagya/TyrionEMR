import { ApiError } from './api-error';
import { describeError } from './error-messages';

/** A failed save as a form shows it: per-field messages, one general line, and the id support can look up. */
export interface FormProblem {
  readonly errors: Readonly<Record<string, string>>;
  readonly general: string;
  readonly requestId: string | null;
  /** The code, for the program to branch on (never shown). */
  readonly code: string | null;
  readonly conflict: boolean;
}

/**
 * Maps an error from a save onto a form (HLD §15.2):
 * - 422 VALIDATION_ERROR: `details[].field` (dotted / indexed paths such as `results[1].unit`) onto the controls named in
 *   `fieldMap` (the API path -> the control name); a field the form does not have goes to the general line;
 * - 409 VERSION_CONFLICT: "This record was changed by someone else." and `conflict` (the form offers Reload);
 * - everything else: the server's message (with the wait for a 429) in the general line.
 */
export function toFormProblem(
  e: unknown,
  fieldMap: Readonly<Record<string, string>> = {},
): FormProblem {
  if (!(e instanceof ApiError)) {
    return {
      errors: {},
      general: 'Something went wrong. Please try again.',
      requestId: null,
      code: null,
      conflict: false,
    };
  }
  const view = describeError(e);
  if (e.code === 'VALIDATION_ERROR') {
    const errors: Record<string, string> = {};
    let unplaced = false;
    for (const [field, issue] of e.fieldIssues()) {
      // a list item is `diagnoses[1].icd10_code` or, from pydantic, `diagnoses.1.icd10_code`; both map to `diagnoses[]...`
      const control =
        fieldMap[field] ?? fieldMap[field.replace(/\[\d+]/g, '[]').replace(/\.\d+(?=\.|$)/g, '[]')];
      if (control) errors[control] = issue;
      else unplaced = true;
    }
    const placed = Object.keys(errors).length;
    return {
      errors,
      general: placed > 0 && !unplaced ? 'Fix the highlighted fields to continue.' : view.message,
      requestId: view.requestId,
      code: e.code,
      conflict: false,
    };
  }
  return {
    errors: {},
    general: view.message,
    requestId: view.requestId,
    code: e.code,
    conflict: e.code === 'VERSION_CONFLICT',
  };
}
