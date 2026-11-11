import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { EmrPageHeader } from '@layout/page-header/page-header';

// Tab keys and labels from the HTML (html:836). The real tab bar and patient header are Phase 7.
const TABS = [
  { path: 'overview', label: 'Overview' },
  { path: 'conditions', label: 'Conditions' },
  { path: 'meds', label: 'Medications and allergies' },
  { path: 'encounters', label: 'Encounters' },
  { path: 'labs', label: 'Labs' },
  { path: 'ai', label: 'AI summary' },
] as const;

@Component({
  selector: 'emr-patient-shell-page',
  imports: [EmrPageHeader, RouterLink, RouterLinkActive, RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <emr-page-header title="Patient chart" [subtitle]="'Patient ' + id()" />
    <nav aria-label="Patient chart sections">
      @for (tab of tabs; track tab.path) {
        <a [routerLink]="tab.path" routerLinkActive="active" ariaCurrentWhenActive="page">{{
          tab.label
        }}</a>
      }
    </nav>
    <router-outlet />
  `,
  styles: `
    nav {
      display: flex;
      gap: var(--space-14);
      margin-bottom: var(--space-18);
    }
    .active {
      font-weight: 600;
    }
  `,
})
export class PatientShellPage {
  /** `:id` route param, bound by withComponentInputBinding. */
  readonly id = input.required<string>();
  protected readonly tabs = TABS;
}
