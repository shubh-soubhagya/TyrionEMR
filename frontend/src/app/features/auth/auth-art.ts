import { ChangeDetectionStrategy, Component } from '@angular/core';
import { EmrIcon } from '@shared/ui/icon/icon';

/** The dark left panel of the sign-in and sign-up pages (reference html:715-718). Pure presentation. */
@Component({
  selector: 'emr-auth-art',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'auth-art' },
  template: `
    <div>
      <div class="brand" style="padding: 0 0 40px">
        <span class="logo"><emr-icon name="activity" [size]="20" /></span>
        <div>
          <b>NephroCare</b>
          <small>Nephrology EMR</small>
        </div>
      </div>
      <h1>Kidney care, charted clearly.</h1>
      <ul>
        <li>
          <emr-icon name="users" [size]="20" />
          <div>
            <b>One chart per patient</b>Demographics, problem list, medications, allergies and every
            visit in one place.
          </div>
        </li>
        <li>
          <emr-icon name="flask" [size]="20" />
          <div>
            <b>Kidney function at a glance</b>Creatinine and eGFR trends against reference ranges,
            with the CKD stage beside them.
          </div>
        </li>
        <li>
          <emr-icon name="spark" [size]="20" />
          <div>
            <b>AI summaries you can verify</b>Computed facts and rule findings stay separate from AI
            narrative, and every claim cites its source.
          </div>
        </li>
      </ul>
    </div>
    <svg
      class="trace"
      viewBox="0 0 420 120"
      fill="none"
      stroke="#5fc4cf"
      stroke-width="2.2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <polyline
        points="0,70 60,70 80,30 105,100 130,50 150,70 230,70 250,20 280,110 305,60 325,70 420,70"
      />
    </svg>
  `,
})
export class AuthArt {}
