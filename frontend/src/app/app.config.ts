import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withRouterConfig } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { authInterceptor } from '@core/auth/auth.interceptor';
import { refreshInterceptor } from '@core/auth/refresh.interceptor';
import { errorInterceptor } from '@core/http/error.interceptor';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Order matters (first = outermost): the bearer is added, a 401 triggers one refresh-and-retry, and the
    // innermost interceptor has already turned the error envelope into an ApiError by then.
    provideHttpClient(
      withFetch(),
      withInterceptors([authInterceptor, refreshInterceptor, errorInterceptor]),
    ),
    // A reload tries the refresh cookie once before the first route is activated.
    provideAppInitializer(() => inject(AuthService).restoreSession()),
    // Route params and route `data` arrive as component inputs (e.g. `id`, `title`).
    provideRouter(
      routes,
      withComponentInputBinding(),
      // Child tabs also receive the parent's :id as an input.
      withRouterConfig({ paramsInheritanceStrategy: 'always' }),
    ),
  ],
};
