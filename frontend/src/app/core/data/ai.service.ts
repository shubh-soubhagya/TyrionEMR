// Port of the HTML's simulated ai-svc (html:1069-1191). The narrative is built deterministically
// from the patient's own data; nothing is invented. Failure modes are chosen with `sim`.
import { Injectable, inject, signal } from '@angular/core';
import { EgfrCat, fmtVal, LAB_TESTS, TestCode, TrendStats } from '../clinical/lab-tests';
import { fmtDate, hash53, isoDate, signed, sleep, sid } from '../format';
import { allergiesOf, Analysis, condsOf, encsOf, medsOf, resultsOf, typeLabel } from './analysis';
import { AppError, DbService } from './db.service';
import { AiSummaryRecord, FollowUpItem, LabResult, Narrative, TrendLite } from './models';

export const AI_DISCLAIMER =
  'AI-generated summary for clinician review only. It may be incomplete or inaccurate. It is not a diagnosis or treatment recommendation. Verify against the patient record.';

export type SimMode = 'normal' | 'invalid' | 'timeout' | 'ratelimit' | 'upstream';
export type StepState = 'pending' | 'active' | 'done' | 'failed' | 'warn' | 'skipped';

export interface Step {
  t: string;
  d: string;
  st: StepState;
  ms: number | null;
  note: string;
  t0?: number;
}

export interface RunState {
  pid: string;
  status: 'running' | 'done' | 'error';
  steps: Step[];
  error?: { message: string; status?: number; code?: string };
}

const AI_STEPS: readonly (readonly [string, string])[] = [
  ['Opening the chart', 'Checking your access and the daily limit'],
  ['Reading the chart and lab results', 'Conditions, medications, encounters and every lab value'],
  ['Calculating trends and checking for gaps', 'Done by the system, not by the AI'],
  ['Preparing what the AI will see', 'Name and patient ID are removed'],
  ['Writing the summary', 'The AI drafts the narrative'],
  ['Checking the summary', 'Every source must exist in the record and the wording must be safe'],
  ['Saving', 'Kept separately from the patient record'],
];

const lite = (s: TrendStats): TrendLite =>
  s.n
    ? {
        n: s.n,
        first: s.first,
        last: s.last,
        pctChange: +s.pct.toFixed(1),
        slopePerYear: s.slope == null ? null : +s.slope.toFixed(2),
        direction: s.direction,
        rapidDecline: s.rapid,
      }
    : { n: 0 };

const labRef = (r: LabResult): string => `lab:${r.test}:${isoDate(r.collectedAt)}`;

class Degrade extends Error {
  constructor(
    readonly degrade: string,
    note: string,
  ) {
    super(note);
  }
}

@Injectable({ providedIn: 'root' })
export class AiService {
  private readonly db = inject(DbService);

  /** "Demo options" scenario (html `ui.ai.sim`). */
  readonly sim = signal<SimMode>('normal');
  readonly run = signal<RunState | null>(null);
  readonly openId = signal<string | null>(null);

  private buildContext(d: Analysis): unknown {
    const raw = this.db.raw();
    const p = d.p;
    return {
      patient: {
        age: d.age,
        sex: p.sex,
        establishedCkdStage: p.ckd || null,
        allergyStatus: p.allergyStatus,
        allergies: allergiesOf(raw, p.id).map((a) => ({
          allergen: a.allergen,
          severity: a.severity,
        })),
        pastMedicalHistory: p.pmh || null,
      },
      conditions: condsOf(raw, p.id).map((c) => ({
        id: 'cond:' + sid(c.id),
        icd10: c.icd10,
        description: c.desc,
        category: c.category,
        primary: c.isPrimary,
        status: c.status,
      })),
      activeMedications: medsOf(raw, p.id)
        .filter((m) => m.status === 'active')
        .map((m) => ({ id: 'med:' + sid(m.id), name: m.name, dose: m.dose })),
      recentEncounters: encsOf(raw, p.id)
        .slice(0, 2)
        .map((e) => ({
          id: 'enc:' + sid(e.id),
          date: isoDate(e.date),
          type: e.type,
          chiefComplaint: e.cc,
          assessment: e.assessment,
          status: e.status,
        })),
      latestLabs: Object.values(d.latest)
        .filter((r): r is LabResult => !!r)
        .map((r) => ({
          id: labRef(r),
          test: r.test,
          value: r.value,
          unit: r.unit,
          flag: r.flag,
          date: isoDate(r.collectedAt),
        })),
      trends: { EGFR: lite(d.trends.EGFR), CREAT: lite(d.trends.CREAT) },
      ruleFindings: d.gaps.map((g) => g.code),
      privacy: 'Name, patient ID, contact details and address are not sent to the model.',
    };
  }

