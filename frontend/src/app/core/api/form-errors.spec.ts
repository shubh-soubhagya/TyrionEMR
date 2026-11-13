import { describe, expect, it } from 'vitest';
import { ApiError } from './api-error';
import { describeError, isRetryable, waitText } from './error-messages';
import { toFormProblem } from './form-errors';

const err = (status: number, code: string, over: Partial<ApiError> = {}, details: unknown[] = []) =>
  Object.assign(
    new ApiError(status, code, 'Server message.', details as never, 'req-9', null),
    over,
  );

describe('toFormProblem', () => {
  it('puts a 422 field on its control, including an indexed path', () => {
    const p = toFormProblem(
      err(422, 'VALIDATION_ERROR', {}, [
        { field: 'results[1].unit', issue: 'Unknown unit' },
        { field: 'vitals.systolic_bp', issue: 'Too high' },
      ]),
      { 'results[].unit': 'unit', 'vitals.systolic_bp': 'sys' },
    );
    expect(p.errors).toEqual({ unit: 'Unknown unit', sys: 'Too high' });
    expect(p.general).toBe('Fix the highlighted fields to continue.');
    expect(p.requestId).toBe('req-9');
  });

  it('sends a field the form does not have to the general line', () => {
    const p = toFormProblem(
      err(422, 'VALIDATION_ERROR', {}, [{ field: 'surprise', issue: 'x' }]),
      {},
    );
    expect(p.errors).toEqual({});
    expect(p.general).toBe('Server message.');
  });

  it('marks a 409 VERSION_CONFLICT so the form offers Reload', () => {
    const p = toFormProblem(err(409, 'VERSION_CONFLICT'));
    expect(p.conflict).toBe(true);
    expect(p.general).toBe('This record was changed by someone else.');
  });

  it('is generic for something that is not an ApiError', () => {
    expect(toFormProblem(new TypeError('boom')).general).toBe(
      'Something went wrong. Please try again.',
    );
  });
});

describe('describeError', () => {
  it('adds the wait to a 429 and never shows the code', () => {
    const v = describeError(err(429, 'RATE_LIMITED', { retryAfterS: 30 }));
    expect(v.message).toBe('Server message. Try again in 30 seconds.');
    expect(v.message).not.toContain('RATE_LIMITED');
  });

  it('says minutes for a long lockout', () => {
    expect(waitText(900)).toBe(' Try again in 15 minutes.');
    expect(waitText(null)).toBe('');
    expect(waitText(1)).toBe(' Try again in 1 second.');
  });

  it('describes an unavailable service and a part that is not deployed', () => {
    expect(describeError(err(503, 'UPSTREAM_UNAVAILABLE')).message).toContain(
      'temporarily unavailable',
    );
    expect(describeError(err(503, 'UPSTREAM_NOT_DEPLOYED')).message).toBe(
      'This part of the system is not available yet.',
    );
  });

  it('retries only what a retry can fix', () => {
    expect(isRetryable(err(0, 'NETWORK_ERROR'))).toBe(true);
    expect(isRetryable(err(504, 'UPSTREAM_TIMEOUT'))).toBe(true);
    expect(isRetryable(err(404, 'NOT_FOUND'))).toBe(false);
    expect(isRetryable(err(422, 'VALIDATION_ERROR'))).toBe(false);
  });
});
