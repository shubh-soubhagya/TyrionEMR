import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { firstValueFrom, of, throwError } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { ApiError, toApiError } from './api-error';
import { dataOf, toRemote, type Remote } from './remote';

const envelope = (over: Record<string, unknown> = {}) => ({
  error: {
    code: 'VALIDATION_ERROR',
    message: 'Invalid input.',
    details: [],
    request_id: 'req-abc123',
    ...over,
  },
});

const http = (status: number, error: unknown, headers: Record<string, string> = {}) =>
  new HttpErrorResponse({ status, error, headers: new HttpHeaders(headers), url: '/api/x' });

describe('toApiError', () => {
  it('reads the platform envelope', () => {
    const e = toApiError(
      http(
        422,
        envelope({
          details: [{ field: 'results[1].unit', issue: 'Unknown unit' }, { code: 'TOO_SHORT' }],
        }),
      ),
    );
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Invalid input.',
      requestId: 'req-abc123',
    });
    expect(e.fieldIssues().get('results[1].unit')).toBe('Unknown unit');
    expect(e.hasDetailCode('TOO_SHORT')).toBe(true);
    expect(e.retryAfterS).toBeNull();
  });

  it('reads Retry-After in seconds', () => {
    const e = toApiError(http(429, envelope({ code: 'RATE_LIMITED' }), { 'Retry-After': '17' }));
    expect(e.retryAfterS).toBe(17);
  });

  it('survives a non-JSON body (a proxy error page) with a generic message and no request id', () => {
    const e = toApiError(http(502, '<html>Bad gateway</html>'));
    expect(e).toMatchObject({ status: 502, code: 'HTTP_502', requestId: null });
    expect(e.message).not.toContain('html');
  });

  it('survives a null body and malformed details', () => {
    expect(toApiError(http(500, null)).code).toBe('HTTP_500');
    expect(toApiError(http(409, envelope({ details: 'nope' }))).details).toEqual([]);
  });

  it('maps status 0 to NETWORK_ERROR', () => {
    const e = toApiError(http(0, new ProgressEvent('error')));
    expect(e).toMatchObject({ status: 0, code: 'NETWORK_ERROR', requestId: null });
  });
});

describe('toRemote', () => {
  const collect = async (
    src: ReturnType<typeof toRemote<number[]>>,
  ): Promise<Remote<number[]>[]> => {
    const out: Remote<number[]>[] = [];
    await new Promise<void>((resolve) =>
      src.subscribe({ next: (v) => out.push(v), complete: resolve }),
    );
    return out;
  };

  it('goes loading -> ok', async () => {
    const states = await collect(toRemote(of([1, 2])));
    expect(states.map((s) => s.state)).toEqual(['loading', 'ok']);
    expect(dataOf(states[1] as Remote<number[]>)).toEqual([1, 2]);
  });

  it('goes loading -> empty for an empty list and for null', async () => {
    expect((await collect(toRemote(of([])))).map((s) => s.state)).toEqual(['loading', 'empty']);
    const nul = await firstValueFrom(toRemote(of(null as unknown as number[])).pipe());
    expect(nul.state).toBe('loading');
  });

  it('turns an ApiError into an error state and never errors the stream', async () => {
    const err = new ApiError(503, 'UPSTREAM_UNAVAILABLE', 'down', [], 'req-1', null);
    const states = await collect(toRemote(throwError(() => err)));
    expect(states.map((s) => s.state)).toEqual(['loading', 'error']);
    expect(states[1]).toMatchObject({ state: 'error', error: err });
  });

  it('wraps a non-ApiError (a bug) in a generic ApiError', async () => {
    const states = await collect(toRemote(throwError(() => new TypeError('boom'))));
    const last = states[1];
    expect(last?.state).toBe('error');
    if (last?.state === 'error') expect(last.error.code).toBe('CLIENT_ERROR');
  });

  it('honours a custom emptiness test', async () => {
    const states = await collect(toRemote(of([1]), (v) => v.length < 2));
    expect(states.map((s) => s.state)).toEqual(['loading', 'empty']);
  });
});