  private buildNarrative(d: Analysis): Narrative {
    const raw = this.db.raw();
    const p = d.p;
    const conds = condsOf(raw, p.id);
    const encs = encsOf(raw, p.id);
    const meds = medsOf(raw, p.id).filter((m) => m.status === 'active');
    const al = allergiesOf(raw, p.id);
    const prim = conds.find((c) => c.isPrimary && c.status === 'active');
    const neph = conds.filter((c) => c.category === 'nephrology' && c.status === 'active');
    const como = conds.filter((c) => c.category === 'comorbidity' && c.status === 'active');
    const last = encs.find((e) => e.status === 'final') ?? encs[0];
    const sexW = p.sex === 'M' ? 'male' : p.sex === 'F' ? 'female' : 'patient';
    const nd: string[] = [];
    const hr: string[] = [];
    let h =
      `${d.age}-year-old ${sexW}` +
      (prim ? `, followed for ${prim.desc}.` : ' with no primary diagnosis documented.');
    if (prim) hr.push('cond:' + sid(prim.id));
    if (neph.length > 1) {
      h += ` Documented nephrology diagnoses: ${neph.map((c) => c.desc).join('; ')}.`;
      neph.forEach((c) => hr.push('cond:' + sid(c.id)));
    }
    h += p.pmh
      ? ` Past medical history on record: ${p.pmh}`
      : ' Past medical history is not documented.';
    if (!p.pmh) nd.push('past medical history');
    h +=
      ` ${encs.length} encounter${encs.length === 1 ? '' : 's'} on record` +
      (last
        ? `; the most recent (${fmtDate(last.date)}, ${typeLabel(last.type).toLowerCase()}) lists the chief complaint "${last.cc || 'not documented'}".`
        : '.');
    if (last) hr.push('enc:' + sid(last.id));

    const cr: string[] = [];
    let c = como.length
      ? `Active comorbidities documented: ${como.map((x) => x.desc).join('; ')}.`
      : 'No active comorbidities are documented.';
    como.forEach((x) => cr.push('cond:' + sid(x.id)));
    c += meds.length
      ? ` Current medications on record: ${meds.map((m) => m.name + ' ' + m.dose).join(', ')}.`
      : ' No current medications are documented.';
    meds.forEach((m) => cr.push('med:' + sid(m.id)));
    c +=
      p.allergyStatus === 'has'
        ? ` Documented allergies: ${al.map((a) => a.allergen + ' (' + a.severity + ')').join(', ')}.`
        : p.allergyStatus === 'nka'
          ? ' No known allergies are recorded.'
          : ' Allergy status is not recorded.';

    const tr: string[] = [];
    const trr: string[] = [];
    (
      [
        ['EGFR', 'eGFR'],
        ['CREAT', 'Serum creatinine'],
      ] as const
    ).forEach(([k, nm]) => {
      const s = d.trends[k];
      const u = LAB_TESTS[k].canon;
      if (!s.n) {
        tr.push(`No ${nm} results are on record.`);
        return;
      }
      const lastPt = s.pts[s.n - 1];
      const firstPt = s.pts[0];
      if (s.n < 3) {
        tr.push(
          `Only ${s.n} ${nm} result${s.n > 1 ? 's' : ''} on record (latest ${fmtVal(k, s.last)} ${u}), so a trend cannot be described.`,
        );
        if (lastPt) trr.push(`lab:${k}:${isoDate(lastPt.t)}`);
        return;
      }
      tr.push(
        `${nm} moved from ${fmtVal(k, s.first)} to ${fmtVal(k, s.last)} ${u} across ${s.n} results over about ${Math.max(1, Math.round(s.spanDays / 30.4))} months (${signed(s.slope ?? 0, k === 'EGFR' ? 1 : 2)} ${u} per year, ${s.direction}${s.rapid ? ', which meets the rapid-decline threshold of 5 per year' : ''}).`,
      );
      if (firstPt && lastPt)
        trr.push(`lab:${k}:${isoDate(firstPt.t)}`, `lab:${k}:${isoDate(lastPt.t)}`);
    });

    const ab = d.abnormal
      .slice()
      .sort(
        (a, b) =>
          Number(b.flag.indexOf('critical') === 0) - Number(a.flag.indexOf('critical') === 0),
      );
    const flagText: Record<string, string> = {
      low: 'low',
      high: 'high',
      critical_low: 'critical low',
      critical_high: 'critical high',
      normal: 'normal',
      unknown: 'no range',
    };
    const abT = ab.length
      ? `Among the latest results, ${ab.length} ${ab.length > 1 ? 'are' : 'is'} outside the reference range: ${ab.map((r) => `${LAB_TESTS[r.test].name} ${fmtVal(r.test, r.value)} ${r.unit} (${flagText[r.flag]}, ${fmtDate(r.collectedAt)})`).join('; ')}.`
      : Object.keys(d.latest).length
        ? 'None of the latest results is outside its reference range.'
        : 'No laboratory results are on record.';

    const fu: FollowUpItem[] = [];
    const add = (consideration: string, rationale: string, refs: string[]) =>
      fu.push({ consideration, rationale, source_refs: refs });
    if (d.rapid)
      add(
        'Consider reviewing how soon eGFR and creatinine should be repeated, given the documented rate of decline.',
        `The eGFR slope of ${signed(d.trends.EGFR.slope ?? 0, 1)} mL/min/1.73m² per year across ${d.trends.EGFR.n} results meets the rapid-decline threshold of 5 per year.`,
        trr.filter((r) => r.indexOf('lab:EGFR') === 0),
      );
    const kr = d.latest.K;
    if (kr && kr.flag !== 'normal')
      add(
        'Consider whether the potassium result warrants repeat testing or earlier review.',
        `Latest potassium is ${fmtVal('K', kr.value)} mmol/L (${flagText[kr.flag]}).`,
        [labRef(kr)],
      );
    const hb = d.latest.HB;
    if (hb && hb.flag !== 'normal')
      add(
        'Consider checking whether an anemia evaluation is already documented.',
        `Latest hemoglobin is ${fmtVal('HB', hb.value)} g/dL (${flagText[hb.flag]}).`,
        [labRef(hb)],
      );
    const ca = d.latest.CA;
    const ph = d.latest.PHOS;
    if ((ca && ca.flag !== 'normal') || (ph && ph.flag !== 'normal'))
      add(
        'Consider reviewing calcium and phosphorus together at the next visit.',
        `Calcium ${ca ? fmtVal('CA', ca.value) : 'not recorded'} mg/dL and phosphorus ${ph ? fmtVal('PHOS', ph.value) : 'not recorded'} mg/dL include a value outside the reference range.`,
        [ca ? labRef(ca) : '', ph ? labRef(ph) : ''].filter(Boolean),
      );
    if (d.ckd.uacrCat === 'A3' && d.ckd.uacrVal !== null && d.ckd.uacrDate)
      add(
        'Consider reviewing the albuminuria monitoring plan.',
        `The latest UACR of ${fmtVal('UACR', d.ckd.uacrVal)} mg/g falls in category A3.`,
        [`lab:UACR:${isoDate(d.ckd.uacrDate)}`],
      );
    d.gaps.forEach((g) => {
      if (g.code === 'CKD_STAGE_MISMATCH')
        add(
          `Consider reconciling the established CKD stage (${d.ckd.established}) with the latest eGFR category (${d.ckd.egfrCat}).`,
          g.message,
          g.refs,
        );
      if (g.code === 'ALLERGY_STATUS_UNKNOWN')
        add(
          'Consider confirming allergy status with the patient and recording it.',
          'Allergy status is currently recorded as unknown.',
          [],
        );
      if (g.code === 'NO_RECENT_LABS')
        add('Consider whether updated laboratory results are due.', g.message, g.refs);
      if (g.code === 'NO_LABS_RECORDED')
        add(
          'Consider whether baseline kidney function tests have been ordered.',
          'No laboratory results are on record.',
          [],
        );
      if (g.code === 'EGFR_CREATININE_DISCORDANT')
        add(
          'Consider verifying the reported eGFR against the creatinine value.',
          g.message,
          g.refs,
        );
      if (g.code === 'ACTIVE_MED_PAST_END_DATE')
        add('Consider checking whether the medication list is up to date.', g.message, g.refs);
    });
    if (last && last.followUp)
      add(
        'Consider confirming the follow-up date and plan from the latest encounter.',
        `The latest encounter lists a follow-up on ${fmtDate(last.followUp)}.`,
        ['enc:' + sid(last.id)],
      );
    const names: Record<string, string> = {
      ALLERGY_STATUS_UNKNOWN: 'allergy information',
      NO_MEDICATIONS_DOCUMENTED: 'current medications',
      NO_PRIMARY_DIAGNOSIS: 'primary diagnosis',
      NO_LABS_RECORDED: 'laboratory results',
      ENCOUNTER_NO_VITALS: 'vitals for some encounters',
      NO_ESTABLISHED_CKD_STAGE: 'established CKD stage',
    };
    d.gaps.forEach((g) => {
      const m = names[g.code];
      if (m && !nd.includes(m)) nd.push(m);
    });
    if (!p.fh) nd.push('family history');
    if (!p.sh) nd.push('social history');
    return {
      history_summary: { text: h, source_refs: hr },
      comorbidity_summary: { text: c, source_refs: cr },
      trend_commentary: { text: tr.join(' '), source_refs: trr },
      abnormal_commentary: { text: abT, source_refs: ab.map(labRef) },
      follow_up_considerations: fu.slice(0, 6),
      not_documented: nd,
    };
  }

