const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Horizontal overflow is invisible in a screenshot taken at the width that
 * caused it, and on a phone it does not even scroll — the layout viewport
 * widens instead, so `innerWidth` comes back larger than the device and every
 * other measurement is taken against a viewport that does not exist.
 *
 * Both causes found here were the same shape: `flex: 0 0 auto` on something
 * whose width comes from data — a relationship label out of edges.csv, and a
 * row of header links. A flex item that cannot shrink keeps its max-content
 * width no matter how narrow the column is, and `min-width: 0` is needed too,
 * because a flex item's default `min-width: auto` floors it at min-content.
 */

const ALL = [
  '/',
  '/about/',
  '/ea-explorer/',
  '/ea-explorer/network.html',
  // A node whose relationship labels are full sentences — the case that broke.
  '/ea-explorer/network.html#' + encodeURIComponent('institution:inst-066'),
  '/ea-explorer/words/',
  '/ea-explorer/words/opener.html',
  '/noblogs/',
  '/dsa-explorer/',
];

/* 390 everywhere, because a phone is where the layout viewport quietly widens
   instead of scrolling. 1280 only for the EA pages, whose panel is the one
   that overflowed at desktop width — the rest of the matrix costs more suite
   time than it has ever caught. */
const MATRIX = [
  { width: 390, routes: ALL },
  { width: 1280, routes: ALL.filter((r) => r.startsWith('/ea-explorer/')) },
];

/* The document-level check above would NOT have caught the reported bug. The
   detail panel is `.dr-sheet__body`, which carries `overflow-x: auto`, so an
   unwrappable label scrolls the PANEL and leaves the document the right size.
   The panel has to be measured on its own. */
test('the network detail panel does not scroll sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(
    HOST + '/ea-explorer/network.html#' + encodeURIComponent('institution:inst-066'),
    { waitUntil: 'load' });
  await page.waitForSelector('#panel .rel', { timeout: 30000 });

  const m = await page.evaluate(() => {
    const panel = document.getElementById('panel');
    return {
      scrollWidth: panel.scrollWidth,
      clientWidth: panel.clientWidth,
      rels: panel.querySelectorAll('.rel').length,
      widest: [...panel.querySelectorAll('*')]
        .filter((e) => e.getBoundingClientRect().width > panel.clientWidth + 1)
        .slice(0, 3)
        .map((e) => `${e.tagName.toLowerCase()}.${(e.className || '').toString().trim().split(/\s+/)[0]}` +
                    ` w=${Math.round(e.getBoundingClientRect().width)}`),
    };
  });

  // If this fixture ever loses its long relationship labels the test proves
  // nothing, so assert it still has some.
  expect(m.rels, 'fixture has no relationship rows').toBeGreaterThan(3);
  expect(m.scrollWidth, `panel overflows — ${m.widest.join(', ')}`)
    .toBeLessThanOrEqual(m.clientWidth + 1);
});

for (const { width, routes } of MATRIX) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const route of routes) {
      test(`${route} does not scroll sideways`, async ({ page }) => {
        await page.goto(HOST + route, { waitUntil: 'load' });
        // The canvases lay out asynchronously; the panel fills after that.
        await page.waitForTimeout(3000);

        const m = await page.evaluate(() => {
          const d = document.documentElement;
          const vw = d.clientWidth;
          return {
            scrollWidth: d.scrollWidth,
            clientWidth: vw,
            // Name the culprit rather than just the number.
            culprits: [...document.querySelectorAll('body *')]
              .map((e) => ({ e, r: e.getBoundingClientRect() }))
              .filter(({ r }) => r.height > 0 && r.right > vw + 1)
              .slice(0, 4)
              .map(({ e, r }) =>
                `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}` +
                `.${(e.className || '').toString().trim().split(/\s+/)[0]} right=${Math.round(r.right)}`),
          };
        });

        expect(
          m.scrollWidth,
          `overflows by ${m.scrollWidth - m.clientWidth}px — ${m.culprits.join(', ')}`
        ).toBeLessThanOrEqual(m.clientWidth + 1);
      });
    }
  });
}
