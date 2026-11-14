// Chart tooltips with real service data (reference html:1000, 1265, 1300), at 1440 and 375 px. Read-only: it writes nothing
// to the database. The screenshot of a trend-point tooltip is saved for the submission (docs/screenshots/15).
import { expect, test, type Page } from '@playwright/test';

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill('dr.rao@nephrocare.demo');
  await page.getByLabel('Password').fill('Nephro#2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL(/\/patients/);
}

const tooltip = (page: Page) => page.locator('#tooltip.show');

/** Hovers a data point of a Chart.js canvas: the chart writes each point's pixel position to `data-points`. */
async function hoverPoint(page: Page, chart: ReturnType<Page['locator']>, which: 'first' | 'last') {
  const canvas = chart.locator('canvas');
  await expect(canvas).toHaveAttribute('data-points', /\[\{/);
  const pts = JSON.parse((await canvas.getAttribute('data-points')) ?? '[]') as {
    x: number;
    y: number;
  }[];
  const p = which === 'first' ? pts[0] : pts[pts.length - 1];
  if (!p) throw new Error('chart has no points');
  await canvas.hover({ position: { x: p.x, y: p.y } });
}

for (const width of [1440, 375]) {
  test(`tooltips at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 800 });
    const consoleErrors: string[] = [];
    page.on('console', (m) => {
      if (m.type() === 'error' && !m.text().includes('401')) consoleErrors.push(m.text());
    });
    await signIn(page);

    // dashboard bar
    await page.goto('/dashboard');
    const bar = page.locator('.hbar').nth(3);
    await expect(bar).toBeVisible();
    await bar.hover();
    await expect(tooltip(page)).toContainText(
      /\d+ patients? in G3b: Moderately to severely decreased/,
    );

    // list sparkline
    await page.goto('/patients?q=PT-000101');
    const spark = page.locator('tbody svg.spark').first();
    await expect(spark).toBeVisible();
    await spark.hover();
    await expect(tooltip(page)).toContainText(/eGFR [\d.]+ to [\d.]+/);
    await expect(tooltip(page)).toContainText(/\d+ results?, (worsening|improving|stable)/);

    // trend point on the overview kidney panel, then on the labs tab
    await page.locator('tbody tr.click').first().click();
    await expect(page.locator('emr-line-chart canvas').first()).toBeVisible();
    await expect(page.locator('emr-line-chart canvas').first()).toBeVisible();
    await hoverPoint(page, page.locator('emr-line-chart').first(), 'last');
    await expect(tooltip(page)).toContainText(/[\d.]+ (mL\/min\/1\.73m²|mg\/dL)/);
    await expect(tooltip(page)).toContainText(/\d{2} \w{3} \d{4}/);
    if (width === 1440) await page.screenshot({ path: '/shots/15-chart-tooltip.png' });
    // the tooltip stays inside the viewport and hides on leave
    const box = await page.locator('#tooltip').boundingBox();
    expect(box && box.x + box.width <= width).toBe(true);
    await page.mouse.move(2, 2);
    await expect(page.locator('#tooltip.show')).toHaveCount(0);

    await page.getByRole('link', { name: /^Labs/ }).click();
    await expect(page.locator('emr-line-chart canvas').first()).toBeVisible();
    await hoverPoint(page, page.locator('emr-line-chart').first(), 'first');
    await expect(tooltip(page)).toContainText(/[\d.]+ [^\s]+/);

    expect(consoleErrors).toEqual([]);
  });
}
