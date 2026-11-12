import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrFormFieldError } from '../form-field-error/form-field-error';
import { EmrControlBase } from '../forms/control-base';
import { SelectOption } from '../select/select';

/** Group of native radios under a fieldset legend. */
@Component({
  selector: 'emr-radio-group',
  imports: [EmrFormFieldError],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <fieldset [attr.aria-describedby]="describedBy()">
      <legend class="fld-l">
        {{ label() }}
        @if (isRequired()) {
          <b class="req" aria-hidden="true">*</b>
        }
      </legend>
      @for (option of options(); track option.value) {
        <label class="chk">
          <input
            type="radio"
            [name]="uid"
            [value]="option.value"
            [checked]="option.value === value()"
            [disabled]="disabled()"
            (change)="setValue(option.value)"
            (blur)="markTouched()"
          />
          <span>{{ option.label }}</span>
        </label>
      }
      @if (hint(); as text) {
        <span class="hint" [id]="hintId">{{ text }}</span>
      }
      <emr-form-field-error [errors]="showError() ? errors() : null" [id]="errorId" />
    </fieldset>
  `,
  styles: `
    @use 'fields' as f;
    :host {
      @include f.field;
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-6);
    }
    .chk {
      display: flex;
      align-items: center;
      gap: var(--space-8);
      font-size: var(--fs-13-5);
    }
  `,
})
export class EmrRadioGroup extends EmrControlBase<string> {
  readonly options = input.required<readonly SelectOption[]>();
}
