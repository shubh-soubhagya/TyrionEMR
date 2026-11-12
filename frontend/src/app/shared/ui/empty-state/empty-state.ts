import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';

/**
 * "Nothing here" block (html `.empty`): optional icon, bold title, explanation, and an action
 * slot for a button ("Clear filters", "New encounter").
 */
@Component({
  selector: 'emr-empty-state',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (icon(); as name) {
      <emr-icon [name]="name" [size]="30" />
    }
    <b>{{ title() }}</b>
    <ng-content />
    <div class="actions"><ng-content select="[emr-empty-actions]" /></div>
  `,
  styles: `
    :host {
      display: block;
      padding: var(--space-36) var(--space-20);
      text-align: center;
      color: var(--color-text-muted);
    }
    b {
      display: block;
      color: var(--color-text-primary);
      font-size: var(--fs-15);
      margin-bottom: var(--space-4);
    }
    .actions:not(:empty) {
      margin-top: var(--space-12);
    }
  `,
})
export class EmrEmptyState {
  readonly title = input.required<string>();
  readonly icon = input<IconName>();
}
