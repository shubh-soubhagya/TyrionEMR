import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

// Placeholder: the real sign-up form is built in Phase 5.
@Component({
  selector: 'emr-signup-page',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="view">
      <h1>Create a clinician account</h1>
      <p class="muted">Placeholder. <a routerLink="/login">Sign in</a></p>
    </main>
  `,
  styles: `
    .view {
      padding: var(--space-24);
    }
  `,
})
export class SignupPage {}
