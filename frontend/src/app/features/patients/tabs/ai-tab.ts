// html:1198-1256. The summary is made by ai-svc: `POST /ai/patients/{id}/summary` starts a job, `GET /ai/summaries/{id}` is
// polled until it finishes, and the history is `GET /ai/patients/{id}/summaries`. The three provenance panels keep the
// facts, the rule findings and the AI narrative apart (HLD 10.9, CLAUDE.md section 7).
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { Subscription, switchMap } from 'rxjs';
import { ApiError } from '@core/api/api-error';
import type { StepDto, SummaryDto, TrendFactsDto } from '@core/api/dto/ai.dto';
import { describeError, type ErrorView } from '@core/api/error-messages';
import { remoteSignal } from '@core/api/remote-signal';
import { AI_DISCLAIMER } from '@core/clinical/ai-disclaimer';
import { fmtVal, LAB_TESTS, type TestCode } from '@core/clinical/lab-tests';
import { AiApi, TERMINAL, type DemoScenario } from '@core/data/ai.api';
import { cap, fmtDT, signed } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { environment } from '@env/environment';
import { EmrIcon } from '@shared/ui/icon/icon';
import { ToastService } from '@shared/ui/toast/toast.service';

/** Routes of the chart tabs a source can point to. */
const TAB_ROUTE: Readonly<Record<string, string>> = {
  overview: 'overview',
  conditions: 'conditions',
  meds: 'meds',
  medications: 'meds',
  encounters: 'encounters',
  labs: 'labs',
};

const GENERIC: ErrorView = { message: 'Something went wrong. Please try again.', requestId: null };

