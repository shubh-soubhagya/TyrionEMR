import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { EmrPageHeader } from '@layout/page-header/page-header';

// Placeholder: the searchable patient table is built in Phase 6.
@Component({
  selector: 'emr-patient-list-page',
  imports: [EmrPageHeader],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-page-header title="Patients" subtitle="Search by name or patient ID, then open a chart." />
    @if (q(); as term) {
      <p class="muted">Search term from the URL: {{ term }}</p>
    }
  `,
})
export class PatientListPage {
  /** `?q=` query param, bound by withComponentInputBinding. */
  readonly q = input<string>();
}
