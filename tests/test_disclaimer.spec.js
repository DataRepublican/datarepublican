const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The disclaimer is the one piece of text on this site with legal consequence,
 * and it was the smallest type on the page: 10–11px across three copies,
 * clipped to a few lines on a phone with a click handler bolted onto a <p>.
 *
 * It is one callout now, at 13px, using a native <details>. These specs guard
 * the two properties that matter — it is readable, and the full text is
 * reachable without a pointer. */

const PAGES = [
  { name: 'noblogs', path: '/noblogs/?view=map' },
  { name: 'dsa-explorer', path: '/dsa-explorer/' },
];

for (const { name, path } of PAGES) {
  test.describe(`${name} disclaimer`, () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

    test('is a real details, closed, with a 44px summary', async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      const d = page.locator('details.disclaimer');
      await expect(d).toBeVisible();
      expect(await d.evaluate(e => e.open)).toBe(false);

      const h = await page.locator('details.disclaimer > summary')
        .evaluate(e => Math.round(e.getBoundingClientRect().height));
      expect(h, 'the summary is the tap target').toBeGreaterThanOrEqual(44);
    });

    test('is never the smallest type on the page', async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      await page.locator('details.disclaimer > summary').click();

      const px = await page.locator('details.disclaimer .disclaimer-body')
        .evaluate(e => parseFloat(getComputedStyle(e).fontSize));
      expect(px, 'legal text below 13px').toBeGreaterThanOrEqual(13);
    });

    test('opens from the keyboard and reveals the full text', async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      const d = page.locator('details.disclaimer');
      const body = page.locator('details.disclaimer .disclaimer-body');

      await expect(body).toBeHidden();
      await page.locator('details.disclaimer > summary').focus();
      await page.keyboard.press('Enter');

      await expect(body).toBeVisible();
      expect(await d.evaluate(e => e.open)).toBe(true);
      expect((await body.textContent()).length,
        'the full disclaimer should be present, not a clipped excerpt').toBeGreaterThan(300);
    });
  });
}

test.describe('noblogs header measurement still tracks the disclaimer', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('--nb-header-h follows the details opening', async ({ page }) => {
    // The header is flex-wrap and the map is sized against its measured height,
    // so the <details> has to report a toggle. This replaces the old
    // click-to-expand handler that called setH() directly.
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('details.disclaimer', { timeout: 60000 });

    const read = () => page.evaluate(() => ({
      v: parseInt(getComputedStyle(document.documentElement)
            .getPropertyValue('--nb-header-h'), 10),
      real: Math.round(document.getElementById('nb-header').offsetHeight),
    }));

    const before = await read();
    expect(before.v).toBe(before.real);

    await page.locator('details.disclaimer > summary').click();
    await page.waitForTimeout(250);

    const after = await read();
    expect(after.real, 'opening it should make the header taller').toBeGreaterThan(before.real);
    expect(after.v, '--nb-header-h went stale after the toggle').toBe(after.real);
  });
});
