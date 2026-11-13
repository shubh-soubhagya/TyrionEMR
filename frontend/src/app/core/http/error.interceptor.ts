import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';
import { toApiError } from '../api/api-error';

/**
 * Turns every failed response into an ApiError (the envelope as one object). It shows nothing itself:
 * the screen that asked decides how to present the error (panel state, form field, toast).
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(
    catchError((err: unknown) =>
      throwError(() => (err instanceof HttpErrorResponse ? toApiError(err) : err)),
    ),
  );
