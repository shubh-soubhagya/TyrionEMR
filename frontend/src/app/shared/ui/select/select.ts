import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrFormFieldError } from '../form-field-error/form-field-error';
import { EmrControlBase } from '../forms/control-base';

export interface SelectOption {
  readonly value: string;
  readonly label: string;
}

/**
 * Native select. `size="sm"` is the compact toolbar variant (html `.inp.sm`: 32px high, auto
 * width). An empty-string value means "nothing chosen" and is written to the form as null.
 */
@Component({
  selector: 'emr-select',
  imports: [EmrFormFieldError],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label class="fld">
      <span class="fld-l" [class.sr-only]="hideLabel()"
        >{{ label() }}
        @if (isRequired()) {
          <b class="req" aria-hidden="true">*</b>
        }
      </span>
      <select
        class="control"
        [class.invalid]="showError()"
        [class.sm]="size() === 'sm'"
        [disabled]="disabled()"
        [attr.aria-invalid]="showError() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="isRequired() ? 'true' : null"
        (change)="onSelectChange($event)"
        (blur)="markTouched()"
      >
        @if (placeholder(); as text) {
          <option value="" [selected]="!value()">{{ text }}</option>
        }
        @for (option of options(); track option.value) {
          <option [value]="option.value" [selected]="option.value === value()">
            {{ option.label }}
          </option>
        }
      </select>
      @if (hint(); as text) {
        <span class="hint" [id]="hintId">{{ text }}</span>
      }
      <emr-form-field-error [errors]="showError() ? errors() : null" [id]="errorId" />
    </label>
  `,
  styles: `
    @use 'fields' as f;
    :host {
      @include f.field;
    }
    .sm {
      min-height: 32px;
      padding: var(--space-5) var(--space-9);
      width: auto;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
    }
  `,
})
export class EmrSelect extends EmrControlBase<string> {
  readonly options = input.required<readonly SelectOption[]>();
  /** Text of the empty choice; omit for a select that always has a value. */
  readonly placeholder = input<string>();
  readonly size = input<'md' | 'sm'>('md');
  /** Keep the label for screen readers but do not show it (toolbar filters). */
  readonly hideLabel = input(false);

  protected onSelectChange(event: Event): void {
    const selected = (event.target as HTMLSelectElement).value;
    this.setValue(selected === '' ? null : selected);
  }
}
