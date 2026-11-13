// html:753-799. The URL query string is the single source of truth: `?q=&sex=&stage=&attention=&sort=&dir=&page=`.
// Filtering, sorting and paging happen on the server (patient-svc `GET /patients`); the eGFR cells and sparklines come
// from one `GET /labs/summary` for the visible page; "Needs attention" comes from ai-svc.
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import {
  Observable,
  Subject,
  catchError,
  debounceTime,
  map,
  of,
  switchMap,
  combineLatest,
} from 'rxjs';
import { IDLE, LOADING, toRemote, type Remote } from '@core/api/remote';
import type { Flag } from '@core/clinical/lab-tests';
import { EncountersApi } from '@core/data/encounters.api';
import { InsightsApi } from '@core/data/insights.api';
import { LabsApi, type EgfrSummary } from '@core/data/labs.api';
import {
  PatientsApi,
  type ListSort,
  type PatientPage,
  type PatientQuery,
} from '@core/data/patients.api';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrAvatar } from '@shared/ui/avatar/avatar';
import { EmrSpark } from '@shared/ui/charts/spark';
import { EmrCkdStageBadge } from '@shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { EmrSkeleton } from '@shared/ui/skeleton/skeleton';
import { fullName, sexLabel } from '@shared/utils/labels';

const PAGE = 8;
const SORTS: readonly ListSort[] = ['name', 'mrn', 'age', 'dx', 'visit'];
const EMPTY_PAGE: PatientPage = { rows: [], total: 0, page: 1, pages: 1, size: PAGE };

