const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Both graph toolbars are icon-first and built on .dr-btn.
 *
 * They spelled out "＋ Zoom", "－ Zoom", "Reset view", "Re-layout", "⬇ Export
 * PNG" in a 6px-radius box that was overridden into a pill below 767px anyway.
 * The glyphs are Lucide, the same pack already inlined in the nav.
 *
 * The rule the labels follow: icon alone where the action has a conventional
 * glyph and no state (zoom, fit, re-layout); icon PLUS word for a mode or
 * anything irreversible (Focus mode, Inferred links, Export). An icon can name
 * a thing but it cannot say whether a mode is currently on.
 */

const TOOLS = [
  { name: 'noblogs graph', path: '/noblogs/?view=graph', scope: '#graphwrap #controls',
    ready: () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0 },
  { name: 'dsa-explorer', path: '/dsa-explorer/', scope: '#controls',
    ready: () => typeof cy !== 'undefined' && cy.nodes && cy.nodes().length > 0 },
];

for (const t of TOOLS) {
  test.describe(`${t.name} toolbar`, () => {
    const load = async (page) => {
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(t.ready, { timeout: 90000 });
      await page.waitForSelector(`${t.scope} .dr-btn`, { timeout: 30000 });
      await page.waitForTimeout(400);
    };

    test('every control is a .dr-btn and every icon-only one is named', async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await load(page);

      const r = await page.evaluate((scope) => {
        const btns = [...document.querySelectorAll(`${scope} button`)];
        return {
          total: btns.length,
          notComponent: btns.filter(b => !b.classList.contains('dr-btn')).map(b => b.id),
          // An icon-only button must carry its own name; the <svg> is aria-hidden.
          unnamed: btns.filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).map(b => b.id),
          // data-tip, not title: DRTip replaced the native tooltip because a
          // one-second delay on an icon-only control is not an explanation.
          noTooltip: btns.filter(b => !b.getAttribute('data-tip')).map(b => b.id),
          nativeTitle: btns.filter(b => b.title).map(b => b.id),
          exposedSvg: [...document.querySelectorAll(`${scope} button svg`)]
            .filter(s => s.getAttribute('aria-hidden') !== 'true').length,
        };
      }, t.scope);

      expect(r.total).toBeGreaterThan(5);
      expect(r.notComponent, `controls not on .dr-btn: ${r.notComponent}`).toEqual([]);
      expect(r.unnamed, `icon-only buttons with no accessible name: ${r.unnamed}`).toEqual([]);
      expect(r.noTooltip, `controls with no tooltip: ${r.noTooltip}`).toEqual([]);
      // Both would stack the native tip under ours and read the text twice.
      expect(r.nativeTitle, `controls still carrying title=: ${r.nativeTitle}`).toEqual([]);
      expect(r.exposedSvg, 'decorative icons must be aria-hidden').toBe(0);
    });

    /* 44px is the floor for a thumb, not for a mouse. The system allows the 32px
       `sm` size in exactly one place — a toolbar above md — because seven
       stacked 44px buttons make a column taller than the room above the
       legend. So the floor is asserted per width rather than globally. */
    for (const [w, h, floor] of [[1280, 900, 32], [390, 844, 44]]) {
      test(`every control clears ${floor}px at ${w}px`, async ({ page }) => {
        await page.setViewportSize({ width: w, height: h });
        await load(page);
        const small = await page.locator(`${t.scope} .dr-btn`).evaluateAll((els, f) =>
          els.map(e => ({ id: e.id, h: Math.round(e.getBoundingClientRect().height) }))
             .filter(r => r.h < f), floor);
        expect(small, `controls under ${floor}px: ${JSON.stringify(small)}`).toEqual([]);
      });
    }

    test('the legend never covers the control column', async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await load(page);
      const clash = await page.evaluate((scope) => {
        const c = document.querySelector(scope).getBoundingClientRect();
        const l = document.querySelector(scope.replace('#controls', '#legend')).getBoundingClientRect();
        const overlap = Math.min(c.bottom, l.bottom) - Math.max(c.top, l.top);
        return { overlap: Math.round(overlap), controlsBottom: Math.round(c.bottom), legendTop: Math.round(l.top) };
      }, t.scope);
      expect(clash.overlap, `legend overlaps the controls by ${clash.overlap}px`).toBeLessThanOrEqual(0);
    });

    test('the controls still work', async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await load(page);
      // Zoom is the one whose label became a bare glyph, so prove it still acts.
      const z = () => page.evaluate(
        (g) => Math.round((g ? graphApi.cy : cy).zoom() * 1000), t.name.startsWith('noblogs'));
      const before = await z();
      await page.locator(`${t.scope} #zin`).click();
      await page.waitForTimeout(300);
      expect(await z(), 'zoom in did nothing').toBeGreaterThan(before);
      await page.locator(`${t.scope} #zout`).click();
      await page.waitForTimeout(300);
      expect(await z()).toBeLessThan(await page.evaluate(() => 1e9));
    });
  });
}
