import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { CKD_STAGE_LABELS, CkdStage } from '../../models/clinical';
import { EmrBadge } from '../badge/badge';

/**
 * CKD / eGFR category chip. The HTML renders every stage as a teal chip (stage colors are only
 * used for the dashboard bars), so the tone is fixed. `null` shows the HTML's italic "Not set".
 * With `showLabel` it appends the KDIGO label, e.g. "G3b (Moderately to severely decreased)".
 */
@Component({
  selector: 'emr-ckd-stage-badge',
  imports: [EmrBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (stage(); as value) {
      <emr-badge tone="teal">{{ text() }}</emr-badge>
    } @else {
      <span class="nd">{{ emptyText() }}</span>
    }
  `,
  styles: `
    :host {
      display: inline-flex;
    }
  `,
})
export class EmrCkdStageBadge {
  readonly stage = input<CkdStage | null | undefined>(null);
  readonly showLabel = input(false);
  readonly emptyText = input('Not set');

  protected readonly text = computed(() => {
    const stage = this.stage();
    if (!stage) return '';
    return this.showLabel() ? `${stage} (${CKD_STAGE_LABELS[stage]})` : stage;
  });
}
