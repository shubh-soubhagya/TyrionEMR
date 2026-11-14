// The whole flow of the assignment against the real stack, with the seeded data only (HLD section 21 item 6):
// sign in, dashboard, global search, open Ramesh Kulkarni, add an encounter (draft, then finalize with "add to problem
// list"), add a lab report with a creatinine in umol/L, see the trend update, generate an AI summary (mock), open a source
// chip, sign out, reload shows the sign-in page, sign in again and a reload keeps the session (silent refresh).
import { expect, test, type Page } from '@playwright/test';

const DEMO = { email: 'dr.rao@nephrocare.demo', password: 'Nephro#2026' };

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(DEMO.email);
  await page.getByLabel('Password').fill(DEMO.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL(/\/patients/);
}

test('sign in to AI summary and back out, with the data written by the user', async ({ page }) => {
  const stamp = new Date().toISOString().slice(11, 19).replace(/:/g, '');
  const complaint = `E2E follow-up ${stamp}`;
  const consoleErrors: string[] = [];
  page.on('console', (m) => {
    // the one 401 of the first silent refresh, before anyone is signed in, is expected (the cookie is HttpOnly)
    if (m.type() === 'error' && !m.text().includes('401')) consoleErrors.push(m.text());
  });

  // 1. a visitor is sent to the sign-in page and comes back to where they were going
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/login\?returnUrl=%2Fdashboard/);
  await signIn(page);

  // 2. dashboard: the numbers come from the services
  await page.goto('/dashboard');
  await expect(page.locator('.att-item').first()).toBeVisible();
  await expect(page.locator('h1.greet')).toContainText('Dr. Anita Rao');

  // 3. global search, open Ramesh Kulkarni
  await page.locator('header input[aria-label="Search patients"]').fill('Kulkarni');
  await page.locator('header input[aria-label="Search patients"]').press('Enter');
  await expect(page).toHaveURL(/\/patients\?q=Kulkarni/);
  await page.locator('tbody tr.click', { hasText: 'Ramesh Kulkarni' }).click();
  await expect(page.locator('.pt-head h1')).toHaveText('Ramesh Kulkarni');

  // 4. encounter: save a draft, reopen it, finalize with a diagnosis added to the problem list
  await page.getByRole('link', { name: /^Encounters/ }).click();
  await page.getByRole('button', { name: 'New encounter' }).first().click();
  await page.getByLabel(/Chief complaint/).fill(complaint);
  await page.locator('textarea[formcontrolname=assessment]').fill('Stable on current treatment.');
  await page.locator('textarea[formcontrolname=plan]').fill('Continue; repeat labs in 3 months.');
  await page.getByRole('button', { name: 'Add diagnosis' }).click();
  await page
    .locator('.dx-row input[formcontrolname=desc]')
    .fill(`Anemia in chronic kidney disease ${stamp}`);
  // no ICD-10 code on purpose: the server links a diagnosis that matches one already on the problem list instead of
  // adding it, and this test must be repeatable, so the description (unique per run) is what identifies it
  await page.locator('.dx-row input[type=checkbox]').check();
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.locator('.toast', { hasText: 'Draft saved.' })).toBeVisible();
  const draftRow = page.locator('tbody tr', { hasText: complaint });
  await expect(draftRow).toContainText('Draft');
  await draftRow.click();
  await expect(page.locator('input[formcontrolname=cc]')).toHaveValue(complaint);
  await page.getByRole('button', { name: 'Finalize encounter' }).click();
  await page.getByRole('button', { name: 'Finalize', exact: true }).click();
  await expect(page.locator('.toast', { hasText: 'added to the problem list' })).toBeVisible();
  await expect(page.locator('tbody tr', { hasText: complaint })).toContainText('Final');

  // 5. lab report with creatinine in umol/L: the preview converts, the history shows how it was entered
  await page.getByRole('link', { name: /^Labs/ }).click();
  await expect(page.locator('.latest-grid .lt')).toHaveCount(8);
  // the Labs tab pill is lab-svc's result_count; a report with two results raises it by 2 without a reload
  const labsPill = page.getByRole('link', { name: /^Labs/ }).locator('.ct');
  await expect(labsPill).toBeVisible();
  const pillBefore = Number(await labsPill.innerText());
  await page.getByRole('button', { name: 'Add lab report' }).first().click();
  const rows = page.locator('.lab-row');
  await rows.nth(0).locator('select[aria-label=Unit]').selectOption({ label: 'µmol/L' });
  await rows.nth(0).locator('input[aria-label=Value]').fill('170');
  await expect(rows.nth(0).locator('.lab-prev')).toContainText('= 1.921 mg/dL');
  await rows.nth(1).locator('input[aria-label=Value]').fill('36');
  await page.getByRole('button', { name: 'Save lab report' }).click();
  await expect(
    page.locator('.toast', { hasText: 'Lab report saved with 2 results' }),
  ).toBeVisible();
  await expect(labsPill).toHaveText(String(pillBefore + 2));
  const history = page.locator('.panel', { hasText: 'Result history' });
  await expect(history.locator('tbody tr', { hasText: '170 µmol/L' }).first()).toBeVisible();
  await expect(page.locator('.latest-grid .lt').first()).toContainText('1.92');

  // 6. AI summary with the mock provider; a source chip opens the cited record
  await page.locator('nav.tabs a.ai-tab').click();
  await page
    .getByRole('button', { name: /Generate summary|Regenerate/ })
    .first()
    .click();
  await expect(page.locator('.ai-banner')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.disclaimer')).toContainText(
    'AI-generated summary for clinician review only',
  );
  await page.locator('.chip.ref', { hasText: 'Encounter' }).first().click();
  await expect(page.locator('.modal')).toContainText('Encounter on');
  await page.locator('.backdrop').click({ position: { x: 4, y: 4 } });

  // 7. sign out; a reload shows the sign-in page
  await page.locator('.user-btn').click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Sign in to your clinic' })).toBeVisible();

  // 8. sign in again; reloading any page keeps the session (the silent refresh)
  await signIn(page);
  await page.goto('/patients?q=Kulkarni');
  await page.reload();
  await expect(page.locator('.user-btn')).toContainText('Dr. Anita Rao');
  await expect(page.locator('tbody tr.click').first()).toBeVisible();

  expect(consoleErrors).toEqual([]);
});