@Component({
  selector: 'emr-patient-list-page',
  imports: [
    EmrIcon,
    EmrAvatar,
    EmrCkdStageBadge,
    EmrLabFlag,
    EmrSpark,
    EmrRemoteState,
    EmrSkeleton,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-list-page.html',
})
export class PatientListPage {
  private readonly patients = inject(PatientsApi);
  private readonly labs = inject(LabsApi);
  private readonly insights = inject(InsightsApi);
  private readonly encounters = inject(EncountersApi);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly modals = inject(ModalService);

  // The query string, bound to inputs by withComponentInputBinding.
  readonly q = input<string>();
  readonly sex = input<string>();
  readonly stage = input<string>();
  readonly attention = input<string>();
  readonly sort = input<string>();
  readonly dir = input<string>();
  readonly page = input<string>();

  protected readonly fullName = fullName;
  protected readonly sexLabel = sexLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly flag = (f: string): Flag => f as Flag;
  protected readonly stageOptions = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'];

  protected readonly sortKey = computed<ListSort>(() => {
    const s = this.sort() as ListSort | undefined;
    return s && SORTS.includes(s) ? s : 'name';
  });
  protected readonly sortDir = computed<'asc' | 'desc'>(() =>
    this.dir() === 'desc' ? 'desc' : 'asc',
  );
  protected readonly onlyAttention = computed(() => this.attention() === 'true');
  protected readonly pageNo = computed(() => Math.max(1, Number(this.page()) || 1));

  private readonly reloads = signal(0);
  private readonly search$ = new Subject<string>();

  /** ids of the patients who need attention, in attention order (ai-svc). Also drives the attention flag per row. */
  private readonly worklist = toSignal(
    toObservable(this.reloads).pipe(
      switchMap(() => this.insights.worklist().pipe(map((w) => w.items.map((i) => i.patient_id)))),
      catchError(() => of<string[] | null>(null)),
    ),
    { initialValue: null as string[] | null },
  );
  protected readonly attentionIds = computed(() => new Set(this.worklist() ?? []));

  private readonly query = computed<PatientQuery>(() => ({
    q: this.q() ?? '',
    sex: this.sex() ?? '',
    stage: this.stage() ?? '',
    sort: this.sortKey(),
    dir: this.sortDir(),
    page: this.pageNo(),
    size: PAGE,
  }));

  /** The visible page of patients. */
  protected readonly list = toSignal(
    combineLatest([
      toObservable(this.query),
      toObservable(this.onlyAttention),
      toObservable(this.reloads),
    ]).pipe(
      switchMap(([q, onlyAttention]) =>
        toRemote(this.fetch(q, onlyAttention), (p) => p.rows.length === 0),
      ),
    ),
    { initialValue: LOADING as Remote<PatientPage> },
  );

  /** eGFR value and sparkline for the visible ids: skeleton until it returns, per-row "No results". */
  protected readonly egfr = toSignal(
    toObservable(this.list).pipe(
      switchMap((l): Observable<Remote<ReadonlyMap<string, EgfrSummary>>> => {
        if (l.state !== 'ok') return of(IDLE);
        return toRemote(this.labs.summary(l.data.rows.map((r) => r.patient.id)), () => false);
      }),
    ),
    { initialValue: IDLE as Remote<ReadonlyMap<string, EgfrSummary>> },
  );

  /** KPI strip: total from the list, the rest from ai-svc and the drafts count from patient-svc (no new endpoint). */
  protected readonly kpis = toSignal(
    toObservable(this.reloads).pipe(
      switchMap(() =>
        toRemote(
          combineLatest([this.insights.dashboard(), this.encounters.drafts(1)]).pipe(
            map(([d, e]) => ({ ...d.kpis, drafts: e.total })),
          ),
          () => false,
        ),
      ),
    ),
    {
      initialValue: LOADING as Remote<{
        need_attention: number;
        critical_results: number;
        rapid_decline: number;
        drafts: number;
        patients: number;
      }>,
    },
  );

  protected readonly listTotal = computed(() => {
    const l = this.list();
    return l.state === 'ok' ? l.data.total : l.state === 'empty' ? 0 : null;
  });

  protected readonly rangeText = computed(() => {
    const l = this.list();
    if (l.state !== 'ok') return '';
    const from = (l.data.page - 1) * l.data.size + 1;
    return `Showing ${from}–${from + l.data.rows.length - 1} of ${l.data.total} patients`;
  });

  constructor() {
    // Search is debounced 300 ms and then written to the URL, which reloads the list.
    this.search$
      .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.navigate({ q: value.trim() || null, page: null }));
  }

  private fetch(q: PatientQuery, onlyAttention: boolean) {
    if (!onlyAttention) return this.patients.list(q);
    // "Needs attention": ids from ai-svc first, then the same list call with ids and the other filters.
    return this.insights.worklist().pipe(
      switchMap((w) => {
        const ids = w.items.map((i) => i.patient_id);
        return ids.length === 0 ? of(EMPTY_PAGE) : this.patients.list({ ...q, ids });
      }),
    );
  }

  protected onSearch(event: Event): void {
    this.search$.next((event.target as HTMLInputElement).value);
  }

  protected sortBy(key: ListSort): void {
    const same = this.sortKey() === key;
    this.navigate({
      sort: key,
      dir: same && this.sortDir() === 'asc' ? 'desc' : 'asc',
      page: null,
    });
  }

  protected arrow(key: ListSort): string {
    return this.sortKey() === key ? (this.sortDir() === 'asc' ? ' ▲' : ' ▼') : '';
  }

  protected ariaSort(key: ListSort): 'ascending' | 'descending' | 'none' {
    return this.sortKey() !== key ? 'none' : this.sortDir() === 'asc' ? 'ascending' : 'descending';
  }

  protected setSex(event: Event): void {
    this.navigate({ sex: (event.target as HTMLSelectElement).value || null, page: null });
  }

  protected setStage(event: Event): void {
    this.navigate({ stage: (event.target as HTMLSelectElement).value || null, page: null });
  }

  protected setAttention(event: Event): void {
    this.navigate({
      attention: (event.target as HTMLInputElement).checked ? 'true' : null,
      page: null,
    });
  }

  protected clearFilters(): void {
    void this.router.navigate(['/patients']);
  }

  protected go(delta: number): void {
    const next = this.pageNo() + delta;
    this.navigate({ page: next <= 1 ? null : String(next) });
  }

  protected retry(): void {
    this.reloads.update((n) => n + 1);
  }

  protected open(id: string): void {
    void this.router.navigate(['/patients', id, 'overview']);
  }

  protected onRowKey(event: Event, id: string): void {
    event.preventDefault();
    this.open(id);
  }

  private navigate(params: Record<string, string | null>): void {
    void this.router.navigate([], { queryParams: params, queryParamsHandling: 'merge' });
  }
}
