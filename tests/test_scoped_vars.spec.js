const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Prohibition 3: a tool's variables belong to the tool, not to the document
 * element. An unlayered `:root` in a tool's inline <style> puts them on <html>,
 * where they outlive the tool's own box and sit alongside the site's real
 * tokens with no way to tell them apart.
 *
 * Asserted as an ABSENCE on :root rather than a presence somewhere, because the
 * failure is the leak itself — it does not matter which element a tool picks
 * instead, only that it is not <html>.
 */

const TOOLS = [
  { name: 'noblogs', path: '/noblogs/?view=map', scope: 'body',
    vars: ['--bg', '--panel', '--ink', '--dim', '--line', '--accent', '--tile'] },
  { name: 'dsa-explorer', path: '/dsa-explorer/', scope: '#app',
    vars: ['--bg', '--panel', '--ink'] },
];

for (const t of TOOLS) {
  test.describe(`${t.name} keeps its variables off :root`, () => {
    test.use({ viewport: { width: 1280, height: 900 } });

    test('declares them on its own scope, not the document element', async ({ page }) => {
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(t.scope, { timeout: 60000 });

      const r = await page.evaluate(({ scope, vars }) => {
        const root = getComputedStyle(document.documentElement);
        const own = getComputedStyle(document.querySelector(scope));
        const read = (cs, n) => cs.getPropertyValue(n).trim();
        return {
          onRoot: vars.filter(v => read(root, v) !== ''),
          missing: vars.filter(v => read(own, v) === ''),
        };
      }, t);

      expect(r.onRoot, `leaked to :root: ${r.onRoot.join(', ')}`).toEqual([]);
      expect(r.missing, `not declared on ${t.scope}: ${r.missing.join(', ')}`).toEqual([]);
    });

    test('and the tool still paints', async ({ page }) => {
      // The scoping is only correct if everything downstream still resolves.
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(t.scope, { timeout: 60000 });
      const painted = await page.evaluate((scope) => {
        const cs = getComputedStyle(document.querySelector(scope));
        return { bg: cs.backgroundColor, color: cs.color };
      }, t.scope);
      // Not transparent, not the initial black-on-nothing of an unresolved var.
      expect(painted.bg).not.toBe('rgba(0, 0, 0, 0)');
      expect(painted.color).not.toBe('');
    });
  });
}
