import { ChangeDetectionStrategy, Component } from '@angular/core';
import { EmrControlBase } from '../forms/control-base';

/** Checkbox with inline label (html `.chk`: 16px box, 13.5px text). */
@Component({
  selector: 'emr-checkbox',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label class="chk">
      <input
        type="checkbox"
        [checked]="!!value()"
        [disabled]="disabled()"
        [attr.aria-describedby]="describedBy()"
        (change)="onToggle($event)"
        (blur)="markTouched()"
      />
      <span>{{ label() }}</span>
    </label>
  `,
  styles: `
    :host {
      display: inline-block;
    }
    .chk {
      display: flex;
      align-items: center;
      gap: var(--space-8);
      font-size: var(--fs-13-5);
    }
    input {
      width: 16px;
      height: 16px;
    }
  `,
})
export class EmrCheckbox extends EmrControlBase<boolean> {
  protected onToggle(event: Event): void {
    this.setValue((event.target as HTMLInputElement).checked);
  }
}
