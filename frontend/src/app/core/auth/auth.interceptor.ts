import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AUTH, isApiUrl, isAuthUrl } from '../api/endpoints';
import { AuthService } from './auth.service';

/** The four calls that need no token (the gateway's public list). */
const PUBLIC = new Set<string>([AUTH.login, AUTH.signup, AUTH.refresh, AUTH.logout]);

/**
 * Adds the bearer token to requests for THIS app's API only (never to any other URL), and asks the browser to send
 * the refresh cookie on /api/auth/* only (the cookie's Path is /api/auth, so nothing else would receive it anyway).
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isApiUrl(req.url)) return next(req);
  const token = inject(AuthService).accessToken();
  const bearer = token !== null && !PUBLIC.has(req.url.split('?')[0] ?? req.url);
  return next(
    req.clone({
      ...(bearer ? { setHeaders: { Authorization: `Bearer ${token}` } } : {}),
      ...(isAuthUrl(req.url) ? { withCredentials: true } : {}),
    }),
  );
};
