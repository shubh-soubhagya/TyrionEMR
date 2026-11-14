import { Directive } from '@angular/core';

/**
 * For numeric inputs that can never be negative (vitals, lab values): stops the keys that make a number negative or
 * exponential (`-`, `+`, `e`, `E`) from being typed. The field's own min and max, and the form validation, still decide
 * what is accepted; this only removes the keystrokes that are never right. ⚑ not in the reference HTML.
 */
@Directive({
  selector: 'input[emrNonNegative]',
  host: { '(keydown)': 'onKey($event)' },
})
export class EmrNonNegative {
  private static readonly BLOCKED = new Set(['-', '+', 'e', 'E']);

  protected onKey(e: KeyboardEvent): void {
    if (EmrNonNegative.BLOCKED.has(e.key)) e.preventDefault();
  }
}
