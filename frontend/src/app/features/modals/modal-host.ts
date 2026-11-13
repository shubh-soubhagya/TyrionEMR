import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ModalService } from '../../core/ui/modal.service';
import { EncounterModal, EncounterViewModal } from './encounter-modal';
import { LabModal } from './lab-modal';
import { PatientModal } from './patient-modal';
import { AllergyModal, ConditionModal, ConfirmModal, MedModal } from './small-modals';

/** Renders whichever modal `ModalService` says is open. Mounted once in the app shell. */
@Component({
  selector: 'emr-modal-host',
  imports: [
    PatientModal,
    ConditionModal,
    MedModal,
    AllergyModal,
    EncounterModal,
    EncounterViewModal,
    LabModal,
    ConfirmModal,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (patient(); as m) {
      <emr-patient-modal [patientId]="m.patientId" (closed)="modals.close()" />
    }
    @if (condition(); as m) {
      <emr-condition-modal [patientId]="m.patientId" (closed)="modals.close()" />
    }
    @if (med(); as m) {
      <emr-med-modal [patientId]="m.patientId" (closed)="modals.close()" />
    }
    @if (allergy(); as m) {
      <emr-allergy-modal [patientId]="m.patientId" (closed)="modals.close()" />
    }
    @if (encounterForm(); as m) {
      <emr-encounter-modal
        [patientId]="m.patientId"
        [encounterId]="m.encounterId"
        (closed)="modals.close()"
      />
    }
    @if (encounterView(); as m) {
      <emr-encounter-view-modal
        [encounterId]="m.encounterId"
        [sub]="m.sub"
        (closed)="modals.close()"
      />
    }
    @if (lab(); as m) {
      <emr-lab-modal [patientId]="m.patientId" (closed)="modals.close()" />
    }
    @if (confirm(); as m) {
      <emr-confirm-modal [title]="m.title" [message]="m.message" [ok]="m.ok" [danger]="m.danger" />
    }
  `,
})
export class ModalHost {
  protected readonly modals = inject(ModalService);
  private readonly cur = this.modals.current;

  protected readonly patient = computed(() => {
    const c = this.cur();
    return c?.kind === 'patient' ? c : null;
  });
  protected readonly condition = computed(() => {
    const c = this.cur();
    return c?.kind === 'condition' ? c : null;
  });
  protected readonly med = computed(() => {
    const c = this.cur();
    return c?.kind === 'med' ? c : null;
  });
  protected readonly allergy = computed(() => {
    const c = this.cur();
    return c?.kind === 'allergy' ? c : null;
  });
  protected readonly encounterForm = computed(() => {
    const c = this.cur();
    return c?.kind === 'encounter-form' ? c : null;
  });
  protected readonly encounterView = computed(() => {
    const c = this.cur();
    return c?.kind === 'encounter-view' ? c : null;
  });
  protected readonly lab = computed(() => {
    const c = this.cur();
    return c?.kind === 'lab' ? c : null;
  });
  protected readonly confirm = computed(() => {
    const c = this.cur();
    return c?.kind === 'confirm' ? c : null;
  });
}
