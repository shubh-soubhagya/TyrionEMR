import { DestroyRef, Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import type { LatestDto } from '@core/api/dto/lab.dto';
import type { PatientDetailDto } from '@core/api/dto/patient.dto';
import { LOADING, toRemote, type Remote } from '@core/api/remote';
import { LabsApi } from '@core/data/labs.api';
import { PatientsApi } from '@core/data/patients.api';
import { ModalService } from '@core/ui/modal.service';
import { Subscription } from 'rxjs';

/**
 * The patient being viewed: header data (with `version` and counts) and the latest-lab block (eGFR category).
 * One instance per open chart, provided by the shell, so the tabs share it. After a save, only the part that changed
 * is reloaded (header after a patient, condition, medication, allergy or encounter change; labs after a lab report).
 */
@Injectable()
export class PatientStore {
  private readonly patients = inject(PatientsApi);
  private readonly labs = inject(LabsApi);
  private readonly modals = inject(ModalService);
  private readonly destroyRef = inject(DestroyRef);

  readonly id = signal('');
  readonly detail = signal<Remote<PatientDetailDto>>(LOADING);
  readonly latest = signal<Remote<LatestDto>>(LOADING);

  private detailSub: Subscription | null = null;
  private latestSub: Subscription | null = null;
  private lastChange = 0;

  /** The patient's current version, for the next PATCH. */
  readonly version = computed(() => {
    const d = this.detail();
    return d.state === 'ok' ? d.data.version : null;
  });

  /** eGFR category of the latest result (from lab-svc), or null. */
  readonly egfrCategory = computed(() => {
    const l = this.latest();
    return l.state === 'ok' ? l.data.ckd.egfr_category : null;
  });

  /** Established stage differs from the eGFR category: both values come from the services, the comparison is display. */
  readonly mismatch = computed(() => {
    const d = this.detail();
    const cat = this.egfrCategory();
    return (
      d.state === 'ok' &&
      d.data.established_ckd_stage !== null &&
      cat !== null &&
      d.data.established_ckd_stage !== cat
    );
  });

  constructor() {
    effect(() => {
      const id = this.id();
      if (id) untracked(() => this.loadAll());
    });
    effect(() => {
      const c = this.modals.changed();
      if (!c || c.n === this.lastChange || c.patientId !== untracked(this.id)) return;
      this.lastChange = c.n;
      untracked(() => (c.kind === 'labs' ? this.reloadLatest() : this.reloadDetail()));
    });
    this.destroyRef.onDestroy(() => {
      this.detailSub?.unsubscribe();
      this.latestSub?.unsubscribe();
    });
  }

  loadAll(): void {
    this.reloadDetail();
    this.reloadLatest();
  }

  reloadDetail(): void {
    this.detailSub?.unsubscribe();
    this.detailSub = toRemote(this.patients.get(this.id()), () => false).subscribe((s) =>
      this.detail.set(s),
    );
  }

  reloadLatest(): void {
    this.latestSub?.unsubscribe();
    this.latestSub = toRemote(this.labs.latest(this.id()), () => false).subscribe((s) =>
      this.latest.set(s),
    );
  }

  /** Keeps the version after a write whose response carries the new one (allergy changes), without a round trip. */
  setVersion(version: number): void {
    const d = this.detail();
    if (d.state === 'ok') this.detail.set({ state: 'ok', data: { ...d.data, version } });
  }
}
