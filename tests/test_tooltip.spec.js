const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* DRTip replaced `title` on every toolbar control.
 *
 * The native tooltip waits about a second, which on an icon-only control is the
 * whole interaction: you hover a glyph you do not recognise, get nothing, and
 * move on. These specs hold the three properties that made it worth replacing —
 * it is instant, it is the ONLY tooltip (both would stack and read twice), and
 * it survives the isolated canvases the tools use to contain Leaflet and
 * Cytoscape.
 */

const TOOLS = [
  { name: 'noblogs graph', path: '/noblogs/?view=graph', ready: '#graphwrap #cy canvas',
    scope: '#graphwrap #controls', ambiguous: '#relayout' },
  { name: 'dsa-explorer', path: '/dsa-explorer/', ready: '#cy canvas',
    scope: '#controls', ambiguous: '#relayout' },
];

for (const t of TOOLS) {
  test.describe(`${t.name} tooltips`, () => {
    test.use({ viewport: { width: 1280, height: 900 } });

    const load = async (page) => {
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(t.ready, { timeout: 90000 });
      await page.waitForSelector(`${t.scope} .dr-btn`, { timeout: 30000 });
    };

    test('every control has one, and none keeps a native title', async ({ page }) => {
      await load(page);
      const r = await page.evaluate((scope) => {
        const btns = [...document.querySelectorAll(`${scope} button`)];
        return {
          total: btns.length,
          untipped: btns.filter(b => !b.getAttribute('data-tip')).map(b => b.id),
          titled: btns.filter(b => b.title).map(b => b.id),
          unnamed: btns.filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).map(b => b.id),
        };
      }, t.scope);

      expect(r.total).toBeGreaterThan(4);
      expect(r.untipped, `no tooltip: ${r.untipped}`).toEqual([]);
      // Both would stack the native tip under ours and read the text twice.
      expect(r.titled, `still carrying title=: ${r.titled}`).toEqual([]);
      expect(r.unnamed, `icon-only with no accessible name: ${r.unnamed}`).toEqual([]);
    });

    test('appears instantly on hover and describes the control', async ({ page }) => {
      await load(page);
      await page.locator(`${t.scope} ${t.ambiguous}`).hover();

      // No timeout: instant is the entire reason this exists. Polling here
      // would pass with a one-second delay reinstated.
      const tip = await page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        return el && !el.hidden ? { text: el.textContent, on: el.classList.contains('is-on') } : null;
      });
      expect(tip, 'the tooltip did not appear on hover').not.toBeNull();
      expect(tip.on).toBe(true);
      expect(tip.text.length, 'an ambiguous control needs a sentence').toBeGreaterThan(30);

      // Described, not named: the control keeps its own accessible name.
      await expect(page.locator(`${t.scope} ${t.ambiguous}`))
        .toHaveAttribute('aria-describedby', 'dr-tip');
    });

    test('renders above the isolated canvas, not trapped inside it', async ({ page }) => {
      await load(page);
      await page.locator(`${t.scope} ${t.ambiguous}`).hover();

      const r = await page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        const box = el.getBoundingClientRect();
        return {
          parentIsBody: el.parentElement === document.body,
          z: Number(getComputedStyle(el).zIndex),
          w: Math.round(box.width), h: Math.round(box.height),
          left: Math.round(box.left), right: Math.round(box.right),
        };
      });

      /* Appended to <body>, because #stage sets `isolation: isolate` to contain
         the vendor's z-indexes — a tip rendered inside is trapped in that
         stacking context and clipped by the stage's overflow. */
      expect(r.parentIsBody, 'a tip inside the canvas is clipped by it').toBe(true);
      expect(r.z, 'nothing this repo authors goes above 100').toBeLessThanOrEqual(100);
      expect(r.w).toBeGreaterThan(0);
      expect(r.h).toBeGreaterThan(0);
      // Clamped into the viewport rather than hanging off the edge.
      expect(r.left).toBeGreaterThanOrEqual(0);
      expect(r.right).toBeLessThanOrEqual(1280);
    });

    test('goes away on leave, and on Escape', async ({ page }) => {
      await load(page);
      const up = () => page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        return !!(el && !el.hidden);
      });

      await page.locator(`${t.scope} ${t.ambiguous}`).hover();
      expect(await up()).toBe(true);
      await page.mouse.move(5, 5);
      expect(await up(), 'the tip outlived the pointer').toBe(false);

      // Keyboard users get it on focus, and Escape dismisses it.
      await page.locator(`${t.scope} ${t.ambiguous}`).focus();
      expect(await up(), 'no tooltip on keyboard focus').toBe(true);
      await page.keyboard.press('Escape');
      expect(await up()).toBe(false);
    });
  });
}
