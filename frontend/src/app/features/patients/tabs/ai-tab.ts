// html:1198-1256
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { fmtVal, LAB_TESTS, TestCode } from '../../../core/clinical/lab-tests';
import { AI_DISCLAIMER, AiService, SimMode } from '../../../core/data/ai.service';
import { DbService } from '../../../core/data/db.service';
import { AiSummaryRecord, TrendLite } from '../../../core/data/models';
import { cap, fmtDate, fmtDT, signed, sid } from '../../../core/format';
import { ModalService } from '../../../core/ui/modal.service';
import { EmrIcon } from '../../../shared/ui/icon/icon';
import { ToastService } from '../../../shared/ui/toast/toast.service';
import { typeLabel } from '../../../core/data/analysis';

@Component({
  selector: 'emr-ai-tab',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ai-tab.html',
})
export class AiTab {
  private readonly db = inject(DbService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly modals = inject(ModalService);
  protected readonly ai = inject(AiService);
  readonly id = input.required<string>();

  protected readonly DISCLAIMER = AI_DISCLAIMER;
  protected readonly LAB = LAB_TESTS;
  protected readonly fmtDT = fmtDT;
  protected readonly fmtVal = fmtVal;
  protected readonly signed = signed;
  protected readonly cap = cap;
  protected readonly Object = Object;

  protected readonly view = computed(() => {
    const pid = this.id();
    const hist = this.db.aiStore().filter((s) => s.patientId === pid);
    const run = this.ai.run();
    const R = run && run.pid === pid ? run : null;
    const running = R?.status === 'running';
    let sel = hist.find((s) => s.id === this.ai.openId());
    if (!sel && !running && !(R && R.status === 'error')) sel = hist[0];
    return { hist, R, running, sel };
  });

  protected readonly simOptions: readonly { v: SimMode; l: string }[] = [
    { v: 'normal', l: 'Normal run' },
    { v: 'invalid', l: 'LLM returns invalid output once (auto-repair)' },
    { v: 'timeout', l: 'LLM times out (partial result)' },
    { v: 'ratelimit', l: 'Provider rate limit, 429 (partial result)' },
    { v: 'upstream', l: 'lab-svc is down (request fails)' },
  ];

  protected stepIcon(st: string): 'check' | 'x' | 'alert' | null {
    return st === 'done' ? 'check' : st === 'failed' ? 'x' : st === 'warn' ? 'alert' : null;
  }

  protected trendDir(t: TrendLite): string {
    if (!t.n) return 'none';
    return t.direction ?? 'insufficient_data';
  }

  protected generate(force: boolean): void {
    void this.ai.generate(this.id(), force);
  }

  protected setSim(event: Event): void {
    this.ai.sim.set((event.target as HTMLSelectElement).value as SimMode);
  }

  protected open(s: AiSummaryRecord): void {
    this.ai.openId.set(s.id);
    this.ai.run.set(null);
  }

  protected uniq(refs: readonly string[]): string[] {
    return [...new Set(refs)];
  }

  protected refLabel(r: string): string {
    const [k, a, b] = r.split(':');
    const raw = this.db.raw();
    if (k === 'lab') return `${LAB_TESTS[a as TestCode]?.name ?? a}, ${fmtDate(b)}`;
    if (k === 'cond') return raw.conditions.find((x) => sid(x.id) === a)?.desc ?? 'Condition';
    if (k === 'med') return raw.meds.find((x) => sid(x.id) === a)?.name ?? 'Medication';
    if (k === 'enc') {
      const e = raw.encounters.find((x) => sid(x.id) === a);
      return e ? `Encounter, ${fmtDate(e.date)}` : 'Encounter';
    }
    return r;
  }

  protected openRef(ref: string): void {
    const [k, a] = ref.split(':');
    const id = this.id();
    if (k === 'lab') void this.router.navigate(['/patients', id, 'labs']);
    else if (k === 'cond') void this.router.navigate(['/patients', id, 'conditions']);
    else if (k === 'med') void this.router.navigate(['/patients', id, 'meds']);
    else if (k === 'enc') {
      const e = this.db.raw().encounters.find((x) => x.id.indexOf(a ?? '') === 0);
      if (e)
        this.modals.open({
          kind: 'encounter-view',
          encounterId: e.id,
          sub: 'Source record cited by the AI summary',
        });
    }
  }

  protected async copy(s: AiSummaryRecord): Promise<void> {
    const o = s.output;
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

  protected json(value: unknown): string {
    return JSON.stringify(value, null, 2);
  }

  protected typeLabel = typeLabel;
}
