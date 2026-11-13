import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding, withRouterConfig } from '@angular/router';
import { errorInterceptor } from '@core/http/error.interceptor';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Auth interceptors join this list in the sign-in phase.
    provideHttpClient(withFetch(), withInterceptors([errorInterceptor])),
    // Route params and route `data` arrive as component inputs (e.g. `id`, `title`).
    provideRouter(
      routes,
      withComponentInputBinding(),
      // Child tabs also receive the parent's :id as an input.
      withRouterConfig({ paramsInheritanceStrategy: 'always' }),
    ),
  ],
};
