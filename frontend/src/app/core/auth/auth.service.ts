import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import {
  Observable,
  catchError,
  defer,
  finalize,
  map,
  of,
  shareReplay,
  switchMap,
  tap,
  throwError,
  timer,
} from 'rxjs';
import { ApiError } from '../api/api-error';
import type { LoginRequestDto, SignupRequestDto, TokenDto, UserDto } from '../api/dto/auth.dto';
import { AUTH } from '../api/endpoints';

export type AuthStatus = 'unknown' | 'authenticated' | 'anonymous';

export interface SessionUser {
  readonly id: string;
  readonly email: string;
  readonly fullName: string;
  /** Label shown beside the name: 'clinician' is a Nephrologist in this product. */
  readonly roleLabel: string;
}

const ROLE_LABELS: Readonly<Record<string, string>> = { clinician: 'Nephrologist' };

/** Refresh codes after which the cookie is gone and the person must sign in again. */
const SIGN_IN_AGAIN = new Set(['REFRESH_REUSED', 'REFRESH_INVALID', 'REFRESH_EXPIRED']);

/** ai-svc rejects a token with less than 30 s left, so the app refreshes first when less than 60 s remain. */
export const AI_MIN_VALIDITY_MS = 60_000;

/**
 * The session (frontend/docs/decisions.md D3). The access token lives in memory only, in a signal: never in
 * localStorage or sessionStorage, so a script injected into the page cannot read it from storage. The refresh token
 * is an HttpOnly cookie the browser sends to /api/auth/* by itself, so a reload restores the session by calling
 * refresh once at start.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private readonly userState = signal<SessionUser | null>(null);
  private readonly tokenState = signal<string | null>(null);
  private readonly statusState = signal<AuthStatus>('unknown');
  private readonly noticeState = signal<string | null>(null);
  private expiresAtMs = 0;
  private inflight: Observable<string> | null = null;

  readonly user = this.userState.asReadonly();
  readonly accessToken = this.tokenState.asReadonly();
  readonly status = this.statusState.asReadonly();
  readonly isAuthenticated = computed(() => this.statusState() === 'authenticated');
  /** Why the last session ended when the server said so (for example "your session was ended for safety"). */
  readonly notice = this.noticeState.asReadonly();

  /** Overridable in tests. */
  protected now(): number {
    return Date.now();
  }

  /** Called once by the app initializer: a reload tries the refresh cookie; no cookie means anonymous. */
  restoreSession(): Promise<void> {
    return new Promise<void>((resolve) => {
      this.refresh().subscribe({ next: () => resolve(), error: () => resolve() });
    });
  }

  login(email: string, password: string): Observable<SessionUser> {
    const body: LoginRequestDto = { email: email.trim(), password };
    return this.http.post<TokenDto>(AUTH.login, body).pipe(map((t) => this.accept(t)));
  }

  signup(fullName: string, email: string, password: string): Observable<SessionUser> {
    const body: SignupRequestDto = { full_name: fullName.trim(), email: email.trim(), password };
    return this.http.post<TokenDto>(AUTH.signup, body).pipe(map((t) => this.accept(t)));
  }

  /** Tells the server to drop the refresh cookie, then forgets the session. The session is cleared even if the call fails. */
  logout(): Observable<void> {
    return this.http.post<void>(AUTH.logout, null).pipe(
      map(() => undefined),
      catchError(() => of(undefined)),
      finalize(() => this.clear(null)),
    );
  }

  changePassword(currentPassword: string, newPassword: string): Observable<void> {
    return this.http
      .post<void>(AUTH.password, { current_password: currentPassword, new_password: newPassword })
      .pipe(map(() => undefined));
  }

  /**
   * Gets a new access token. Single-flight: every caller that arrives while a refresh is running shares it, so
   * three requests failing at once cause ONE POST /auth/refresh (the server rotates the cookie on each call, and a
   * second call with the old cookie would look like token theft).
   */
  refresh(): Observable<string> {
    if (this.inflight) return this.inflight;
    const shared = defer(() => this.refreshWithRaceRetry()).pipe(
      finalize(() => {
        this.inflight = null;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    this.inflight = shared;
    return shared;
  }

  /** Refreshes first when the token has less than `minValidityMs` left; otherwise does nothing. */
  ensureFresh(minValidityMs = AI_MIN_VALIDITY_MS): Observable<void> {
    const left = this.expiresAtMs - this.now();
    if (this.tokenState() !== null && left > minValidityMs) return of(undefined);
    return this.refresh().pipe(map(() => undefined));
  }

  /** Drops the session in memory (used when a refresh failed or after sign out). */
  clear(notice: string | null): void {
    this.tokenState.set(null);
    this.userState.set(null);
    this.expiresAtMs = 0;
    this.statusState.set('anonymous');
    this.noticeState.set(notice);
  }

  private refreshWithRaceRetry(): Observable<string> {
    return this.postRefresh().pipe(
      catchError((e: unknown) => {
        // Two tabs refreshed at the same moment: the cookie is still valid, so wait a moment and try once more.
        if (e instanceof ApiError && e.code === 'REFRESH_RACE') {
          return timer(50 + Math.floor(Math.random() * 200)).pipe(
            switchMap(() => this.postRefresh()),
          );
        }
        return throwError(() => e);
      }),
      catchError((e: unknown) => {
        const notice = e instanceof ApiError && SIGN_IN_AGAIN.has(e.code) ? e.message : null;
        this.clear(notice);
        return throwError(() => e);
      }),
    );
  }

  private postRefresh(): Observable<string> {
    return this.http.post<TokenDto>(AUTH.refresh, null).pipe(
      tap((t) => this.accept(t)),
      map((t) => t.access_token),
    );
  }

  private accept(t: TokenDto): SessionUser {
    const user = toSessionUser(t.user);
    this.tokenState.set(t.access_token);
    this.userState.set(user);
    this.expiresAtMs = this.now() + t.expires_in * 1000;
    this.statusState.set('authenticated');
    this.noticeState.set(null);
    return user;
  }
}

export function toSessionUser(u: UserDto): SessionUser {
  return {
    id: u.id,
    email: u.email,
    fullName: u.full_name,
    roleLabel: ROLE_LABELS[u.role] ?? u.role,
  };
}
