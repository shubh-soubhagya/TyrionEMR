import { describe, expect, it } from 'vitest';
import { friendlyIssue } from './issue-text';

describe('friendlyIssue', () => {
  it('words a failed ICD-10 pattern for the user', () => {
    expect(friendlyIssue('icd10_code', "String should match pattern '^[A-Z][0-9]...'")).toBe(
      'Enter a valid ICD-10 code, for example N18.3 or E11.22.',
    );
  });
  it('has a generic line for other patterns', () => {
    expect(friendlyIssue('name', "String should match pattern '^x$'")).toBe(
      'Check the format of this value.',
    );
  });
  it('rewords length messages', () => {
    expect(friendlyIssue('full_name', 'String should have at least 2 characters')).toBe(
      'Enter at least 2 characters.',
    );
    expect(friendlyIssue('notes', 'String should have at most 200 characters')).toBe(
      'Use at most 200 characters.',
    );
  });
  it('leaves other messages alone', () => {
    expect(friendlyIssue('x', 'Onset cannot be in the future.')).toBe(
      'Onset cannot be in the future.',
    );
  });
});
