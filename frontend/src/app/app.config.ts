import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding, withRouterConfig } from '@angular/router';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Route params and route `data` arrive as component inputs (e.g. `id`, `title`).
    provideRouter(
      routes,
      withComponentInputBinding(),
      // Child tabs also receive the parent's :id as an input.
      withRouterConfig({ paramsInheritanceStrategy: 'always' }),
    ),
  ],
};
