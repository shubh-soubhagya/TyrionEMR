import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrFormFieldError } from '../form-field-error/form-field-error';
import { EmrControlBase } from '../forms/control-base';

/**
 * Single-line input with label, hint, error and optional prefix/suffix (for example a unit such
 * as "mmHg"). With `type="number"` the form receives a number (or null when empty).
 */
@Component({
  selector: 'emr-text-field',
  imports: [EmrFormFieldError],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './text-field.html',
  styleUrl: './text-field.scss',
})
export class EmrTextField extends EmrControlBase<string | number> {
  readonly type = input<'text' | 'email' | 'password' | 'number' | 'tel'>('text');
  readonly placeholder = input('');
  readonly autocomplete = input<string>();
  readonly prefix = input<string>();
  readonly suffix = input<string>();
  readonly step = input<string>();

  protected displayValue(): string {
    const v = this.value();
    return v === null || v === undefined ? '' : String(v);
  }

  protected onInput(event: Event): void {
    const el = event.target as HTMLInputElement;
    if (this.type() === 'number') {
      this.setValue(el.value === '' ? null : el.valueAsNumber);
    } else {
      this.setValue(el.value);
    }
  }
}
