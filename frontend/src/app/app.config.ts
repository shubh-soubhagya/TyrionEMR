import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Route params and route `data` arrive as component inputs (e.g. `id`, `title`).
    provideRouter(routes, withComponentInputBinding()),
  ],
};
