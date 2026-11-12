import { test } from '@playwright/test';
import { WIDTHS, compare, newPair, openAngular, openReference, writeReport } from './parity-lib';

// Shell parity: sidebar, top bar, page background and fonts. The HTML opens on the dashboard
// (hash route), so no click is needed to reach the matching view.
test.describe.configure({ mode: 'serial' });

for (const width of WIDTHS) {
  test(`shell @ ${width}px`, async ({ browser }) => {
    const { ctx, reference, angular } = await newPair(browser, width);
    try {
      // HTML: wait for the dashboard's page header (rendered after its simulated API delay).
      await openReference(reference, '#/dashboard', '.page-h', true);
      await openAngular(angular, '/dashboard', 'emr-dashboard-page', true);
      const r = await compare('shell', width, reference, angular);
      console.log(`shell ${width}px: ${r.diffPercent}% (${r.diffPixels}px)`);
    } finally {
      await ctx.close();
    }
  });
}

test.afterAll(() => writeReport());
