import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * A clinical value with its unit. Missing data (null, undefined, empty text) is shown as
 * "Not documented" and never as a blank, "null" or 0 (CLAUDE.md section 6).
 */
@Component({
  selector: 'emr-value-with-unit',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (hasValue()) {
      <span [class.mono]="mono()">{{ text() }}</span>
      @if (unit(); as u) {
        <span class="muted small"> {{ u }}</span>
      }
    } @else {
      <span class="nd">{{ emptyText() }}</span>
    }
  `,
})
export class EmrValueWithUnit {
  readonly value = input<number | string | null | undefined>();
  readonly unit = input<string>();
  /** Fixed decimals for numbers (lab parameters define their own). */
  readonly decimals = input<number>();
  readonly mono = input(false);
  readonly emptyText = input('Not documented');

  protected readonly hasValue = computed(() => {
    const v = this.value();
    return v !== null && v !== undefined && String(v).trim() !== '';
  });

  protected readonly text = computed(() => {
    const v = this.value();
    const decimals = this.decimals();
    return typeof v === 'number' && decimals !== undefined ? v.toFixed(decimals) : String(v);
  });
}
