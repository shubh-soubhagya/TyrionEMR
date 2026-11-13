import { HttpContextToken, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';
import { ApiError } from '../api/api-error';
import { isApiUrl, isAuthUrl } from '../api/endpoints';
import { AuthService } from './auth.service';

/** Marks the one retry, so a request is never retried twice. */
const RETRIED = new HttpContextToken<boolean>(() => false);

const EXPIRED = new Set(['TOKEN_EXPIRED', 'UNAUTHENTICATED']);

/**
 * On 401 TOKEN_EXPIRED / UNAUTHENTICATED from a non-auth route: refresh (single-flight in AuthService), retry the
 * request once with the new token. If the refresh fails the session is already cleared; the person goes to the
 * sign-in page and comes back to where they were (`returnUrl`).
 * Sits OUTSIDE the error interceptor, so it sees ApiError, never HttpErrorResponse.
 */
export const refreshInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return next(req).pipe(
    catchError((err: unknown) => {
      const refreshable =
        err instanceof ApiError &&
        err.status === 401 &&
        EXPIRED.has(err.code) &&
        isApiUrl(req.url) &&
        !isAuthUrl(req.url) &&
        !req.context.get(RETRIED);
      if (!refreshable) return throwError(() => err);
      return auth.refresh().pipe(
        switchMap((token) =>
          next(
            req.clone({
              setHeaders: { Authorization: `Bearer ${token}` },
              context: req.context.set(RETRIED, true),
            }),
          ),
        ),
        catchError((refreshErr: unknown) => {
          if (auth.status() === 'anonymous') {
            void router.navigate(['/login'], { queryParams: { returnUrl: router.url } });
          }
          return throwError(() => refreshErr);
        }),
      );
    }),
  );
};
