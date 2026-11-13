import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { existsSync, readFileSync } from 'node:fs';
import { firstValueFrom, of, toArray } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../api/endpoints';
import { AI_DISCLAIMER } from '../clinical/ai-disclaimer';
import { AuthService } from '../auth/auth.service';
import { AiApi } from './ai.api';

const START = `${API_BASE}/ai/patients/p1/summary`;
const summary = (status: string, over: Record<string, unknown> = {}) => ({
  summary_id: 's1',
  patient_id: 'p1',
  status,
  cached: false,
  cached_from: null,
  as_of: null,
  generated_at: null,
  progress: [],
  facts: null,
  gaps: null,
  ai: null,
  sources: null,
  validation: null,
  error_code: null,
  ...over,
});

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return {
    api: TestBed.inject(AiApi),
    ctrl: TestBed.inject(HttpTestingController),
    auth: TestBed.inject(AuthService),
  };
}

afterEach(() => vi.useRealTimers());

describe('the disclaimer', () => {
  it('equals the one ai-svc sends in its recorded example (decisions D2), and the file is mounted', () => {
    const path = '/ai-examples/summary-completed.json';
    expect(existsSync(path), `${path} is missing: mount ../ai-svc/docs/api/examples`).toBe(true);
    const example = JSON.parse(readFileSync(path, 'utf-8')) as { disclaimer: string };
    expect(AI_DISCLAIMER).toBe(example.disclaimer);
  });
});

describe('AiApi.start', () => {
  it('refreshes the token first when it is about to expire, then posts', async () => {
    const { api, ctrl, auth } = setup();
    const refresh = vi.spyOn(auth, 'ensureFresh').mockReturnValue(of(undefined));
    const p = firstValueFrom(api.start('p1', { force: false }));
    expect(refresh).toHaveBeenCalled();
    ctrl
      .expectOne((r) => r.url === START)
      .flush({
        summary_id: 's1',
        status: 'queued',
        deduplicated: false,
        poll_after_ms: 1000,
        progress: [],
      });
    expect((await p).summary_id).toBe('s1');
  });

  it('sends force=true only for a regenerate and the demo scenario only outside production', async () => {
    const { api, ctrl, auth } = setup();
    vi.spyOn(auth, 'ensureFresh').mockReturnValue(of(undefined));
    void firstValueFrom(api.start('p1', { force: true, scenario: 'invalid' }));
    const req = ctrl.expectOne((r) => r.url === START);
    expect(req.request.params.get('force')).toBe('true');
    expect(req.request.headers.get('X-Mock-Scenario')).toBe('invalid_then_valid'); // development build
    req.flush({
      summary_id: 's',
      status: 'queued',
      deduplicated: false,
      poll_after_ms: 1000,
      progress: [],
    });

    void firstValueFrom(api.start('p1', { force: false, scenario: 'normal' }));
    const normal = ctrl.expectOne((r) => r.url === START);
    expect(normal.request.params.has('force')).toBe(false);
    expect(normal.request.headers.has('X-Mock-Scenario')).toBe(false); // the normal run sends nothing
    normal.flush({
      summary_id: 's',
      status: 'queued',
      deduplicated: false,
      poll_after_ms: 1000,
      progress: [],
    });
  });
});

describe('AiApi.watch', () => {
  it('polls every interval until a terminal status, then stops', async () => {
    vi.useFakeTimers();
    const { api, ctrl } = setup();
    const done = firstValueFrom(api.watch('s1', 1000, false).pipe(toArray()));

    await vi.advanceTimersByTimeAsync(1000);
    ctrl.expectOne(`${API_BASE}/ai/summaries/s1`).flush(summary('running'));
    await vi.advanceTimersByTimeAsync(1000);
    ctrl.expectOne(`${API_BASE}/ai/summaries/s1`).flush(summary('running'));
    await vi.advanceTimersByTimeAsync(1000);
    ctrl.expectOne(`${API_BASE}/ai/summaries/s1`).flush(summary('completed'));
    expect((await done).map((s) => s.status)).toEqual(['running', 'running', 'completed']);
    await vi.advanceTimersByTimeAsync(5000);
    ctrl.expectNone(`${API_BASE}/ai/summaries/s1`); // no request after the terminal status
  });

  it('reads at once when the job already finished (a cache hit)', async () => {
    vi.useFakeTimers();
    const { api, ctrl } = setup();
    const p = firstValueFrom(api.watch('s1', 1000, true));
    await vi.advanceTimersByTimeAsync(0);
    ctrl.expectOne(`${API_BASE}/ai/summaries/s1`).flush(summary('completed', { cached: true }));
    expect((await p).cached).toBe(true);
  });

  it('stops polling when the subscriber leaves (the page was left)', async () => {
    vi.useFakeTimers();
    const { api, ctrl } = setup();
    const sub = api.watch('s1', 1000, false).subscribe();
    await vi.advanceTimersByTimeAsync(1000);
    ctrl.expectOne(`${API_BASE}/ai/summaries/s1`).flush(summary('running'));
    sub.unsubscribe();
    await vi.advanceTimersByTimeAsync(10_000);
    ctrl.expectNone(`${API_BASE}/ai/summaries/s1`);
  });

  it('asks for the context only when told to', () => {
    const { api, ctrl } = setup();
    void firstValueFrom(api.get('s1', true));
    const req = ctrl.expectOne((r) => r.url === `${API_BASE}/ai/summaries/s1`);
    expect(req.request.params.get('include')).toBe('context');
    req.flush(summary('completed'));
  });
});
