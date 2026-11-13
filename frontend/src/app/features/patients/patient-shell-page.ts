// html:837-858. The header, the tab pills and the eGFR/established-stage chips come from patient-svc
// (`GET /patients/{id}`) and lab-svc (`GET /labs/patients/{id}/latest`); a 404 is the not-found state.
import { ChangeDetectionStrategy, Component, computed, effect, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiError } from '@core/api/api-error';
import { describeError } from '@core/api/error-messages';
import type { PatientDetailDto } from '@core/api/dto/patient.dto';
import { egfrLabel } from '@core/clinical/lab-tests';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrAvatar } from '@shared/ui/avatar/avatar';
import { EmrCkdStageBadge } from '@shared/ui/ckd-stage-badge/ckd-stage-badge';
import { EmrIcon } from '@shared/ui/icon/icon';
import { IconName } from '@shared/ui/icon/icons';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { sexLabel } from '@shared/utils/labels';
import { PatientStore } from './patient-store';

const TABS: readonly {
  key: string;
  label: string;
  icon: IconName;
  count?: keyof PatientDetailDto['counts'];
}[] = [
  { key: 'overview', label: 'Overview', icon: 'user' },
  { key: 'conditions', label: 'Conditions', icon: 'clip', count: 'conditions' },
  { key: 'meds', label: 'Medications and allergies', icon: 'pill', count: 'active_medications' },
  { key: 'encounters', label: 'Encounters', icon: 'file', count: 'encounters' },
  { key: 'labs', label: 'Labs', icon: 'flask' },
  { key: 'ai', label: 'AI summary', icon: 'spark' },
];

@Component({
  selector: 'emr-patient-shell-page',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    EmrIcon,
    EmrAvatar,
    EmrCkdStageBadge,
    EmrRemoteState,
  ],
  providers: [PatientStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './patient-shell-page.html',
})
export class PatientShellPage {
  protected readonly store = inject(PatientStore);
  protected readonly modals = inject(ModalService);

  /** `:id` route param, bound by withComponentInputBinding. */
  readonly id = input.required<string>();

  protected readonly tabs = TABS;
  protected readonly sexLabel = sexLabel;
  protected readonly fmtDate = fmtDate;
  protected readonly egfrLabel = egfrLabel;

  protected readonly notFound = computed(() => {
    const d = this.store.detail();
    return d.state === 'error' && d.error.status === 404;
  });
  protected readonly error = computed(() => {
    const d = this.store.detail();
    return d.state === 'error' && d.error.status !== 404 ? d.error : null;
  });
  protected readonly errorText = (e: ApiError): string => describeError(e).message;
  protected readonly name = (p: PatientDetailDto): string => p.first_name + ' ' + p.last_name;
  protected readonly allergyNames = (p: PatientDetailDto): string =>
    p.allergy_summary.map((a) => a.allergen).join(', ');
  protected readonly stage = (p: PatientDetailDto) =>
    p.established_ckd_stage as 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5' | null;

  constructor() {
    effect(() => this.store.id.set(this.id()));
  }
}
