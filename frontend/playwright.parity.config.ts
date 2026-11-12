import { defineConfig } from '@playwright/test';

// Visual parity check: reference/emr-ui.html vs the Angular app (see e2e/parity/README in the
// project README). Runs inside the `parity` compose service, never on the host.
export default defineConfig({
  testDir: 'e2e/parity',
  testMatch: '**/*.parity.ts',
  workers: 1, // screenshots are compared one at a time; also keeps the report deterministic
  timeout: 90_000,
  reporter: 'list',
  use: {
    browserName: 'chromium',
    deviceScaleFactor: 1,
    colorScheme: 'light',
    reducedMotion: 'reduce', // the HTML and the app both honour prefers-reduced-motion
  },
});
