import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Page title block (html `.page-h`). Slots:
 *  - `[emr-breadcrumbs]` above the title
 *  - `[emr-page-actions]` on the right (buttons)
 */
@Component({
  selector: 'emr-page-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './page-header.html',
  styleUrl: './page-header.scss',
})
export class EmrPageHeader {
  readonly title = input.required<string>();
  readonly subtitle = input<string>();
}
