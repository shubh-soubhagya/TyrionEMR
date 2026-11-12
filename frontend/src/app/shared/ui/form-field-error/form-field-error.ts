import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ValidationErrors } from '@angular/forms';
import { firstErrorMessage } from '../../validators/error-messages';

/** Red helper line under a field (html `.err`). Renders nothing when there is no error. */
@Component({
  selector: 'emr-form-field-error',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `@if (message(); as text) {
    <span class="err" [attr.id]="id()">{{ text }}</span>
  }`,
  styles: `
    :host {
      display: contents;
    }
    .err {
      font-size: var(--fs-12);
      color: var(--color-danger-600);
    }
  `,
})
export class EmrFormFieldError {
  readonly errors = input<ValidationErrors | null | undefined>(null);
  /** Id for the field's `aria-describedby`. */
  readonly id = input<string>();
  protected readonly message = computed(() => firstErrorMessage(this.errors()));
}
