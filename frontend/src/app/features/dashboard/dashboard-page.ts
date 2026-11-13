// html:1277-1305. Every number on this page comes from a service: ai-svc `GET /insights/dashboard` and patient-svc
// `GET /encounters`. The three panels load in parallel and fail independently (HLD §3.2b).
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Observable, Subscription } from 'rxjs';
import type { DashboardDto } from '@core/api/dto/ai.dto';
import type { DashboardEncountersDto } from '@core/api/dto/patient.dto';
import { IDLE, toRemote, type Remote } from '@core/api/remote';
import { AuthService } from '@core/auth/auth.service';
import { egfrLabel, fmtVal, LAB_TESTS, type TestCode } from '@core/clinical/lab-tests';
import { EncountersApi } from '@core/data/encounters.api';
import { InsightsApi } from '@core/data/insights.api';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { EmrTip } from '@shared/ui/tooltip/tooltip';
import { greetingFor, typeLabel } from '@shared/utils/labels';
import type { Flag } from '@core/clinical/lab-tests';

const STAGE_COL: Record<string, string> = {
  G1: '#bfe3e6',
  G2: '#8ccdd3',
  G3a: '#52aeb8',
  G3b: '#2f8f9b',
  G4: '#0e6b75',
  G5: '#083f46',
};
const STAGES = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'] as const;

@Component({
  selector: 'emr-dashboard-page',
  imports: [RouterLink, EmrIcon, EmrLabFlag, EmrTip, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard-page.html',
})
export class DashboardPage {
  private readonly insights = inject(InsightsApi);
  private readonly encounters = inject(EncountersApi);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly modals = inject(ModalService);
  private readonly auth = inject(AuthService);

  protected readonly LAB = LAB_TESTS;
  protected readonly stages = STAGES;
  protected readonly stageCol = STAGE_COL;
  protected readonly egfrLabel = egfrLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly typeLabel = typeLabel;
  protected readonly flag = (f: string): Flag => f as Flag;
  protected readonly fmt = (test: string, v: number): string =>
    test in LAB_TESTS ? fmtVal(test as TestCode, v) : String(v);

  protected readonly greeting = greetingFor(new Date());
  protected readonly doctor = computed(() => this.auth.user()?.fullName ?? '');
  protected readonly today = new Date().toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });

  protected readonly dash = signal<Remote<DashboardDto>>(IDLE);
  protected readonly drafts = signal<Remote<DashboardEncountersDto>>(IDLE);
  protected readonly follow = signal<Remote<DashboardEncountersDto>>(IDLE);

  protected readonly kpisOf = computed(() => {
    const r = this.dash();
    return r.state === 'ok' ? r.data.kpis : null;
  });
  /** Total of draft encounters (a count the dashboard aggregate does not carry). */
  protected readonly draftTotal = computed(() => {
    const r = this.drafts();
    return r.state === 'ok' ? r.data.total : null;
  });

  /** Longest bar of the eGFR distribution, so the bars are drawn relative to it. */
  protected readonly maxDist = computed(() => {
    const r = this.dash();
    return r.state === 'ok' ? Math.max(1, ...Object.values(r.data.egfr_distribution)) : 1;
  });

  private subs: Subscription[] = [];

  constructor() {
    this.load(false);
    this.destroyRef.onDestroy(() => this.cancel());
  }

  /** Reloads all three panels. `fresh` makes ai-svc recompute instead of serving its 30 s snapshot. */
  protected refresh(): void {
    this.load(true);
  }

  protected retryDash(): void {
    this.run(this.dash, this.insights.dashboard(true));
  }
  protected retryDrafts(): void {
    this.run(this.drafts, this.encounters.drafts(10));
  }
  protected retryFollow(): void {
    this.run(this.follow, this.encounters.upcomingFollowUps(5));
  }

  private load(fresh: boolean): void {
    this.cancel();
    this.run(this.dash, this.insights.dashboard(fresh));
    this.run(this.drafts, this.encounters.drafts(10));
    this.run(this.follow, this.encounters.upcomingFollowUps(5));
  }

  private run<T>(target: ReturnType<typeof signal<Remote<T>>>, source: Observable<T>): void {
    this.subs.push(
      toRemote(source, () => false)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((state) => target.set(state)),
    );
  }

  private cancel(): void {
    this.subs.forEach((s) => s.unsubscribe());
    this.subs = [];
  }
}
