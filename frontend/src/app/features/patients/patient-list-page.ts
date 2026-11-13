// html:753-799
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  untracked,
} from '@angular/core';
import { Router } from '@angular/router';
import { Analysis, fullName, primaryOf, sexLabel } from '../../core/data/analysis';
import { DbService } from '../../core/data/db.service';
import { LabResult, Patient } from '../../core/data/models';
import { fmtDate } from '../../core/format';
import { ModalService } from '../../core/ui/modal.service';
import { EmrAvatar } from '../../shared/ui/avatar/avatar';
import { EmrCkdStageBadge } from '../../shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrSpark } from '../../shared/ui/charts/spark';
import { EmrIcon } from '../../shared/ui/icon/icon';
import { EmrLabFlag } from '../../shared/ui/lab-flag/lab-flag';
import { ListStateService, SortKey } from './list-state.service';

const PAGE = 8;

interface Row {
  p: Patient;
  a: Analysis;
  age: number;
  dx: string;
  visit: string | null;
  egfr: number | null;
  egfrRes: LabResult | undefined;
}

@Component({
  selector: 'emr-patient-list-page',
  imports: [EmrIcon, EmrAvatar, EmrCkdStageBadge, EmrLabFlag, EmrSpark],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-list-page.html',
})
export class PatientListPage {
  private readonly db = inject(DbService);
  private readonly router = inject(Router);
  protected readonly modals = inject(ModalService);
  protected readonly L = inject(ListStateService);

  /** `?q=` from the global search, bound by withComponentInputBinding. */
  readonly q = input<string>();

  protected readonly fullName = fullName;
  protected readonly sexLabel = sexLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly stageOptions = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'];

  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    effect(() => {
      const q = this.q();
      if (q !== undefined) {
        untracked(() => {
          this.L.q.set(q);
          this.L.page.set(1);
        });
      }
    });
  }

  protected readonly stats = computed(() => {
    const all = this.db.patients().map((p) => this.db.analysis(p.id));
    return {
      total: all.length,
      att: all.filter((a) => a.attention).length,
      crit: all.filter((a) => a.critical).length,
      rapid: all.filter((a) => a.rapid).length,
      drafts: this.db.raw().encounters.filter((e) => e.status === 'draft' && !e.deletedAt).length,
    };
  });

  protected readonly result = computed(() => {
    const q = this.L.q().trim().toLowerCase();
    const sex = this.L.sex();
    const stage = this.L.stage();
    const sort = this.L.sort();
    const dir = this.L.dir();
    const raw = this.db.raw();
    let rows: Row[] = this.db.patients().map((p) => {
      const a = this.db.analysis(p.id);
      const pr = primaryOf(raw, p.id);
      const le = this.db.encounters(p.id).find((e) => e.status === 'final');
      return {
        p,
        a,
        age: a.age,
        dx: pr ? pr.desc : '',
        visit: le ? le.date : null,
        egfr: a.latest.EGFR ? a.latest.EGFR.value : null,
        egfrRes: a.latest.EGFR,
      };
    });
    if (q)
      rows = rows.filter(
        (r) =>
          r.p.mrn.toLowerCase().includes(q) ||
          fullName(r.p).toLowerCase().includes(q) ||
          (r.p.last + ' ' + r.p.first).toLowerCase().includes(q),
      );
    if (sex) rows = rows.filter((r) => r.p.sex === sex);
    if (stage) rows = rows.filter((r) => (stage === 'none' ? !r.p.ckd : r.p.ckd === stage));
    if (this.L.attention()) rows = rows.filter((r) => r.a.attention);

    const keys: Record<SortKey, (r: Row) => string | number> = {
      name: (r) => (r.p.last + r.p.first).toLowerCase(),
      mrn: (r) => r.p.mrn,
      age: (r) => r.age,
      dx: (r) => r.dx.toLowerCase(),
      egfr: (r) => (r.egfr == null ? 1e9 : r.egfr),
      visit: (r) => (r.visit ? new Date(r.visit).getTime() : 0),
    };
    const key = keys[sort];
    rows.sort((a, b) => {
      const x = key(a);
      const y = key(b);
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / PAGE));
    const page = Math.min(this.L.page(), pages);
    return { items: rows.slice((page - 1) * PAGE, page * PAGE), total, pages, page };
  });

  protected readonly rangeText = computed(() => {
    const r = this.result();
    const from = (r.page - 1) * PAGE + 1;
    return `Showing ${from}–${from + r.items.length - 1} of ${r.total} patients`;
  });

  protected onSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.L.q.set(value);
    this.L.page.set(1);
    clearTimeout(this.searchTimer);
  }

  protected sortBy(key: SortKey): void {
    if (this.L.sort() === key) this.L.dir.update((d) => (d * -1) as 1 | -1);
    else {
      this.L.sort.set(key);
      this.L.dir.set(1);
    }
  }

  protected arrow(key: SortKey): string {
    return this.L.sort() === key ? (this.L.dir() > 0 ? ' ▲' : ' ▼') : '';
  }

  protected setSex(event: Event): void {
    this.L.sex.set((event.target as HTMLSelectElement).value);
    this.L.page.set(1);
  }

  protected setStage(event: Event): void {
    this.L.stage.set((event.target as HTMLSelectElement).value);
    this.L.page.set(1);
  }

  protected setAttention(event: Event): void {
    this.L.attention.set((event.target as HTMLInputElement).checked);
    this.L.page.set(1);
  }

  protected clearFilters(): void {
    this.L.reset();
    void this.router.navigate(['/patients']);
  }

  protected page(delta: number): void {
    this.L.page.set(this.result().page + delta);
  }

  protected open(p: Patient): void {
    void this.router.navigate(['/patients', p.id, 'overview']);
  }

  protected onRowKey(event: Event, p: Patient): void {
    event.preventDefault();
    this.open(p);
  }
}
