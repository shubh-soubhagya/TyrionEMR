import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

/**
 * Card (html `.panel`). Slots: `[emr-panel-title]` or the `title` input, `[emr-panel-actions]`,
 * the default slot is the body, `[emr-panel-footer]`. `flush` removes body padding (tables).
 * `accent="ai"` gives the violet AI container look (html `.ai-panel`).
 */
@Component({
  selector: 'emr-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './panel.html',
  styleUrl: './panel.scss',
  host: { '[class.ai]': "accent() === 'ai'" },
})
export class EmrPanel {
  readonly title = input<string>();
  readonly flush = input(false, { transform: booleanAttribute });
  readonly accent = input<'none' | 'ai'>('none');
}
