// html:919-923. The list is paged by patient-svc (`GET /patients/{id}/encounters?page=&size=`); a save reloads just it.
import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { remoteSignal } from '@core/api/remote-signal';
import { EncountersApi } from '@core/data/encounters.api';
import type { Encounter } from '@core/data/models';
import { fmtDate } from '@core/format';
import { ModalService } from '@core/ui/modal.service';
import { EmrIcon } from '@shared/ui/icon/icon';
import { EmrRemoteState } from '@shared/ui/remote-state/remote-state';
import { typeLabel } from '@shared/utils/labels';

const SIZE = 10;

@Component({
  selector: 'emr-encounters-tab',
  imports: [EmrIcon, EmrRemoteState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './encounters-tab.html',
})
export class EncountersTab {
  private readonly api = inject(EncountersApi);
  protected readonly modals = inject(ModalService);
  readonly id = input.required<string>();

  protected readonly fmtDate = fmtDate;
  protected readonly typeLabel = typeLabel;
  protected readonly page = signal(1);

  protected readonly list = remoteSignal(
    () => [this.id(), this.page()],
    () => this.api.list(this.id(), this.page(), SIZE),
    (p) => p.items.length === 0 && p.total === 0,
  );

  private lastChange = 0;

  constructor() {
    effect(() => {
      const c = this.modals.changed();
      if (
        c &&
        c.kind === 'encounters' &&
        c.n !== this.lastChange &&
        c.patientId === untracked(this.id)
      ) {
        this.lastChange = c.n;
        untracked(() => this.list.reload());
      }
    });
  }

  protected pages(total: number): number {
    return Math.max(1, Math.ceil(total / SIZE));
  }

  protected go(delta: number): void {
    this.page.update((p) => Math.max(1, p + delta));
  }

  protected short(text: string): string {
    return text.length > 90 ? text.slice(0, 90) + '…' : text;
  }

  protected open(e: Encounter): void {
    if (e.status === 'draft') {
      this.modals.open({ kind: 'encounter-form', patientId: this.id(), encounterId: e.id });
    } else {
      this.modals.open({
        kind: 'encounter-view',
        patientId: this.id(),
        encounterId: e.id,
        sub: `${typeLabel(e.type)}, Final`,
      });
    }
  }
}
