const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* An oversized image passes every other spec in this repo: it is on screen, in
 * the right place, and looks correct. Only its weight is wrong, and nothing
 * else here measures that. */

// 2x covers a retina screen; the extra 1x is slack for a card that grows at a
// breakpoint this viewport does not hit.
const MAX_PIXEL_RATIO = 3;

/* Both signals, or neither. Ratio alone flags a 20 KB icon drawn at 64px,
   where the fix saves nothing and costs high-DPR headroom. Bytes alone flag a
   photo that is genuinely being shown large. What is worth failing a build
   over is a heavy file painted into a small box. */
const HEAVY_BYTES = 120_000;

const ROUTES = [
  { path: '/', label: 'the tools index' },
  { path: '/ea-explorer/words/', label: 'EA — in their own words' },
  { path: '/ea-explorer/words/opener.html', label: 'the EA opener' },
  { path: '/about/', label: 'about' },
];

for (const { path, label } of ROUTES) {
  test(`${label} sends no heavy image into a small box`, async ({ page }) => {
    const bytes = new Map();
    page.on('response', (res) => {
      const h = res.headers();
      if (/image/.test(h['content-type'] || '')) {
        bytes.set(res.url(), Number(h['content-length'] || 0));
      }
    });

    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto(HOST + path, { waitUntil: 'load' });
    await page.waitForTimeout(3500);

    const painted = await page.evaluate((ratio) =>
      [...document.images]
        // A lazy image below the fold has no box yet — not this spec's business.
        .filter((i) => i.naturalWidth > 0 && i.getBoundingClientRect().width > 1)
        .filter((i) => i.naturalWidth > i.getBoundingClientRect().width * ratio)
        .map((i) => ({
          src: i.src,
          natural: i.naturalWidth,
          shown: Math.round(i.getBoundingClientRect().width),
        })),
      MAX_PIXEL_RATIO);

    const offenders = painted
      .filter((p) => (bytes.get(p.src) || 0) > HEAVY_BYTES)
      .map((p) => `${new URL(p.src).pathname.split('/').pop()}: ` +
        `${Math.round((bytes.get(p.src) || 0) / 1024)} KB, ` +
        `${p.natural}px sent, ${p.shown}px painted`);

    expect(offenders, `heavy and oversized on ${path}:\n  ${offenders.join('\n  ')}`)
      .toEqual([]);
  });
}

/* The rule above cannot catch a correctly-sized image that is simply an
   enormous file, so this weighs the whole page. Loose on purpose — a tripwire,
   not a style guide. */
test('the tools index stays under its image budget', async ({ page }) => {
  const BUDGET_MB = 2.5;

  await page.setViewportSize({ width: 1400, height: 1000 });
  let bytes = 0;
  const seen = new Set();
  page.on('response', (res) => {
    const h = res.headers();
    if (!/image/.test(h['content-type'] || '')) return;
    if (seen.has(res.url())) return;
    seen.add(res.url());
    bytes += Number(h['content-length'] || 0);
  });

  await page.goto(HOST + '/', { waitUntil: 'load' });
  // The cards are lazy: scroll the list so the budget covers what a reader who
  // reaches the bottom actually pays.
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 600) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
  });
  await page.waitForTimeout(2500);

  expect(bytes / 1e6, `tools index shipped ${(bytes / 1e6).toFixed(2)} MB of images`)
    .toBeLessThan(BUDGET_MB);
});
