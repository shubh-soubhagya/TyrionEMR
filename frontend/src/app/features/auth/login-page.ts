import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiError } from '@core/api/api-error';
import { describeError, type ErrorView } from '@core/api/error-messages';
import { AuthService } from '@core/auth/auth.service';
import { safeReturnUrl } from '@core/auth/auth.guard';
import { ToastService } from '@shared/ui/toast/toast.service';
import { EmrPasswordField } from '@shared/ui/password-field/password-field';
import { EmrIcon } from '@shared/ui/icon/icon';
import { environment } from '@env/environment';
import { AuthArt } from './auth-art';

/** Sign-in (reference html:713-750). The demo accounts box is shown only outside production builds. */
@Component({
  selector: 'emr-login-page',
  imports: [ReactiveFormsModule, RouterLink, AuthArt, EmrIcon, EmrPasswordField],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="auth">
      <emr-auth-art />
      <section class="auth-form">
        <div class="auth-card">
          <div class="seg">
            <a class="on" routerLink="/login" aria-current="page">Sign in</a>
            <a routerLink="/signup">Create account</a>
          </div>
          <h2>Sign in to your clinic</h2>
          <p class="muted" style="margin-bottom: 18px">Use your clinic email and password.</p>

          <div aria-live="polite">
            @if (problem(); as p) {
              <div class="alert danger" style="margin-bottom: 14px" role="alert">
                <emr-icon name="alert" [size]="16" />
                <div>
                  {{ p.message }}
                  @if (p.requestId) {
                    <div class="small muted">Reference: {{ p.requestId }}</div>
                  }
                </div>
              </div>
            } @else if (auth.notice(); as notice) {
              <div class="alert warn" style="margin-bottom: 14px" role="status">
                <emr-icon name="alert" [size]="16" />
                <div>{{ notice }}</div>
              </div>
            }
          </div>

          <form [formGroup]="form" novalidate (ngSubmit)="submit()">
            <label class="fld"
              ><span class="fld-l">Email</span>
              <input
                formControlName="email"
                type="email"
                autocomplete="username"
                placeholder="you@clinic.org"
                [class.invalid]="shown('email')"
              />
              <span class="err">{{ shown('email') ? 'Enter a valid email address.' : '' }}</span>
            </label>
            <label class="fld"
              ><span class="fld-l">Password</span>
              <emr-password-field>
                <input
                  formControlName="password"
                  type="password"
                  autocomplete="current-password"
                  [class.invalid]="shown('password')"
                />
              </emr-password-field>
              <span class="err">{{ shown('password') ? 'Enter your password.' : '' }}</span>
            </label>
            <button
              class="btn primary"
              style="width: 100%; justify-content: center; height: 40px"
              type="submit"
              [disabled]="busy()"
              [attr.aria-busy]="busy()"
            >
              Sign in
            </button>
          </form>

          @if (demo) {
            <div class="demo-box">
              <b>Demo accounts</b>
              <div class="row" style="margin-top: 8px">
                <button class="btn sm" type="button" (click)="fill('dr.rao@nephrocare.demo')">
                  Use clinician account
                </button>
                <button class="btn sm" type="button" (click)="fill('dr.malhotra@nephrocare.demo')">
                  Use second clinician
                </button>
              </div>
              <p class="small muted" style="margin-top: 8px">
                Five wrong passwords lock an account for 15 minutes.
              </p>
            </div>
          }
        </div>
      </section>
    </main>
  `,
})
export class LoginPage {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;

  /** Where to go after signing in; bound from the query string. Only an in-app path is honoured. */
  readonly returnUrl = input<string>();

  protected readonly demo = !environment.production;
  protected readonly busy = signal(false);
  protected readonly problem = signal<ErrorView | null>(null);
  private readonly submitted = signal(false);

  protected readonly form = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected shown(name: 'email' | 'password'): boolean {
    const c = this.form.controls[name];
    return c.invalid && (c.touched || this.submitted());
  }

  protected fill(email: string): void {
    this.form.setValue({ email, password: 'Nephro#2026' });
  }

  protected submit(): void {
    this.submitted.set(true);
    this.problem.set(null);
    if (this.form.invalid || this.busy()) return;
    this.busy.set(true);
    const { email, password } = this.form.getRawValue();
    this.auth.login(email, password).subscribe({
      next: (user) => {
        this.busy.set(false);
        this.toast.show('Signed in as ' + user.fullName + '.', 'ok');
        void this.router.navigateByUrl(safeReturnUrl(this.returnUrl()));
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.problem.set(
          e instanceof ApiError
            ? describeError(e)
            : { message: 'Something went wrong. Please try again.', requestId: null },
        );
      },
    });
  }
}
