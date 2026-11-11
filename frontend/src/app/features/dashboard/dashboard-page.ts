import { ChangeDetectionStrategy, Component } from '@angular/core';
import { EmrPageHeader } from '@layout/page-header/page-header';

// Placeholder: the dashboard (KPIs, attention list, eGFR distribution) is built in a later phase.
@Component({
  selector: 'emr-dashboard-page',
  imports: [EmrPageHeader],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<emr-page-header title="Dashboard" subtitle="Placeholder page." />`,
})
export class DashboardPage {}
