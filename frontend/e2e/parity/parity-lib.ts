import { Browser, BrowserContext, Page } from '@playwright/test';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

// Shared by every *.parity.ts file, so later phases only describe their screens.

export const WIDTHS = [1440, 1024, 768, 375] as const;
export const VIEWPORT_HEIGHT = 900;

// Container paths (see compose.yaml, service `parity`).
export const REFERENCE_URL = 'file:///reference/emr-ui.html';
export const ANGULAR_ORIGIN = 'http://host.docker.internal:4200';
const OUT_DIR = 'docs/parity';
const FONT_DIR = 'node_modules/@fontsource';

export interface ParityResult {
  screen: string;
  width: number;
  diffPercent: number;
  diffPixels: number;
  totalPixels: number;
}

/**
 * The reference HTML pulls IBM Plex from the Google Fonts CDN. The container has no guarantee of
 * internet access, and a fallback font would swamp every diff. So we answer that request with the
 * same fonts the Angular app self-hosts (@fontsource), embedded as data URIs.
 */
function localFontCss(): string {
  const face = (family: string, pkg: string, slug: string, weight: number) => {
    const file = readFileSync(join(FONT_DIR, pkg, 'files', `${slug}-latin-${weight}-normal.woff2`));
    return (
      `@font-face{font-family:'${family}';font-style:normal;font-weight:${weight};` +
      `font-display:swap;src:url(data:font/woff2;base64,${file.toString('base64')}) format('woff2')}`
    );
  };
  const sans = [400, 500, 600, 700].map((w) =>
    face('IBM Plex Sans', 'ibm-plex-sans', 'ibm-plex-sans', w),
  );
  const mono = [400, 500].map((w) => face('IBM Plex Mono', 'ibm-plex-mono', 'ibm-plex-mono', w));
  return [...sans, ...mono].join('\n');
}

// Hide the page body content so the comparison covers the shell frame only (sidebar and top bar);
// the main area is different on purpose while pages are still placeholders. Layout is preserved.
const MASK_MAIN_CSS = '.view > * { visibility: hidden !important; } #toasts { display: none; }';

export async function newPair(
  browser: Browser,
  width: number,
): Promise<{ ctx: BrowserContext; reference: Page; angular: Page }> {
  const ctx = await browser.newContext({ viewport: { width, height: VIEWPORT_HEIGHT } });
  const css = localFontCss();
  await ctx.route(/fonts\.googleapis\.com/, (route) =>
    route.fulfill({ contentType: 'text/css', body: css }),
  );
  await ctx.route(/fonts\.gstatic\.com/, (route) => route.abort());
  const reference = await ctx.newPage();
  const angular = await ctx.newPage();
  return { ctx, reference, angular };
}

export async function openReference(page: Page, hash: string, readySelector: string, mask = false) {
  await page.goto(`${REFERENCE_URL}${hash}`);
  await page.waitForSelector(readySelector);
  await settle(page, mask);
}

export async function openAngular(page: Page, path: string, readySelector: string, mask = false) {
  await page.goto(`${ANGULAR_ORIGIN}${path}`);
  await page.waitForSelector(readySelector);
  await settle(page, mask);
}

async function settle(page: Page, mask: boolean) {
  if (mask) await page.addStyleTag({ content: MASK_MAIN_CSS });
  await page.evaluate(() => document.fonts.ready);
}

/** Screenshot both pages, save [reference | angular | diff] to docs/parity and return the numbers. */
export async function compare(
  screen: string,
  width: number,
  reference: Page,
  angular: Page,
): Promise<ParityResult> {
  mkdirSync(OUT_DIR, { recursive: true });
  const shotA = PNG.sync.read(await reference.screenshot({ fullPage: true }));
  const shotB = PNG.sync.read(await angular.screenshot({ fullPage: true }));
  const height = Math.max(shotA.height, shotB.height);
  const pad = (img: PNG): PNG => {
    const out = new PNG({ width: img.width, height });
    out.data.fill(0xff);
    PNG.bitblt(img, out, 0, 0, img.width, img.height, 0, 0);
    return out;
  };
  const a = pad(shotA);
  const b = pad(shotB);

  const diff = new PNG({ width: a.width, height: a.height });
  const diffPixels = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.1 });
  const totalPixels = a.width * a.height;

  // Side by side: reference | angular | diff, separated by 8 px grey gutters.
  const gap = 8;
  const out = new PNG({ width: a.width * 3 + gap * 2, height: a.height });
  out.data.fill(0xcc);
  [a, b, diff].forEach((img, i) =>
    PNG.bitblt(img, out, 0, 0, a.width, a.height, i * (a.width + gap), 0),
  );
  writeFileSync(join(OUT_DIR, `${screen}-${width}.png`), PNG.sync.write(out));

  const result: ParityResult = {
    screen,
    width,
    diffPercent: Math.round((diffPixels / totalPixels) * 10000) / 100,
    diffPixels,
    totalPixels,
  };
  writeFileSync(join(OUT_DIR, `${screen}-${width}.json`), JSON.stringify(result));
  return result;
}

/** Rebuild docs/parity/report.md from every result JSON (so each screen's run is kept). */
export function writeReport(): void {
  const rows = readdirSync(OUT_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(readFileSync(join(OUT_DIR, f), 'utf8')) as ParityResult)
    .sort((x, y) => x.screen.localeCompare(y.screen) || y.width - x.width);

  const lines = [
    '# Visual parity report',
    '',
    'Generated by `npm run parity` (see README). Images are `[reference | angular | diff]`.',
    'The page body is masked while pages are placeholders, so only the shell frame is compared.',
    'Diff uses pixelmatch, threshold 0.1.',
    '',
    '| Screen | Width | Diff % | Different pixels | Image |',
    '|---|---|---|---|---|',
    ...rows.map(
      (r) =>
        `| ${r.screen} | ${r.width} | ${r.diffPercent.toFixed(2)} | ${r.diffPixels} / ${r.totalPixels} | ![${r.screen} ${r.width}](${r.screen}-${r.width}.png) |`,
    ),
    '',
  ];
  writeFileSync(join(OUT_DIR, 'report.md'), lines.join('\n'));
}
