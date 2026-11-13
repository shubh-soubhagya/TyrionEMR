import { Observable, catchError, map, of, startWith } from 'rxjs';
import { ApiError } from './api-error';

/** Remote data as one discriminated union: never a tangle of isLoading / hasError / data flags. */
export type Remote<T> =
  | { readonly state: 'idle' }
  | { readonly state: 'loading' }
  | { readonly state: 'ok'; readonly data: T }
  | { readonly state: 'empty' }
  | { readonly state: 'error'; readonly error: ApiError };

export const IDLE: Remote<never> = { state: 'idle' };
export const LOADING: Remote<never> = { state: 'loading' };

export function isEmptyValue(v: unknown): boolean {
  return v === null || v === undefined || (Array.isArray(v) && v.length === 0);
}

/** Anything thrown that is not an ApiError (a bug) becomes a generic one, so the UI still has an error to show. */
export function asApiError(e: unknown): ApiError {
  return e instanceof ApiError
    ? e
    : new ApiError(0, 'CLIENT_ERROR', 'Something went wrong. Please try again.', [], null, null);
}

/**
 * Maps a request to a stream of states: `loading` first, then `ok` (or `empty` when `isEmpty` says so), or `error`.
 * The stream never errors, so one failing panel cannot break the screen around it.
 */
export function toRemote<T>(
  source: Observable<T>,
  isEmpty: (v: T) => boolean = isEmptyValue,
): Observable<Remote<T>> {
  return source.pipe(
    map((data): Remote<T> => (isEmpty(data) ? { state: 'empty' } : { state: 'ok', data })),
    catchError((e: unknown): Observable<Remote<T>> => of({ state: 'error', error: asApiError(e) })),
    startWith<Remote<T>>(LOADING),
  );
}

export function dataOf<T>(r: Remote<T>): T | null {
  return r.state === 'ok' ? r.data : null;
}
