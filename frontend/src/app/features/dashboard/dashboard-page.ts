// html:1277-1305
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { egfrLabel, fmtVal, LAB_TESTS } from '../../core/clinical/lab-tests';
import { Analysis, fullName, typeLabel } from '../../core/data/analysis';
import { DbService } from '../../core/data/db.service';
import { LabResult } from '../../core/data/models';
import { fmtDate, isoDate } from '../../core/format';
import { ModalService } from '../../core/ui/modal.service';
import { EmrIcon } from '../../shared/ui/icon/icon';
import { EmrLabFlag } from '../../shared/ui/lab-flag/lab-flag';
import { EmrTip } from '../../shared/ui/tooltip/tooltip';

const STAGE_COL: Record<string, string> = {
  G1: '#bfe3e6',
  G2: '#8ccdd3',
  G3a: '#52aeb8',
  G3b: '#2f8f9b',
  G4: '#0e6b75',
  G5: '#083f46',
};
const STAGES = ['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'] as const;

const isCrit = (r: LabResult): number => (r.flag.indexOf('critical') === 0 ? 1 : 0);

@Component({
  selector: 'emr-dashboard-page',
  imports: [RouterLink, EmrIcon, EmrLabFlag, EmrTip],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard-page.html',
})
export class DashboardPage {
  private readonly db = inject(DbService);
  protected readonly modals = inject(ModalService);

  protected readonly LAB = LAB_TESTS;
  protected readonly fmt = fmtVal;
  protected readonly stages = STAGES;
  protected readonly stageCol = STAGE_COL;
  protected readonly egfrLabel = egfrLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly fullName = fullName;
  protected readonly typeLabel = typeLabel;
  protected readonly name = (id: string): string => this.db.patientName(id);

  protected readonly greeting = (() => {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  })();
  protected readonly doctor = 'Dr. ' + (this.db.clinician.split(' ').pop() ?? '');
  protected readonly today = new Date().toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });

  protected readonly D = computed(() => {
    const all: Analysis[] = this.db.patients().map((p) => this.db.analysis(p.id));
    const today = isoDate(Date.now());
    const raw = this.db.raw();
    const live = new Set(all.map((a) => a.p.id));
    const drafts = raw.encounters
      .filter((e) => e.status === 'draft' && !e.deletedAt)
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    const follow = raw.encounters
      .filter((e) => !e.deletedAt && e.status === 'final' && e.followUp && isoDate(e.followUp) >= today && live.has(e.patientId))
      .sort((a, b) => new Date(a.followUp).getTime() - new Date(b.followUp).getTime());
    const abn: LabResult[] = [];
    all.forEach((a) =>
      Object.values(a.latest)
        .filter((r): r is LabResult => !!r && r.flag !== 'normal')
        .sort((x, y) => isCrit(y) - isCrit(x))
        .slice(0, 2)
        .forEach((r) => abn.push(r)),
    );
    abn.sort(
      (x, y) =>
        isCrit(y) - isCrit(x) ||
        new Date(y.collectedAt).getTime() - new Date(x.collectedAt).getTime(),
    );
    const att = all
      .filter((a) => a.attention)
      .map((a) => {
        const why: { tone: string; text: string }[] = [];
        a.abnormal
          .filter((r) => r.flag.indexOf('critical') === 0)
          .forEach((r) =>
            why.push({
              tone: 'danger',
              text: `Critical ${LAB_TESTS[r.test].name.toLowerCase()} ${fmtVal(r.test, r.value)} ${r.unit}`,
            }),
          );
        if (a.rapid)
          why.push({
            tone: 'danger',
            text: `eGFR falling ${Math.abs(a.trends.EGFR.slope ?? 0).toFixed(1)} per year`,
          });
        a.gaps
          .filter((g) => g.sev === 'high')
          .slice(0, 2)
          .forEach((g) => why.push({ tone: 'warn', text: g.message.replace(/\.$/, '') }));
        return { a, why, crit: a.critical ? 0 : a.rapid ? 1 : 2 };
      })
      .sort((x, y) => x.crit - y.crit);
    const dist: Record<string, number> = { G1: 0, G2: 0, G3a: 0, G3b: 0, G4: 0, G5: 0, none: 0 };
    all.forEach((a) => {
      const k = a.ckd.egfrCat ?? 'none';
      dist[k] = (dist[k] ?? 0) + 1;
    });
    return {
      all,
      att,
      drafts,
      follow,
      abn,
      dist,
      maxD: Math.max(1, ...Object.values(dist)),
      crit: all.filter((a) => a.critical).length,
      rapid: all.filter((a) => a.rapid).length,
    };
  });
}
