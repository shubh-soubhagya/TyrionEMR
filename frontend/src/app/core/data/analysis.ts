// Port of the HTML's repositories + analysis (html:559-616). Pure functions over a Db.
import {
  ckdEpi,
  classifyEgfr,
  classifyUacr,
  EgfrCat,
  fmtVal,
  LAB_TESTS,
  TestCode,
  trendStats,
  TrendStats,
  UacrCat,
} from '../clinical/lab-tests';
import { ageOf, DAY, fmtDate, isoDate, sid } from '../format';
import {
  Allergy,
  Condition,
  Db,
  Encounter,
  GapFinding,
  LabResult,
  Med,
  Patient,
} from './models';

export const patientOf = (db: Db, id: string): Patient | undefined =>
  db.patients.find((x) => x.id === id && !x.deletedAt);
export const condsOf = (db: Db, id: string): Condition[] =>
  db.conditions.filter((c) => c.patientId === id && !c.deletedAt);
export const medsOf = (db: Db, id: string): Med[] => db.meds.filter((m) => m.patientId === id);
export const allergiesOf = (db: Db, id: string): Allergy[] =>
  db.allergies.filter((a) => a.patientId === id);
export const encsOf = (db: Db, id: string): Encounter[] =>
  db.encounters
    .filter((e) => e.patientId === id && !e.deletedAt)
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
export const resultsOf = (db: Db, id: string): LabResult[] =>
  db.labResults
    .filter((r) => r.patientId === id)
    .sort((a, b) => new Date(b.collectedAt).getTime() - new Date(a.collectedAt).getTime());
export const fullName = (p: Patient): string => p.first + ' ' + p.last;
export const sexLabel = (s: string): string => ({ M: 'Male', F: 'Female', O: 'Other' })[s as 'M'] ?? s;
export const typeLabel = (t: string): string =>
  ({ new: 'New visit', follow_up: 'Follow-up', emergency: 'Emergency' })[t as 'new'] ?? t;
export const primaryOf = (db: Db, id: string): Condition | undefined =>
  condsOf(db, id).find((c) => c.isPrimary && c.status === 'active');
export const hasVitals = (e: Encounter): boolean =>
  !!e.vitals && Object.values(e.vitals).some((v) => v != null);

export function latestByTest(db: Db, id: string): Partial<Record<TestCode, LabResult>> {
  const o: Partial<Record<TestCode, LabResult>> = {};
  resultsOf(db, id).forEach((r) => {
    if (!o[r.test]) o[r.test] = r;
  });
  return o;
}

export interface CkdInfo {
  established: EgfrCat | null;
  egfrCat: EgfrCat | null;
  egfrVal: number | null;
  egfrDate: string | null;
  uacrCat: UacrCat | null;
  uacrVal: number | null;
  uacrDate: string | null;
  mismatch: boolean;
}

export interface Analysis {
  p: Patient;
  age: number;
  latest: Partial<Record<TestCode, LabResult>>;
  res: LabResult[];
  trends: { CREAT: TrendStats; EGFR: TrendStats };
  ckd: CkdInfo;
  gaps: GapFinding[];
  abnormal: LabResult[];
  critical: boolean;
  rapid: boolean;
  attention: boolean;
}

