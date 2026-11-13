import { defineConfig } from '@playwright/test';

// End-to-end flow and screenshots against the RUNNING stack (`make up` at the repo root, then the web service here).
// Runs inside the `flow` compose service (Playwright image), never on the host.
//
// The app must be opened as http://localhost:4200: auth-svc and the gateway only accept that origin (CORS_ALLOWED_ORIGINS),
// and the refresh cookie is Secure, which a browser only accepts for localhost or https. Inside the container "localhost"
// is the container itself, so Chromium is told to resolve it to the host machine instead.
export default defineConfig({
  testDir: 'e2e/flow',
  testMatch: '**/*.e2e.ts',
  workers: 1, // the flow writes to the shared dev database; one test at a time
  timeout: 180_000,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:4200',
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: 'light',
    reducedMotion: 'reduce',
    launchOptions: { args: ['--host-resolver-rules=MAP localhost host.docker.internal'] },
  },
});
