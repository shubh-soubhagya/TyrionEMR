import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrFormFieldError } from '../form-field-error/form-field-error';
import { EmrControlBase } from '../forms/control-base';

/**
 * Native date or date-time input. The form value is the browser's string
 * (`yyyy-MM-dd` or `yyyy-MM-ddTHH:mm`); conversion to ISO happens in the feature, not here.
 */
@Component({
  selector: 'emr-date-field',
  imports: [EmrFormFieldError],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label class="fld">
      <span class="fld-l"
        >{{ label() }}
        @if (isRequired()) {
          <b class="req" aria-hidden="true">*</b>
        }
      </span>
      <input
        class="control"
        [class.invalid]="showError()"
        [type]="kind()"
        [value]="value() ?? ''"
        [disabled]="disabled()"
        [attr.min]="min()"
        [attr.max]="max()"
        [attr.aria-invalid]="showError() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="isRequired() ? 'true' : null"
        (input)="onInput($event)"
        (blur)="markTouched()"
      />
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
  `,
})
export class EmrDateField extends EmrControlBase<string> {
  readonly kind = input<'date' | 'datetime-local'>('date');
  readonly min = input<string>();
  readonly max = input<string>();

  protected onInput(event: Event): void {
    const text = (event.target as HTMLInputElement).value;
    this.setValue(text === '' ? null : text);
  }
}