@Component({
  selector: 'emr-ai-tab',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ai-tab.html',
})
export class AiTab {
  private readonly api = inject(AiApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  private readonly destroyRef = inject(DestroyRef);
  readonly id = input.required<string>();

  protected readonly DISCLAIMER = AI_DISCLAIMER;
  protected readonly LAB = LAB_TESTS;
  protected readonly fmtDT = fmtDT;
  protected readonly signed = signed;
  protected readonly cap = cap;
  /** The demo options exist only in a non-production build (they send X-Mock-Scenario). */
  protected readonly isDev = !environment.production;
  protected readonly fmt = (code: string, v: number): string =>
    code in LAB_TESTS ? fmtVal(code as TestCode, v) : String(v);

  /** What the job is doing now: nothing, starting, or being polled. */
  protected readonly phase = signal<'idle' | 'starting' | 'running'>('idle');
  /** The job being watched; its `progress` drives the stepper. */
  protected readonly live = signal<SummaryDto | null>(null);
  /** The summary a run just finished with (any terminal status, including a failed one that is not in the history). */
  protected readonly finished = signal<SummaryDto | null>(null);
  /** A summary opened from the history. */
  private readonly opened = signal<SummaryDto | null>(null);
  /** The job could not even be started (the daily limit, the service is down). */
  protected readonly startError = signal<ErrorView | null>(null);
  protected readonly scenario = signal<DemoScenario>('normal');

  protected readonly history = remoteSignal<SummaryDto[]>(
    this.id,
    () => this.api.history(this.id()),
    () => false,
  );

  /** What the panels show: the opened one, else the one just finished, else the newest saved. */
  protected readonly shown = computed<SummaryDto | null>(() => {
    const o = this.opened();
    if (o) return o;
    const f = this.finished();
    if (f) return f;
    const h = this.history.state();
    return h.state === 'ok' ? (h.data[0] ?? null) : null;
  });

  protected readonly saved = computed(() => {
    const h = this.history.state();
    return h.state === 'ok' ? h.data : [];
  });

  protected readonly narrative = computed(() => this.shown()?.ai?.content ?? null);
  protected readonly sections = computed(() => {
    const n = this.narrative();
    return n
      ? [
          { h: 'Nephrology history', x: n.history_summary },
          { h: 'Conditions, medications and allergies', x: n.comorbidity_summary },
          { h: 'Creatinine and eGFR trends', x: n.trend_commentary },
          { h: 'Abnormal findings', x: n.abnormal_commentary },
        ]
      : [];
  });

  protected readonly steps = computed<readonly StepDto[]>(() => this.live()?.progress ?? []);

  /** "What the AI was given": loaded only when the person opens the fold. */
  protected readonly context = signal<{
    id: string;
    state: 'loading' | 'ok' | 'error';
    json: string;
  } | null>(null);

  protected readonly simOptions: readonly { v: DemoScenario; l: string }[] = [
    { v: 'normal', l: 'Normal run' },
    { v: 'invalid', l: 'LLM returns invalid output once (auto-repair)' },
    { v: 'timeout', l: 'LLM times out (partial result)' },
    { v: 'ratelimit', l: 'Provider rate limit, 429 (partial result)' },
    { v: 'upstream', l: 'lab-svc is down (request fails)' },
    { v: 'invalid_twice', l: 'LLM returns invalid output twice' },
    { v: 'unsafe_then_safe', l: 'Unsafe wording once, then safe' },
    { v: 'bad_refs', l: 'Sources that do not exist' },
    { v: 'tool_roundtrip', l: 'The AI looks up one more record' },
  ];

  private sub: Subscription | null = null;

  constructor() {
    // Leaving the page (a route change or destroy) stops the polling.
    this.destroyRef.onDestroy(() => this.sub?.unsubscribe());
  }

  protected stepClass(state: string): string {
    return state === 'running' ? 'active' : state === 'pending' ? '' : state;
  }

  protected stepIcon(st: string): 'check' | 'x' | 'alert' | null {
    return st === 'done' ? 'check' : st === 'failed' ? 'x' : st === 'warn' ? 'alert' : null;
  }

  protected trendDir(t: TrendFactsDto): string {
    return !t.n ? 'none' : (t.direction ?? 'insufficient_data');
  }

  protected trendRows(s: SummaryDto): { k: string; nm: string; t: TrendFactsDto }[] {
    const trends = s.facts?.trends ?? {};
    return [
      { k: 'EGFR', nm: 'eGFR', t: trends['EGFR'] ?? { n: 0 } },
      { k: 'CREAT', nm: 'Creatinine', t: trends['CREAT'] ?? { n: 0 } },
    ];
  }

  protected generate(force: boolean): void {
    if (this.phase() !== 'idle') return;
    this.sub?.unsubscribe();
    this.phase.set('starting');
    this.startError.set(null);
    this.opened.set(null);
    this.finished.set(null);
    this.live.set(null);
    // One stream: start the job, then poll it. Unsubscribing (a new run, or the page being left) stops both.
    this.sub = this.api
      .start(this.id(), { force, scenario: this.scenario() })
      .pipe(
        switchMap((start) => {
          this.phase.set('running');
          return this.api.watch(start.summary_id, start.poll_after_ms, TERMINAL.has(start.status));
        }),
      )
      .subscribe({
        next: (s) => {
          this.live.set(s);
          if (TERMINAL.has(s.status)) {
            this.finished.set(s);
            this.phase.set('idle');
            this.history.reload();
          }
        },
        error: (e: unknown) => this.fail(e),
      });
  }

  private fail(e: unknown): void {
    this.phase.set('idle');
    this.startError.set(e instanceof ApiError ? describeError(e) : GENERIC);
  }

  protected setScenario(event: Event): void {
    this.scenario.set((event.target as HTMLSelectElement).value as DemoScenario);
  }

  /** Opening a saved summary shows it as it was; nothing is regenerated. */
  protected open(s: SummaryDto): void {
    this.finished.set(null);
    this.opened.set(s);
    this.context.set(null);
  }

  protected uniq(refs: readonly string[]): string[] {
    return [...new Set(refs)];
  }

  protected refLabel(s: SummaryDto, ref: string): string {
    return s.sources?.[ref]?.label ?? ref;
  }

  /** A source chip opens the tab (or, for an encounter, its record) the server says it came from. */
  protected openRef(s: SummaryDto, ref: string): void {
    const src = s.sources?.[ref];
    if (!src) return;
    if (src.type === 'encounter' && src.target_id) {
      this.modals.open({
        kind: 'encounter-view',
        patientId: this.id(),
        encounterId: src.target_id,
        sub: 'Source record cited by the AI summary',
      });
      return;
    }
    const route = TAB_ROUTE[src.tab];
    if (route) void this.router.navigate(['/patients', this.id(), route]);
  }

  protected loadContext(s: SummaryDto, event: Event): void {
    if (!(event.target as HTMLDetailsElement).open) return;
    if (this.context()?.id === s.summary_id) return;
    this.context.set({ id: s.summary_id, state: 'loading', json: '' });
    this.api
      .get(s.summary_id, true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (d) =>
          this.context.set({
            id: s.summary_id,
            state: 'ok',
            json: JSON.stringify(d.context ?? null, null, 2),
          }),
        error: () => this.context.set({ id: s.summary_id, state: 'error', json: '' }),
      });
  }

  protected async copy(s: SummaryDto): Promise<void> {
    const o = s.ai?.content;
    if (!o) return;
    const text = [
      'AI-GENERATED, FOR CLINICIAN REVIEW ONLY',
      o.history_summary.text,
      o.comorbidity_summary.text,
      o.trend_commentary.text,
      o.abnormal_commentary.text,
      'Follow-up considerations:',
      ...o.follow_up_considerations.map((x) => '- ' + x.consideration),
      '',
      AI_DISCLAIMER,
    ].join('\n');
    try {
      await navigator.clipboard.writeText(text);
      this.toast.show('Narrative copied with its disclaimer.');
    } catch {
      this.toast.show('Copy is blocked by the browser. Select the text instead.', 'info');
    }
  }
}
