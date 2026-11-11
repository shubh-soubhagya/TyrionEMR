import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'emr-not-found-page',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="view">
      <h1>Page not found</h1>
      <p class="muted">The page you asked for does not exist.</p>
      <p><a routerLink="/dashboard">Back to dashboard</a></p>
    </main>
  `,
  styles: `
    .view {
      padding: var(--space-24);
    }
  `,
})
export class NotFoundPage {}
