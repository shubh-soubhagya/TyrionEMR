import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Only a path inside this app is a valid `returnUrl`. A full URL ("https://evil.example"), a protocol-relative one
 * ("//evil.example") or a backslash trick would make the sign-in page an open redirect.
 */
export function safeReturnUrl(raw: string | null | undefined, fallback = '/patients'): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return fallback;
  if (/^\/(login|signup)(\/|\?|$)/.test(raw)) return fallback;
  if ([...raw].some((c) => c.charCodeAt(0) < 32)) return fallback; // control characters
  return raw;
}

/** Every app page: signed-in people only; others go to /login and come back afterwards. */
export const authGuard: CanActivateFn = (_route, state): boolean | UrlTree => {
  if (inject(AuthService).isAuthenticated()) return true;
  return inject(Router).createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** /login and /signup: a signed-in person goes straight to the app. */
export const guestGuard: CanActivateFn = (): boolean | UrlTree =>
  inject(AuthService).isAuthenticated() ? inject(Router).createUrlTree(['/patients']) : true;