export function gapEngine(
  db: Db,
  p: Patient,
  latest: Partial<Record<TestCode, LabResult>>,
  res: LabResult[],
  trends: { CREAT: TrendStats; EGFR: TrendStats },
  ckd: CkdInfo,
): GapFinding[] {
  const g: GapFinding[] = [];
  const add = (
    code: string,
    sev: GapFinding['sev'],
    kind: GapFinding['kind'],
    message: string,
    refs: string[] = [],
  ) => g.push({ code, sev, kind, message, refs });
  const conds = condsOf(db, p.id);
  const encs = encsOf(db, p.id);
  const meds = medsOf(db, p.id);
  const now = Date.now();

  if (p.allergyStatus === 'unknown')
    add('ALLERGY_STATUS_UNKNOWN', 'medium', 'missing', 'Allergy status has not been recorded. "Unknown" is not the same as "no known allergies".');
  if (!conds.some((c) => c.isPrimary && c.status === 'active'))
    add('NO_PRIMARY_DIAGNOSIS', 'medium', 'missing', 'No active primary diagnosis is recorded.');
  if (!meds.length)
    add('NO_MEDICATIONS_DOCUMENTED', 'low', 'missing', 'No medications are documented, so "takes none" cannot be told apart from "not recorded".');
  if (!res.length) {
    add('NO_LABS_RECORDED', 'high', 'missing', 'No laboratory results are on record for this patient.');
  } else {
    const first = res[0] as LabResult;
    const days = Math.round((now - new Date(first.collectedAt).getTime()) / DAY);
    if (days > 180)
      add('NO_RECENT_LABS', 'medium', 'missing', `The most recent lab result is ${days} days old (threshold 180 days).`, [
        'lab:' + first.test + ':' + isoDate(first.collectedAt),
      ]);
    (['CREAT', 'EGFR', 'UACR'] as TestCode[]).forEach((t) => {
      if (!latest[t])
        add('NO_LABS_FOR_TEST', 'low', 'missing', `${LAB_TESTS[t].name} has never been recorded.`);
    });
    if (trends.EGFR.n > 0 && trends.EGFR.n < 3)
      add('INSUFFICIENT_TREND_DATA', 'low', 'missing', `Only ${trends.EGFR.n} eGFR result${trends.EGFR.n > 1 ? 's' : ''} on record; a trend needs at least 3.`);
  }
  encs
    .filter((e) => e.status === 'final')
    .forEach((e) => {
      if (!hasVitals(e))
        add('ENCOUNTER_NO_VITALS', 'low', 'missing', `Final encounter on ${fmtDate(e.date)} has no vitals recorded.`, ['enc:' + sid(e.id)]);
      if (!e.assessment || !e.plan)
        add('ENCOUNTER_NO_ASSESSMENT', 'medium', 'missing', `Final encounter on ${fmtDate(e.date)} is missing an assessment or plan.`, ['enc:' + sid(e.id)]);
    });
  const low = res
    .filter((r) => r.test === 'EGFR' && r.value < 60)
    .sort((a, b) => new Date(a.collectedAt).getTime() - new Date(b.collectedAt).getTime());
  const egfr = latest.EGFR;
  const lowFirst = low[0];
  const lowLast = low[low.length - 1];
  if (
    !p.ckd &&
    egfr &&
    egfr.value < 60 &&
    low.length >= 2 &&
    lowFirst &&
    lowLast &&
    new Date(lowLast.collectedAt).getTime() - new Date(lowFirst.collectedAt).getTime() >= 90 * DAY
  )
    add('NO_ESTABLISHED_CKD_STAGE', 'medium', 'missing', 'eGFR has been below 60 for over 3 months but no established CKD stage is recorded.', [
      'lab:EGFR:' + isoDate(lowFirst.collectedAt),
    ]);
  if (ckd.mismatch && ckd.egfrVal != null && ckd.egfrDate)
    add(
      'CKD_STAGE_MISMATCH',
      'high',
      'inconsistent',
      `Established CKD stage ${ckd.established} does not match the eGFR category of the latest result (${ckd.egfrCat}, eGFR ${fmtVal('EGFR', ckd.egfrVal)}).`,
      ['lab:EGFR:' + isoDate(ckd.egfrDate)],
    );
  const creat = latest.CREAT;
  if (egfr && creat && egfr.reportId === creat.reportId) {
    const calc = ckdEpi(creat.value, ageOf(p.dob, egfr.collectedAt), p.sex);
    if (Math.abs(calc - egfr.value) > 12)
      add(
        'EGFR_CREATININE_DISCORDANT',
        'medium',
        'inconsistent',
        `Reported eGFR ${egfr.value} differs from the CKD-EPI 2021 estimate (${Math.round(calc)}) computed from creatinine ${fmtVal('CREAT', creat.value)} mg/dL.`,
        ['lab:EGFR:' + isoDate(egfr.collectedAt), 'lab:CREAT:' + isoDate(creat.collectedAt)],
      );
  }
  const c = trends.CREAT;
  const e = trends.EGFR;
  if (
    c.n >= 3 &&
    e.n >= 3 &&
    ((c.direction === 'improving' && e.direction === 'worsening') ||
      (c.direction === 'worsening' && e.direction === 'improving'))
  )
    add('DIRECTION_CONTRADICTION', 'medium', 'inconsistent', 'Creatinine and eGFR are trending in clinically incompatible directions.');
  meds
    .filter((m) => m.status === 'active' && m.end && new Date(m.end).getTime() < now)
    .forEach((m) =>
      add('ACTIVE_MED_PAST_END_DATE', 'low', 'inconsistent', `${m.name} is marked active but its end date (${fmtDate(m.end)}) has passed.`, ['med:' + sid(m.id)]),
    );
  res.forEach((r) => {
    const t = new Date(r.collectedAt).getTime();
    if (t > now || t < new Date(p.dob).getTime())
      add('LAB_DATE_INVALID', 'high', 'inconsistent', `A ${LAB_TESTS[r.test].name} result has an impossible collection date.`);
  });
  const o = { high: 0, medium: 1, low: 2 };
  return g.sort((a, b) => o[a.sev] - o[b.sev]);
}

export function analyze(db: Db, id: string): Analysis | null {
  const p = patientOf(db, id);
  if (!p) return null;
  const age = ageOf(p.dob);
  const latest = latestByTest(db, id);
  const res = resultsOf(db, id);
  const series = (t: TestCode) =>
    res
      .filter((r) => r.test === t)
      .sort((a, b) => new Date(a.collectedAt).getTime() - new Date(b.collectedAt).getTime())
      .map((r) => ({ t: new Date(r.collectedAt).getTime(), v: r.value, flag: r.flag, id: r.id }));
  const trends = {
    CREAT: trendStats(series('CREAT'), 'CREAT'),
    EGFR: trendStats(series('EGFR'), 'EGFR'),
  };
  const eg = latest.EGFR;
  const ua = latest.UACR;
  const ckd: CkdInfo = {
    established: p.ckd,
    egfrCat: eg ? classifyEgfr(eg.value) : null,
    egfrVal: eg ? eg.value : null,
    egfrDate: eg ? eg.collectedAt : null,
    uacrCat: ua ? classifyUacr(ua.value) : null,
    uacrVal: ua ? ua.value : null,
    uacrDate: ua ? ua.collectedAt : null,
    mismatch: false,
  };
  ckd.mismatch = !!(p.ckd && eg && ckd.egfrCat !== p.ckd);
  const gaps = gapEngine(db, p, latest, res, trends, ckd);
  const abnormal = Object.values(latest).filter((r): r is LabResult => !!r && r.flag !== 'normal');
  const critical = abnormal.some((r) => r.flag.indexOf('critical') === 0);
  return {
    p,
    age,
    latest,
    res,
    trends,
    ckd,
    gaps,
    abnormal,
    critical,
    rapid: !!trends.EGFR.rapid,
    attention: critical || !!trends.EGFR.rapid || gaps.some((x) => x.sev === 'high'),
  };
}
