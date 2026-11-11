import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

// Placeholder: the real sign-in form is built in Phase 5.
@Component({
  selector: 'emr-login-page',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="view">
      <h1>Sign in</h1>
      <p class="muted">Placeholder. <a routerLink="/signup">Create account</a></p>
    </main>
  `,
  styles: `
    .view {
      padding: var(--space-24);
    }
  `,
})
export class LoginPage {}
