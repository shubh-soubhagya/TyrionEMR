import { Injectable, signal } from '@angular/core';
import {
  flagFor,
  LAB_TESTS,
  rangeFor,
  Sex,
  TestCode,
  toCanon,
} from '../clinical/lab-tests';
import { ageOf, isoDate, uid } from '../format';
import {
  allergiesOf,
  analyze,
  Analysis,
  condsOf,
  encsOf,
  medsOf,
  patientOf,
  primaryOf,
  resultsOf,
} from './analysis';
import {
  AllergyStatus,
  CkdStage,
  Db,
  Encounter,
  EncounterDx,
  EncounterType,
  Patient,
  Vitals,
} from './models';
import { CLINICIANS, seedDb } from './seed';

export class AppError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface PatientInput {
  first: string;
  last: string;
  dob: string;
  sex: Sex;
  phone: string;
  email: string;
  address: string;
  pmh: string;
  fh: string;
  sh: string;
  als?: AllergyStatus;
}

export interface EncounterInput {
  date: string;
  type: EncounterType;
  cc: string;
  symptoms: string[];
  exam: string;
  assessment: string;
  plan: string;
  followUp: string;
  vitals: Vitals | null;
  diagnoses: { icd: string; desc: string; prob: boolean }[];
}

export interface LabRowInput {
  test: TestCode;
  value: number;
  unit: string;
}

const STORAGE_KEY = 'nephrocare-ng-v1';

/**
 * The prototype's in-memory "backend" (html `db`, repositories and mutations), as one injectable.
 * Screens read through computed() that call `rev()`, so any change re-renders them. State is kept
 * in localStorage like the prototype does; clearing site data resets to the seed.
 */
@Injectable({ providedIn: 'root' })
export class DbService {
  private db: Db = this.load();
  /** Bumped on every mutation; read it inside computed() to re-run selectors. */
  readonly rev = signal(0);

  readonly clinician = CLINICIANS[0];

