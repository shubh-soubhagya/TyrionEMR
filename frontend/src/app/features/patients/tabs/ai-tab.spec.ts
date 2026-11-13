import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NEVER, Observable, of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@core/api/api-error';
import type { SummaryDto } from '@core/api/dto/ai.dto';
import { AI_DISCLAIMER } from '@core/clinical/ai-disclaimer';
import { AiApi } from '@core/data/ai.api';
import { AiTab } from './ai-tab';

const facts = {
  ckd: {
    established: 'G4',
    egfr_category: 'G4',
    uacr_category: 'A3',
    egfr_value: 24,
    mismatch: false,
  },
  trends: {
    EGFR: {
      n: 7,
      first: 34,
      last: 24,
      direction: 'worsening',
      pct_change: -29,
      slope_per_year: -6.6,
      rapid_decline: true,
    },
  },
  abnormal_results: [
    {
      ref: 'lab:1',
      flag: 'critical_high',
      name: 'Potassium',
      test: 'K',
      unit: 'mmol/L',
      value: 6.2,
      collected_at: '2026-11-01T00:00:00Z',
    },
  ],
};

const summary = (over: Partial<SummaryDto> = {}): SummaryDto => ({
  summary_id: 's1',
  patient_id: 'p1',
  status: 'completed',
  cached: false,
  cached_from: null,
  as_of: null,
  generated_at: '2026-11-13T10:00:00Z',
  progress: [],
  facts,
  gaps: {
    findings: [
      {
        code: 'NO_RECENT_LABS',
        severity: 'high',
        kind: 'missing',
        message: 'No labs in 6 months',
        evidence: [],
      },
    ],
    provenance: 'rule_engine',
    rules_version: 'r',
  },
  ai: null,
  sources: {},
  validation: null,
  error_code: null,
  ...over,
});

function create(fake: Partial<Record<keyof AiApi, unknown>>) {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      { provide: AiApi, useValue: { history: () => of([]), ...fake } },
    ],
  });
  const fixture = TestBed.createComponent(AiTab);
  fixture.componentRef.setInput('id', 'p1');
  fixture.detectChanges();
  return { fixture, el: fixture.nativeElement as HTMLElement };
}

const click = (el: HTMLElement, text: string) =>
  Array.from(el.querySelectorAll('button'))
    .find((b) => b.textContent?.includes(text))
    ?.click();

describe('AiTab', () => {
  it('says "No summary yet" and offers Generate when nothing is saved', async () => {
    const { fixture, el } = create({});
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.textContent).toContain('No summary yet');
  });

  it('shows the daily-limit message with the wait and the reference, not the code, when ai-svc answers 429', async () => {
    const err = new ApiError(
      429,
      'AI_QUOTA_EXCEEDED',
      'The daily summary limit was reached.',
      [],
      'req-42',
      600,
    );
    const { fixture, el } = create({ start: () => throwError(() => err), watch: () => NEVER });
    await fixture.whenStable();
    click(el, 'Generate summary');
    fixture.detectChanges();
    expect(el.textContent).toContain(
      'The daily summary limit was reached. Try again in 10 minutes.',
    );
    expect(el.textContent).toContain('req-42');
    expect(el.textContent).not.toContain('AI_QUOTA_EXCEEDED');
  });

  it('degraded: shows the facts and the rule findings, replaces the narrative with the reason, keeps the disclaimer', async () => {
    const degraded = summary({
      status: 'degraded',
      error_code: 'LLM_INVALID_OUTPUT',
      error_message: 'The AI response could not be verified, so it is not shown.',
    });
    const { fixture, el } = create({ history: () => of([degraded]) });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.textContent).toContain('Partial result');
    expect(el.textContent).toContain('Calculated from the chart');
    expect(el.textContent).toContain('Potassium');
    expect(el.textContent).toContain('No labs in 6 months');
    expect(el.textContent).toContain('The AI response could not be verified, so it is not shown.');
    expect(el.textContent).toContain(AI_DISCLAIMER);
    expect(el.querySelector('.ai-sec p')).toBeNull(); // no narrative paragraphs
  });

  it('failed: shows the reason, a Try again button, and nothing from the AI', async () => {
    const failed = summary({
      status: 'failed',
      facts: null,
      gaps: null,
      error_code: 'UPSTREAM_UNAVAILABLE',
      error_message: 'The patient record or lab results could not be loaded.',
    });
    const { fixture, el } = create({
      start: () =>
        of({
          summary_id: 's1',
          status: 'queued',
          deduplicated: false,
          poll_after_ms: 1000,
          progress: [],
        }),
      watch: () => of(failed),
    });
    await fixture.whenStable();
    click(el, 'Generate summary');
    fixture.detectChanges();
    expect(el.textContent).toContain('The summary could not be created.');
    expect(el.textContent).toContain('The patient record or lab results could not be loaded.');
    expect(
      Array.from(el.querySelectorAll('button')).some((b) => b.textContent?.includes('Try again')),
    ).toBe(true);
  });

  it('shows the cache note when nothing changed since the last summary', async () => {
    const { fixture, el } = create({ history: () => of([summary({ cached: true })]) });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.textContent).toContain(
      'Nothing has changed since the last summary, so the saved one is shown.',
    );
  });

  it('stops polling when the page is destroyed', async () => {
    const torn = vi.fn();
    const watching = new Observable<SummaryDto>(() => torn);
    const { fixture, el } = create({
      start: () =>
        of({
          summary_id: 's1',
          status: 'queued',
          deduplicated: false,
          poll_after_ms: 1000,
          progress: [],
        }),
      watch: () => watching,
    });
    await fixture.whenStable();
    click(el, 'Generate summary');
    fixture.detectChanges();
    expect(torn).not.toHaveBeenCalled();
    fixture.destroy();
    expect(torn).toHaveBeenCalled();
  });
});
