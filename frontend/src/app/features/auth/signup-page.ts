import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiError } from '@core/api/api-error';
import { describeError, type ErrorView } from '@core/api/error-messages';
import { AuthService } from '@core/auth/auth.service';
import { EmrPasswordField } from '@shared/ui/password-field/password-field';
import { EmrIcon } from '@shared/ui/icon/icon';
import { ToastService } from '@shared/ui/toast/toast.service';
import {
  passwordChecks,
  passwordOk,
  ruleLineForServerCode,
  type RuleLine,
} from '@shared/utils/password-rules';
import { startWith } from 'rxjs';
import { AuthArt } from './auth-art';

const sameAsPassword = (c: AbstractControl): ValidationErrors | null => {
  const g = c.parent;
  return g && g.get('password')?.value !== c.value ? { passwordMismatch: true } : null;
};

/** Create account (reference html:713-750). New accounts are clinicians; the server decides everything else. */
@Component({
  selector: 'emr-signup-page',
  imports: [ReactiveFormsModule, RouterLink, AuthArt, EmrIcon, EmrPasswordField],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="auth">
      <emr-auth-art />
      <section class="auth-form">
        <div class="auth-card">
          <div class="seg">
            <a routerLink="/login">Sign in</a>
            <a class="on" routerLink="/signup" aria-current="page">Create account</a>
          </div>
          <h2>Create a clinician account</h2>
          <p class="muted" style="margin-bottom: 18px">
            New accounts are created with the clinician role.
          </p>

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
            }
          </div>

          <form [formGroup]="form" novalidate (ngSubmit)="submit()">
            <label class="fld"
              ><span class="fld-l">Full name</span>
              <input
                formControlName="name"
                autocomplete="name"
                placeholder="Dr. Priya Sharma"
                [class.invalid]="show('name')"
              />
              <span class="err">{{ show('name') ? 'Enter your full name.' : '' }}</span>
            </label>
            <label class="fld"
              ><span class="fld-l">Email</span>
              <input
                formControlName="email"
                type="email"
                autocomplete="username"
                [class.invalid]="show('email') || !!emailTaken()"
              />
              <span class="err">{{
                emailTaken() ?? (show('email') ? 'Enter a valid email address.' : '')
              }}</span>
            </label>
            <label class="fld"
              ><span class="fld-l">Password</span>
              <emr-password-field>
                <input
                  formControlName="password"
                  type="password"
                  autocomplete="new-password"
                  [class.invalid]="show('password')"
                  aria-describedby="pw-rules"
                />
              </emr-password-field>
              <span class="err">{{
                show('password') ? 'Password does not meet the rules below.' : ''
              }}</span>
            </label>
            <div class="pw-rules" id="pw-rules">
              @for (r of rules(); track r.line) {
                <span [class.ok]="r.ok" [class.bad]="!r.ok && show('password')"
                  >{{ r.ok ? '✓ ' : show('password') ? '✗ ' : '' }}{{ r.text }}</span
                >
              }
            </div>
            <label class="fld"
              ><span class="fld-l">Confirm password</span>
              <emr-password-field>
                <input
                  formControlName="confirm"
                  type="password"
                  autocomplete="new-password"
                  [class.invalid]="show('confirm')"
                />
              </emr-password-field>
              <span class="err">{{ show('confirm') ? 'Passwords do not match.' : '' }}</span>
            </label>
            <button
              class="btn primary"
              style="width: 100%; justify-content: center; height: 40px"
              type="submit"
              [disabled]="busy()"
              [attr.aria-busy]="busy()"
            >
              Create account
            </button>
          </form>
        </div>
      </section>
    </main>
  `,
})
export class SignupPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder).nonNullable;

  protected readonly busy = signal(false);
  protected readonly problem = signal<ErrorView | null>(null);
  protected readonly emailTaken = signal<string | null>(null);
  private readonly submitted = signal(false);
  /** Checklist lines the server rejected (422 rule codes), shown as failed even if the local check passes. */
  private readonly serverFailed = signal<ReadonlySet<RuleLine>>(new Set());

  protected readonly form = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(2)]],
    email: ['', [Validators.required, Validators.email]],
    password: [
      '',
      [
        Validators.required,
        (c: AbstractControl) => (passwordOk(c.value as string) ? null : { rules: true }),
      ],
    ],
    confirm: ['', [Validators.required, sameAsPassword]],
  });

  private readonly password = toSignal(
    this.form.controls.password.valueChanges.pipe(startWith('')),
    { initialValue: '' },
  );

  protected readonly rules = computed(() => {
    const c = passwordChecks(this.password());
    const bad = this.serverFailed();
    return [
      {
        line: 'length' as const,
        ok: c.length && !bad.has('length'),
        text: 'At least 10 characters',
      },
      {
        line: 'letterAndDigit' as const,
        ok: c.letterAndDigit && !bad.has('letterAndDigit'),
        text: 'Contains a letter and a number',
      },
      {
        line: 'notCommon' as const,
        ok: c.notCommon && !bad.has('notCommon'),
        text: 'Not a commonly used password',
      },
    ];
  });

  protected show(name: 'name' | 'email' | 'password' | 'confirm'): boolean {
    const c = this.form.controls[name];
    return c.invalid && (c.touched || this.submitted());
  }

  protected submit(): void {
    this.submitted.set(true);
    this.problem.set(null);
    this.emailTaken.set(null);
    this.serverFailed.set(new Set());
    this.form.controls.confirm.updateValueAndValidity();
    if (this.form.invalid || this.busy()) return;
    this.busy.set(true);
    const { name, email, password } = this.form.getRawValue();
    this.auth.signup(name, email, password).subscribe({
      next: (user) => {
        this.busy.set(false);
        this.toast.show('Account created. Welcome, ' + user.fullName + '.', 'ok');
        void this.router.navigateByUrl('/patients');
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.fail(e);
      },
    });
  }

  private fail(e: unknown): void {
    if (!(e instanceof ApiError)) {
      this.problem.set({ message: 'Something went wrong. Please try again.', requestId: null });
      return;
    }
    if (e.code === 'EMAIL_TAKEN') {
      this.emailTaken.set(e.message);
    } else if (e.code === 'VALIDATION_ERROR') {
      const lines = new Set<RuleLine>();
      for (const d of e.details) {
        const line = d.code ? ruleLineForServerCode(d.code) : null;
        if (line) lines.add(line);
      }
      this.serverFailed.set(lines);
      this.form.controls.password.markAsTouched();
      if (lines.size === 0) this.problem.set(describeError(e));
    } else {
      // 403 SIGNUP_DISABLED, 429, 503 ...: a page-level alert
      this.problem.set(describeError(e));
    }
  }
}
