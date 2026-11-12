import { Page, test } from '@playwright/test';
import { ANGULAR_ORIGIN, REFERENCE_URL, WIDTHS, compare, newPair, writeReport } from './parity-lib';

// Full-screen comparisons. Pages that need a patient click the same row in both apps (the
// prototype's patient ids are random per load, so we cannot deep-link).
test.describe.configure({ mode: 'serial' });

const PATIENT = 'Ramesh Kulkarni';

interface Screen {
  name: string;
  /** null = the patients list, otherwise the tab label to click inside the chart. */
  tab: string | null;
  ready: string;
}

const SCREENS: Screen[] = [
  { name: 'patients', tab: null, ready: '.pager, .empty' },
  { name: 'overview', tab: 'Overview', ready: '.ckd-strip' },
  { name: 'conditions', tab: 'Conditions', ready: 'text=Nephrology diagnoses' },
  { name: 'meds', tab: 'Medications and allergies', ready: 'h2:has-text("Allergies")' },
  { name: 'encounters', tab: 'Encounters', ready: 'h2:has-text("Encounters")' },
  { name: 'labs', tab: 'Labs', ready: '.ckd-grid' },
  { name: 'ai', tab: 'AI summary', ready: 'text=AI clinical summary' },
];

async function go(page: Page, url: string, screen: Screen) {
  await page.goto(url);
  await page.waitForSelector('.toolbar');
  if (screen.tab !== null) {
    await page.locator(`tr.click:has-text("${PATIENT}")`).first().click();
    await page.waitForSelector('#pt-shell, .crumbs');
    if (screen.tab !== 'Overview') await page.locator(`a.tab:has-text("${screen.tab}")`).click();
  }
  await page.waitForSelector(screen.ready);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
}

const only = process.env['SCREEN'];
for (const screen of SCREENS.filter((s) => !only || s.name === only)) {
  for (const width of WIDTHS) {
    test(`${screen.name} @ ${width}px`, async ({ browser }) => {
      const { ctx, reference, angular } = await newPair(browser, width);
      try {
        await go(reference, `${REFERENCE_URL}#/patients`, screen);
        await go(angular, `${ANGULAR_ORIGIN}/patients`, screen);
        const r = await compare(screen.name, width, reference, angular);
        console.log(`${screen.name} ${width}px: ${r.diffPercent}% (${r.diffPixels}px)`);
      } finally {
        await ctx.close();
      }
    });
  }
}

test.afterAll(() => writeReport());
