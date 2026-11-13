import { ApiError } from './api-error';

/** What a screen shows for an error: readable text, never the internal code, plus the id support can look up. */
export interface ErrorView {
  readonly message: string;
  readonly requestId: string | null;
}

/** "in 12 seconds" / "in 3 minutes" from a Retry-After value; empty when the server sent none. */
export function waitText(seconds: number | null): string {
  if (seconds === null) return '';
  if (seconds < 90)
    return ` Try again in ${Math.max(1, seconds)} second${seconds === 1 ? '' : 's'}.`;
  const minutes = Math.ceil(seconds / 60);
  return ` Try again in ${minutes} minutes.`;
}

/**
 * The single place that turns an ApiError into screen text (HLD §15.2). Rules:
 * 429 shows the wait, 502/503/504 say the service is unavailable, and an unavailable part of the system says so.
 * Everything else uses the server's own message, which is already written for people.
 */
export function describeError(e: ApiError): ErrorView {
  const base = ((): string => {
    switch (e.code) {
      case 'RATE_LIMITED':
      case 'ACCOUNT_LOCKED':
      case 'AI_QUOTA_EXCEEDED':
        return e.message + waitText(e.retryAfterS);
      case 'UPSTREAM_NOT_DEPLOYED':
        return 'This part of the system is not available yet.';
      case 'VERSION_CONFLICT':
        return 'This record was changed by someone else.';
      case 'NETWORK_ERROR':
        return e.message;
      default:
        if (e.status === 502 || e.status === 503 || e.status === 504) {
          return 'This part of the system is temporarily unavailable. Try again in a moment.';
        }
        return e.message;
    }
  })();
  return { message: base, requestId: e.requestId };
}

/** True for the codes that mean "load this panel again" (the panel shows a Retry button). */
export function isRetryable(e: ApiError): boolean {
  return e.status === 0 || e.status === 502 || e.status === 503 || e.status === 504;
}
