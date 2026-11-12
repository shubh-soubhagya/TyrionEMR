import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';

export type BadgeTone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'teal' | 'ai';

/** Pill chip (html `.chip`). Content is projected text; an optional leading icon. */
@Component({
  selector: 'emr-badge',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (icon(); as name) {
      <emr-icon [name]="name" [size]="13" />
    }
    <ng-content />
  `,
  host: { '[class]': 'tone()' },
  styleUrl: './badge.scss',
})
export class EmrBadge {
  readonly tone = input<BadgeTone>('neutral');
  readonly icon = input<IconName>();
}
