// Screenshots for the submission (HLD section 21 item 6), taken from the running stack with the seeded data.
// They are written to /shots, which the `flow` compose service maps to docs/screenshots/ at the repo root.
import { expect, test, type Page } from '@playwright/test';

const SHOTS = '/shots';

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill('dr.rao@nephrocare.demo');
  await page.getByLabel('Password').fill('Nephro#2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL(/\/patients/);
}

async function openPatient(page: Page, mrn: string, tab = 'overview'): Promise<void> {
  await page.goto(`/patients?q=${mrn}`);
  await page.locator('tbody tr.click').first().click();
  await expect(page.locator('#pt-shell')).toBeVisible();
  if (tab !== 'overview')
    await page
      .getByRole('link', { name: new RegExp(`^${tab}`) })
      .first()
      .click();
}

const shot = (page: Page, name: string, fullPage = false) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage });

test.describe.configure({ mode: 'serial' });

test('screenshots of every screen the submission shows', async ({ page }) => {
  // 1 sign in
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Sign in to your clinic' })).toBeVisible();
  await shot(page, '01-sign-in');

  await signIn(page);

  // 2 dashboard
  await page.goto('/dashboard');
  await expect(page.locator('.att-item').first()).toBeVisible();
  await expect(page.locator('.hbar').first()).toBeVisible();
  await shot(page, '02-dashboard', true);

  // 3 patient list with sparklines and a filter
  await page.goto('/patients?attention=true');
  await expect(page.locator('tbody emr-spark svg').first()).toBeVisible();
  await expect(page.locator('tbody emr-skeleton')).toHaveCount(0);
  await shot(page, '03-patient-list-filtered', true);

  // 4 overview with the kidney panel
  await openPatient(page, 'PT-000101');
  await expect(page.locator('emr-line-chart svg').first()).toBeVisible();
  await expect(page.locator('.ckd-strip')).toContainText('G3b');
  await shot(page, '04-overview-kidney-panel', true);

  // 5 conditions with the stage mismatch (Lakshmi Iyer: established G4, latest eGFR G3b)
  await openPatient(page, 'PT-000106', 'Conditions');
  await expect(page.getByText('Stage mismatch.')).toBeVisible();
  await shot(page, '05-conditions-stage-mismatch', true);

  // 6 encounter form
  await openPatient(page, 'PT-000101', 'Encounters');
  await page.getByRole('button', { name: 'New encounter' }).first().click();
  await expect(page.locator('.modal')).toBeVisible();
  await page.getByLabel(/Chief complaint/).fill('Routine review');
  await page.locator('.vit label:nth-child(1) input').fill('138');
  await page.locator('.vit label:nth-child(2) input').fill('86');
  await shot(page, '06-encounter-form');
  await page.locator('.backdrop').click({ position: { x: 4, y: 4 } });

  // 7 labs: table with flags, 8 add-report modal with the live preview, 9 trend charts
  await page.getByRole('link', { name: /^Labs/ }).click();
  await expect(page.locator('.latest-grid .lt')).toHaveCount(8);
  await expect(page.locator('emr-line-chart svg').first()).toBeVisible();
  await shot(page, '07-labs-table-and-trends', true);
  await page.locator('emr-line-chart').first().scrollIntoViewIfNeeded();
  await page
    .locator('.grid.g2')
    .first()
    .screenshot({ path: `${SHOTS}/09-trend-charts.png` });
  await page.getByRole('button', { name: 'Add lab report' }).first().click();
  const rows = page.locator('.lab-row');
  await rows.nth(0).locator('select[aria-label=Unit]').selectOption({ label: 'µmol/L' });
  await rows.nth(0).locator('input[aria-label=Value]').fill('150');
  await rows.nth(1).locator('input[aria-label=Value]').fill('38');
  await expect(rows.nth(0).locator('.lab-prev')).toContainText('= 1.695 mg/dL');
  await shot(page, '08-add-lab-report-preview');
  await page.locator('.backdrop').click({ position: { x: 4, y: 4 } });

  // 10 AI summary: running, completed, a source chip opening a record, then degraded and failed (demo scenarios)
  await openPatient(page, 'PT-000104');
  await page.locator('nav.tabs a.ai-tab').click();
  await expect(page.locator('#ai-pane')).toBeVisible();
  await page
    .getByRole('button', { name: /Generate summary|Regenerate/ })
    .first()
    .click();
  await expect(page.locator('.steps')).toBeVisible();
  await shot(page, '10-ai-summary-running');
  await expect(page.locator('.ai-banner')).toBeVisible({ timeout: 30_000 });
  await shot(page, '11-ai-summary-completed', true);
  await page.locator('.chip.ref', { hasText: 'Encounter' }).first().click();
  await expect(page.locator('.modal')).toContainText('Encounter on');
  await shot(page, '14-ai-source-chip-opens-record');
  await page.locator('.backdrop').click({ position: { x: 4, y: 4 } });

  await page.locator('details.demo-opt summary').click();
  await page.locator('details.demo-opt select').selectOption('timeout');
  await page.getByRole('button', { name: 'Regenerate' }).click();
  await expect(page.getByText('The AI narrative is unavailable right now.')).toBeVisible({
    timeout: 30_000,
  });
  await shot(page, '12-ai-summary-degraded', true);

  await page.locator('details.demo-opt select').selectOption('upstream');
  await page.getByRole('button', { name: 'Regenerate' }).click();
  await expect(page.getByText('The summary could not be created.')).toBeVisible({
    timeout: 30_000,
  });
  await shot(page, '13-ai-summary-failed', true);
});
