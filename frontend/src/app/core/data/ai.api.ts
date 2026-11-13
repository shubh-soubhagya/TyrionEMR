import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { EMPTY, Observable, expand, map, switchMap, timer } from 'rxjs';
import { environment } from '@env/environment';
import type { HistoryDto, StartDto, SummaryDto } from '../api/dto/ai.dto';
import { AI } from '../api/endpoints';
import { AuthService } from '../auth/auth.service';

/** Where a job ends; polling stops at the first of these. */
export const TERMINAL: ReadonlySet<string> = new Set(['completed', 'degraded', 'failed']);

/**
 * The dev-only demo scenarios of ai-svc's MockProvider (`X-Mock-Scenario`). The value maps the five options the screen
 * has always had to the server's names; the header is sent only by a non-production build.
 */
export type DemoScenario =
  | 'normal'
  | 'invalid'
  | 'timeout'
  | 'ratelimit'
  | 'upstream'
  | 'invalid_twice'
  | 'unsafe_then_safe'
  | 'bad_refs'
  | 'tool_roundtrip';

export const SCENARIO_HEADER_VALUE: Readonly<Record<DemoScenario, string>> = {
  normal: 'success',
  invalid: 'invalid_then_valid',
  timeout: 'timeout',
  ratelimit: 'rate_limited',
  upstream: 'upstream_down',
  invalid_twice: 'invalid_twice',
  unsafe_then_safe: 'unsafe_then_safe',
  bad_refs: 'bad_refs',
  tool_roundtrip: 'tool_roundtrip',
};

/** ai-svc summaries through the gateway: start a job, poll it, read one, list the history. */
@Injectable({ providedIn: 'root' })
export class AiApi {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  /**
   * Starts (or joins) a summary job. ai-svc rejects a token with less than 30 s left, so the token is refreshed first
   * when it has under a minute (HLD 10.3). Always answers 202.
   */
  start(
    patientId: string,
    opts: { force: boolean; scenario?: DemoScenario },
  ): Observable<StartDto> {
    let headers = new HttpHeaders();
    if (!environment.production && opts.scenario && opts.scenario !== 'normal') {
      headers = headers.set('X-Mock-Scenario', SCENARIO_HEADER_VALUE[opts.scenario]);
    }
    const params = opts.force ? new HttpParams().set('force', true) : new HttpParams();
    return this.auth
      .ensureFresh()
      .pipe(
        switchMap(() => this.http.post<StartDto>(AI.start(patientId), null, { headers, params })),
      );
  }

  get(summaryId: string, includeContext = false): Observable<SummaryDto> {
    const params = includeContext ? new HttpParams().set('include', 'context') : new HttpParams();
    return this.http.get<SummaryDto>(AI.summary(summaryId), { params });
  }

  /** Completed and degraded summaries of one patient, newest first. */
  history(patientId: string, page = 1, size = 10): Observable<SummaryDto[]> {
    return this.http
      .get<HistoryDto>(AI.history(patientId), { params: { page, size } })
      .pipe(map((d) => [...d.items]));
  }

  /**
   * Polls a job every `pollMs` until it reaches a terminal status, emitting every state (the stepper follows `progress`).
   * The first read happens immediately when the job is already finished (a cache hit), else after one interval.
   * Unsubscribing stops the polling: the page does that when the person leaves it.
   */
  watch(summaryId: string, pollMs: number, alreadyTerminal: boolean): Observable<SummaryDto> {
    const first = timer(alreadyTerminal ? 0 : pollMs).pipe(switchMap(() => this.get(summaryId)));
    return first.pipe(
      expand((s) =>
        TERMINAL.has(s.status) ? EMPTY : timer(pollMs).pipe(switchMap(() => this.get(summaryId))),
      ),
    );
  }
}
