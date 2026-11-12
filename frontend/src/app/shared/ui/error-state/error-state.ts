import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { EmrButton } from '../button/button';
import { EmrIcon } from '../icon/icon';

/**
 * Error block (html `errorState`, html:651): 403 "Access denied", 404 "Not found", otherwise
 * "Something went wrong". Adds a Retry button (output `retry`) that the HTML lacks, and an
 * optional back link.
 */
@Component({
  selector: 'emr-error-state',
  imports: [EmrIcon, EmrButton],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-icon [name]="status() === 403 ? 'shield' : 'alert'" [size]="30" />
    <b>{{ title() }}</b>
    <span>{{ message() }}</span>
    @if (code(); as value) {
      <div class="small muted code">{{ value }}</div>
    }
    <div class="actions">
      @if (retryable()) {
        <button emr-button type="button" icon="refresh" (click)="retry.emit()">Try again</button>
      }
      <ng-content />
    </div>
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
    .code {
      margin-top: var(--space-8);
    }
    .actions {
      margin-top: var(--space-14);
      display: flex;
      gap: var(--space-8);
      justify-content: center;
    }
  `,
})
export class EmrErrorState {
  readonly status = input<number>();
  readonly message = input.required<string>();
  readonly code = input<string>();
  readonly retryable = input(true);
  readonly retry = output<void>();

  protected readonly title = computed(() => {
    switch (this.status()) {
      case 403:
        return 'Access denied';
      case 404:
        return 'Not found';
      default:
        return 'Something went wrong';
    }
  });
}