  private refUniverse(id: string): Set<string> {
    const raw = this.db.raw();
    const s = new Set<string>();
    resultsOf(raw, id).forEach((r) => s.add(labRef(r)));
    encsOf(raw, id).forEach((e) => s.add('enc:' + sid(e.id)));
    condsOf(raw, id).forEach((c) => s.add('cond:' + sid(c.id)));
    medsOf(raw, id).forEach((m) => s.add('med:' + sid(m.id)));
    return s;
  }

  private validate(o: Narrative, id: string): { refsTotal: number; refsOk: number; lint: number } {
    const u = this.refUniverse(id);
    const refs = [
      ...o.history_summary.source_refs,
      ...o.comorbidity_summary.source_refs,
      ...o.trend_commentary.source_refs,
      ...o.abnormal_commentary.source_refs,
      ...o.follow_up_considerations.flatMap((f) => f.source_refs),
    ];
    const text = [
      o.history_summary.text,
      o.comorbidity_summary.text,
      o.trend_commentary.text,
      o.abnormal_commentary.text,
      ...o.follow_up_considerations.map((f) => f.consideration + ' ' + f.rationale),
    ].join(' ');
    const lint =
      text.match(
        /\b(prescribe|you have|start (?:the )?\w+ therapy|increase the dose|decrease the dose|diagnosis is)\b/gi,
      ) || [];
    return {
      refsTotal: refs.length,
      refsOk: refs.filter((r) => u.has(r)).length,
      lint: lint.length,
    };
  }

