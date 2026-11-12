import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrFormFieldError } from '../form-field-error/form-field-error';
import { EmrControlBase } from '../forms/control-base';

/** Multi-line input (html `.fld textarea`: min-height 70px, resize vertical, line-height 1.45). */
@Component({
  selector: 'emr-textarea',
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
      <textarea
        class="control"
        [class.invalid]="showError()"
        [value]="value() ?? ''"
        [disabled]="disabled()"
        [attr.maxlength]="maxlength()"
        [attr.aria-invalid]="showError() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="isRequired() ? 'true' : null"
        (input)="onInput($event)"
        (blur)="markTouched()"
      ></textarea>
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
    textarea {
      resize: vertical;
      min-height: 70px;
      line-height: 1.45;
    }
  `,
})
export class EmrTextarea extends EmrControlBase<string> {
  protected onInput(event: Event): void {
    this.setValue((event.target as HTMLTextAreaElement).value);
  }

  readonly maxlength = input<number>();
}
