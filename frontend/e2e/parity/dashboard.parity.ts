import { test } from '@playwright/test';
import { WIDTHS, compare, newPair, openAngular, openReference, writeReport } from './parity-lib';

// Full-screen comparison of the dashboard (nothing masked).
test.describe.configure({ mode: 'serial' });

for (const width of WIDTHS) {
  test(`dashboard @ ${width}px`, async ({ browser }) => {
    const { ctx, reference, angular } = await newPair(browser, width);
    try {
      await openReference(reference, '#/dashboard', '.att-item, .kpis');
      await openAngular(angular, '/dashboard', '.kpis');
      const r = await compare('dashboard', width, reference, angular);
      console.log(`dashboard ${width}px: ${r.diffPercent}% (${r.diffPixels}px)`);
    } finally {
      await ctx.close();
    }
  });
}

test.afterAll(() => writeReport());
