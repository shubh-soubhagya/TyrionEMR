import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { describeError, isRetryable } from '@core/api/error-messages';
import type { Remote } from '@core/api/remote';
import { EmrErrorState } from '../error-state/error-state';
import { EmrSkeleton } from '../skeleton/skeleton';

/**
 * Wraps one panel of a screen that loads from the network: a skeleton while loading, an error block (with the
 * request id, never the internal code, and a Retry button when trying again can help) on failure, and the projected
 * content otherwise. Other panels on the screen are not affected by this one failing.
 */
@Component({
  selector: 'emr-remote-state',
  imports: [EmrSkeleton, EmrErrorState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (remote().state) {
      @case ('loading') {
        <div class="panel-b" role="status" aria-label="Loading">
          <emr-skeleton [widths]="widths()" />
        </div>
      }
      @case ('error') {
        @if (view(); as v) {
          <emr-error-state
            [status]="status()"
            [message]="v.message"
            [code]="v.requestId ? 'Reference: ' + v.requestId : undefined"
            [retryable]="retryable()"
            (retry)="retry.emit()"
          />
        }
      }
      @default {
        <ng-content />
      }
    }
  `,
})
export class EmrRemoteState {
  readonly remote = input.required<Remote<unknown>>();
  readonly widths = input<readonly string[]>(['30%', '90%', '80%', '60%']);
  readonly retry = output<void>();

  private readonly error = computed(() => {
    const r = this.remote();
    return r.state === 'error' ? r.error : null;
  });
  protected readonly view = computed(() => {
    const e = this.error();
    return e ? describeError(e) : null;
  });
  protected readonly status = computed(() => this.error()?.status);
  protected readonly retryable = computed(() => {
    const e = this.error();
    return e ? isRetryable(e) : false;
  });
}
