import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LabFlag } from '../../models/clinical';
import { BadgeTone, EmrBadge } from '../badge/badge';
import { IconName } from '../icon/icons';

export interface FlagView {
  readonly text: string;
  readonly tone: BadgeTone;
  readonly icon?: IconName;
}

// Same labels, tones and arrows as the HTML `FLAG` map (html:371). The text and the arrow carry the
// meaning, so a flag is never conveyed by color alone (CLAUDE.md section 7).
export const FLAG_VIEWS: Readonly<Record<LabFlag, FlagView>> = {
  normal: { text: 'Normal', tone: 'ok' },
  low: { text: 'Low', tone: 'info', icon: 'dn' },
  high: { text: 'High', tone: 'warn', icon: 'up' },
  critical_low: { text: 'Critical low', tone: 'danger', icon: 'dn' },
  critical_high: { text: 'Critical high', tone: 'danger', icon: 'up' },
  unknown: { text: 'No range', tone: 'neutral' },
};

/** Abnormal-value chip. `rangeText` becomes the tooltip, e.g. "Reference 0.7–1.3 mg/dL". */
@Component({
  selector: 'emr-lab-flag',
  imports: [EmrBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<emr-badge [tone]="view().tone" [icon]="view().icon" [attr.title]="rangeText()">{{
    view().text
  }}</emr-badge>`,
  styles: `
    :host {
      display: inline-flex;
    }
  `,
})
export class EmrLabFlag {
  readonly flag = input.required<LabFlag>();
  readonly rangeText = input<string>();
  protected readonly view = computed(() => FLAG_VIEWS[this.flag()] ?? FLAG_VIEWS.unknown);
}
