import { ChangeDetectionStrategy, Component, input } from '@angular/core';

// One shared placeholder for all six tabs; each tab gets its own lazy component later.
@Component({
  selector: 'emr-patient-tab-placeholder',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<h2>{{ title() }}</h2>
    <p class="muted">Placeholder.</p>`,
})
export class PatientTabPlaceholder {
  /** From route `data`, bound by withComponentInputBinding. */
  readonly title = input.required<string>();
}