  private toolPlan(d: Analysis, pid: string): { name: string; argsShort: string }[] {
    const plan = [{ name: 'get_recent_encounters', argsShort: 'limit=3' }];
    if (d.trends.EGFR.n) plan.push({ name: 'get_lab_trend', argsShort: 'EGFR' });
    if (d.trends.CREAT.n) plan.push({ name: 'get_lab_trend', argsShort: 'CREAT' });
    if (d.latest.K && d.latest.K.flag !== 'normal')
      plan.push({ name: 'get_lab_history', argsShort: 'K' });
    plan.push({ name: 'get_medications_and_allergies', argsShort: '' });
    void pid;
    return plan;
  }

  private setStep(i: number, st: StepState, note?: string): void {
    const run = this.run();
    if (!run) return;
    const steps = run.steps.map((s) => ({ ...s }));
    const s = steps[i];
    if (!s) return;
    if (st === 'active') s.t0 = performance.now();
    else if (s.t0) {
      s.ms = Math.round(performance.now() - s.t0);
      s.t0 = undefined;
    }
    s.st = st;
    if (note != null) s.note = note;
    this.run.set({ ...run, steps });
  }

  async generate(pid: string, force: boolean): Promise<void> {
    if (this.run()?.status === 'running') return;
    const sim = this.sim();
    const cfg = this.db.config;
    this.run.set({
      pid,
      status: 'running',
      steps: AI_STEPS.map((x) => ({
        t: x[0],
        d: x[1],
        st: 'pending' as StepState,
        ms: null,
        note: '',
      })),
    });
    this.openId.set(null);
    const T0 = performance.now();
    let d: Analysis;
    let ctx: unknown;
    let hash: string;
    let out: Narrative | null = null;
    let status: 'completed' | 'degraded' = 'completed';
    let errCode: string | null = null;
    let attempts = 1;
    let v: AiSummaryRecord['validation'] = null;
    try {
      this.setStep(0, 'active');
      await sleep(260);
      const today = isoDate(Date.now());
      if (this.db.aiStore().filter((s) => isoDate(s.createdAt) === today).length >= cfg.dailyQuota)
        throw new AppError(
          429,
          'AI_QUOTA_EXCEEDED',
          'You have reached the daily limit for AI summaries.',
        );
      this.setStep(0, 'done', 'Ready');
      this.setStep(1, 'active');
      await Promise.all([sleep(220), sleep(280)]);
      if (sim === 'upstream')
        throw new AppError(503, 'UPSTREAM_UNAVAILABLE', 'Lab results could not be loaded in time.');
      this.setStep(1, 'done', 'Done');
      this.setStep(2, 'active');
      await sleep(320);
      d = this.db.analysis(pid);
      this.setStep(
        2,
        'done',
        `${d.gaps.length} rule findings, ${d.abnormal.length} abnormal latest results`,
      );
      this.setStep(3, 'active');
      await sleep(240);
      ctx = this.buildContext(d);
      hash = hash53(JSON.stringify(ctx) + 'mock' + 'v1').slice(0, 12);
      const cached = !force
        ? this.db
            .aiStore()
            .find((s) => s.patientId === pid && s.status === 'completed' && s.contextHash === hash)
        : undefined;
      let rec: AiSummaryRecord | undefined = cached;
      if (cached) {
        this.setStep(3, 'done', 'Same data as an earlier summary');
        [4, 5, 6].forEach((i) =>
          this.setStep(i, 'skipped', 'Not needed, reusing the saved summary'),
        );
      } else {
        this.setStep(3, 'done', 'New or changed data');
        this.setStep(4, 'active', 'Sending the chart summary to the AI');
        try {
          if (sim === 'ratelimit') {
            await sleep(520);
            throw new Degrade(
              'LLM_RATE_LIMITED',
              'The AI service is busy right now. Try again in a minute.',
            );
          }
          if (sim === 'timeout') {
            await sleep(650);
            this.setStep(4, 'active', 'No answer yet, trying again');
            await sleep(750);
            throw new Degrade(
              'LLM_TIMEOUT',
              'The AI service did not answer in time. Try again in a minute.',
            );
          }
          if (cfg.toolsEnabled) {
            for (const tc of this.toolPlan(d, pid).slice(0, cfg.maxToolIterations + 2)) {
              this.setStep(
                4,
                'active',
                `Looking up ${tc.name.replace(/^get_/, '').replace(/_/g, ' ')} ${tc.argsShort}`,
              );
              await sleep(130 + Math.random() * 120);
            }
          }
          await sleep(520);
          out = this.buildNarrative(d);
          this.setStep(4, 'done', 'Draft ready');
          this.setStep(5, 'active', 'Checking the format');
          await sleep(380);
          if (sim === 'invalid') {
            this.setStep(
              5,
              'active',
              'The first answer was incomplete. Asking the AI to correct it',
            );
            attempts = 2;
            await sleep(1000);
          }
          v = this.validate(out, pid);
          this.setStep(
            5,
            'done',
            `${v.refsOk} of ${v.refsTotal} sources found in the record${attempts > 1 ? ', corrected after one retry' : ''}`,
          );
        } catch (e) {
          if (!(e instanceof Degrade)) throw e;
          status = 'degraded';
          errCode = e.degrade;
          out = null;
          this.setStep(4, 'warn', e.message);
          this.setStep(5, 'skipped', 'Nothing to check');
        }
        this.setStep(6, 'active');
        await sleep(220);
      }
      if (!rec) {
        rec = {
          id: crypto.randomUUID(),
          patientId: pid,
          status,
          provider: 'mock',
          model: 'mock-deterministic-v1',
          contextHash: hash,
          contextSnapshot: ctx,
          output: out,
          facts: {
            ckd: {
              established: d.ckd.established,
              egfrCat: d.ckd.egfrCat as EgfrCat | null,
              uacrCat: d.ckd.uacrCat,
            },
            abnormal: d.abnormal.map((r) => ({
              test: r.test as TestCode,
              value: r.value,
              unit: r.unit,
              flag: r.flag,
              date: r.collectedAt,
            })),
            trends: { EGFR: lite(d.trends.EGFR), CREAT: lite(d.trends.CREAT) },
          },
          gaps: d.gaps,
          attempts,
          validation: v,
          errorCode: errCode,
          createdAt: new Date().toISOString(),
        };
        this.setStep(6, 'done', 'Saved');
        this.db.saveAiSummary(rec);
      }
      const cur = this.run();
      if (cur) this.run.set({ ...cur, status: 'done' });
      this.openId.set(rec.id);
      void T0;
    } catch (e) {
      const cur = this.run();
      if (cur) {
        const steps = cur.steps.map((s) => ({ ...s }));
        const i = steps.findIndex((s) => s.st === 'active');
        const msg = e instanceof Error ? e.message : 'Unknown error';
        if (i >= 0 && steps[i]) {
          (steps[i] as Step).st = 'failed';
          (steps[i] as Step).note = msg;
        }
        this.run.set({
          ...cur,
          steps,
          status: 'error',
          error: {
            message: msg,
            status: e instanceof AppError ? e.status : undefined,
            code: e instanceof AppError ? e.code : undefined,
          },
        });
      }
    }
  }
}