  private load(): Db {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { v: number; db: Db };
        if (parsed.v === 1) return parsed.db;
      }
    } catch {
      /* fall through to the seed */
    }
    return seedDb();
  }

  private commit(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ v: 1, db: this.db }));
    } catch {
      /* storage may be unavailable; the app still works in memory */
    }
    this.rev.update((n) => n + 1);
  }

  /** Throw-away reset to the seed (dev). */
  reset(): void {
    this.db = seedDb();
    this.commit();
  }

  // ---- selectors (call inside computed(); they depend on rev()) ----
  readonly raw = (): Db => {
    this.rev();
    return this.db;
  };
  patients(): Patient[] {
    this.rev();
    return this.db.patients.filter((p) => !p.deletedAt);
  }
  patient(id: string): Patient {
    this.rev();
    const p = patientOf(this.db, id);
    if (!p) throw new AppError(404, 'NOT_FOUND', 'Patient not found');
    return p;
  }
  analysis(id: string): Analysis {
    this.rev();
    const a = analyze(this.db, id);
    if (!a) throw new AppError(404, 'NOT_FOUND', 'Patient not found');
    return a;
  }
  conds(id: string) {
    this.rev();
    return condsOf(this.db, id);
  }
  meds(id: string) {
    this.rev();
    return medsOf(this.db, id);
  }
  allergies(id: string) {
    this.rev();
    return allergiesOf(this.db, id);
  }
  encounters(id: string) {
    this.rev();
    return encsOf(this.db, id);
  }
  results(id: string) {
    this.rev();
    return resultsOf(this.db, id);
  }
  primary(id: string) {
    this.rev();
    return primaryOf(this.db, id);
  }
  encounterById(id: string): Encounter | undefined {
    this.rev();
    return this.db.encounters.find((e) => e.id === id);
  }
  labReportOf(reportId: string) {
    this.rev();
    return this.db.labReports.find((r) => r.id === reportId);
  }
  patientName(id: string): string {
    const p = this.db.patients.find((x) => x.id === id);
    return p ? p.first + ' ' + p.last : 'Unknown';
  }

  // ---- mutations (html forms.* and actions.*) ----
  createPatient(v: PatientInput): Patient {
    const n = Math.max(...this.db.patients.map((p) => +p.mrn.slice(3))) + 1;
    const p: Patient = {
      id: uid(),
      mrn: 'PT-' + String(n).padStart(6, '0'),
      first: v.first,
      last: v.last,
      dob: v.dob,
      sex: v.sex,
      phone: v.phone,
      email: v.email,
      address: v.address,
      pmh: v.pmh,
      fh: v.fh,
      sh: v.sh,
      allergyStatus: v.als ?? 'unknown',
      ckd: null,
      version: 1,
      deletedAt: null,
      createdAt: new Date().toISOString(),
    };
    this.db.patients.push(p);
    this.commit();
    return p;
  }

  updatePatient(id: string, version: number, v: PatientInput): void {
    const p = this.patient(id);
    if (p.version !== version)
      throw new AppError(409, 'VERSION_CONFLICT', 'This record was changed by someone else. Reload and try again.');
    Object.assign(p, {
      first: v.first,
      last: v.last,
      dob: v.dob,
      sex: v.sex,
      phone: v.phone,
      email: v.email,
      address: v.address,
      pmh: v.pmh,
      fh: v.fh,
      sh: v.sh,
    });
    p.version++;
    this.commit();
  }

  setCkdStage(id: string, stage: CkdStage | null): void {
    const p = this.patient(id);
    p.ckd = stage;
    p.version++;
    this.commit();
  }

  addCondition(
    id: string,
    v: { icd: string; desc: string; cat: 'nephrology' | 'comorbidity'; onset: string; primary: boolean },
  ): void {
    if (v.primary) condsOf(this.db, id).forEach((c) => (c.isPrimary = false));
    this.db.conditions.push({
      id: uid(),
      patientId: id,
      icd10: v.icd.trim().toUpperCase(),
      desc: v.desc.trim(),
      category: v.cat,
      isPrimary: v.primary,
      status: 'active',
      onset: v.onset,
      sourceEncounterId: null,
      deletedAt: null,
    });
    this.commit();
  }

  setPrimary(id: string, condId: string): void {
    condsOf(this.db, id).forEach((c) => (c.isPrimary = false));
    const c = this.db.conditions.find((x) => x.id === condId);
    if (c) c.isPrimary = true;
    this.commit();
  }

  toggleCondition(condId: string): void {
    const c = this.db.conditions.find((x) => x.id === condId);
    if (!c) return;
    c.status = c.status === 'active' ? 'resolved' : 'active';
    if (c.status === 'resolved') c.isPrimary = false;
    this.commit();
  }

  addMedication(id: string, v: { name: string; dose: string; route: string; freq: string; start: string }): void {
    this.db.meds.push({
      id: uid(),
      patientId: id,
      name: v.name,
      dose: v.dose,
      route: v.route,
      freq: v.freq,
      start: v.start,
      end: null,
      status: 'active',
    });
    this.commit();
  }

  stopMedication(medId: string): void {
    const m = this.db.meds.find((x) => x.id === medId);
    if (!m) return;
    m.status = 'discontinued';
    m.end = isoDate(Date.now());
    this.commit();
  }

  addAllergy(id: string, v: { allergen: string; reaction: string; severity: 'mild' | 'moderate' | 'severe' }): void {
    this.db.allergies.push({ id: uid(), patientId: id, ...v });
    this.patient(id).allergyStatus = 'has';
    this.commit();
  }

  removeAllergy(id: string, allergyId: string): void {
    this.db.allergies = this.db.allergies.filter((x) => x.id !== allergyId);
    if (!allergiesOf(this.db, id).length) this.patient(id).allergyStatus = 'unknown';
    this.commit();
  }

  markNoKnownAllergies(id: string): void {
    this.patient(id).allergyStatus = 'nka';
    this.commit();
  }

  deleteDraft(encId: string): void {
    const e = this.db.encounters.find((x) => x.id === encId);
    if (!e) return;
    if (e.status !== 'draft') throw new AppError(409, 'ENCOUNTER_FINAL', 'Final encounters cannot be deleted.');
    e.deletedAt = new Date().toISOString();
    this.commit();
  }

  /** Create or update an encounter; `final` locks it and adds flagged diagnoses to the problem list. */
  saveEncounter(
    patientId: string,
    editId: string | null,
    v: EncounterInput,
    mode: 'draft' | 'final',
  ): { e: Encounter; added: number } {
    let e = editId ? (this.db.encounters.find((x) => x.id === editId) ?? null) : null;
    if (e && e.status === 'final') throw new AppError(409, 'ENCOUNTER_FINAL', 'Final encounters cannot be edited.');
    const diagnoses: EncounterDx[] = v.diagnoses.map((d) => ({ icd: d.icd, desc: d.desc, condId: null }));
    const data = {
      date: new Date(v.date).toISOString(),
      type: v.type,
      cc: v.cc,
      symptoms: v.symptoms,
      exam: v.exam,
      assessment: v.assessment,
      plan: v.plan,
      followUp: v.followUp,
      vitals: v.vitals,
      diagnoses,
    };
    if (e) {
      Object.assign(e, data);
    } else {
      e = {
        id: uid(),
        patientId,
        clinician: this.clinician,
        status: 'draft',
        version: 1,
        deletedAt: null,
        ...data,
      };
      this.db.encounters.push(e);
    }
    let added = 0;
    if (mode === 'final') {
      e.status = 'final';
      e.finalizedAt = new Date().toISOString();
      const target = e;
      v.diagnoses.forEach((d, i) => {
        if (!d.prob) return;
        let c = condsOf(this.db, patientId).find((x) => x.icd10 && x.icd10 === d.icd && x.status === 'active');
        if (!c) {
          c = {
            id: uid(),
            patientId,
            icd10: d.icd,
            desc: d.desc,
            category: /^(N|Q61|M32)/.test(d.icd) ? 'nephrology' : 'comorbidity',
            isPrimary: false,
            status: 'active',
            onset: isoDate(target.date),
            sourceEncounterId: target.id,
            deletedAt: null,
          };
          this.db.conditions.push(c);
          added++;
        }
        const dx = target.diagnoses[i];
        if (dx) dx.condId = c.id;
      });
    }
    this.commit();
    return { e, added };
  }

  addLabReport(
    patientId: string,
    v: { collectedAt: string; labName: string; notes: string; rows: LabRowInput[] },
  ): { n: number; abn: number } {
    const p = this.patient(patientId);
    const rep = {
      id: uid(),
      patientId,
      collectedAt: new Date(v.collectedAt).toISOString(),
      labName: v.labName.trim() || 'Unspecified laboratory',
      notes: v.notes.trim(),
      enteredBy: this.clinician,
      createdAt: new Date().toISOString(),
    };
    this.db.labReports.push(rep);
    let abn = 0;
    v.rows.forEach((r) => {
      const rg = rangeFor(r.test, p.sex);
      const val = toCanon(r.test, r.value, r.unit);
      const fl = flagFor(val, rg);
      if (fl !== 'normal') abn++;
      this.db.labResults.push({
        id: uid(),
        reportId: rep.id,
        patientId,
        collectedAt: rep.collectedAt,
        test: r.test,
        value: val,
        unit: LAB_TESTS[r.test].canon,
        valueOriginal: r.value,
        unitOriginal: r.unit,
        refLow: rg.low,
        refHigh: rg.high,
        flag: fl,
      });
    });
    this.commit();
    return { n: v.rows.length, abn };
  }

  ageOfPatient(id: string): number {
    return ageOf(this.patient(id).dob);
  }

  // ---- AI summary store (used by the AI tab) ----
  readonly aiStore = (): Db['aiSummaries'] => {
    this.rev();
    return this.db.aiSummaries;
  };
  saveAiSummary(rec: Db['aiSummaries'][number]): void {
    this.db.aiSummaries.unshift(rec);
    this.commit();
  }
  get config(): Db['config'] {
    return this.db.config;
  }
}
