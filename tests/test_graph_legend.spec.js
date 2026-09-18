const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The graph legend, the last of the three.
 *
 * Its rows show and hide a node class or an edge type, so they are filters —
 * and they were <div>s with a delegated click: not focusable, no state
 * announced. It also had no collapse control at all, so on a phone the key ran
 * down the screen over the graph it was describing, bounded only by a
 * calc(100vh - 150px) guess at the chrome above it.
 *
 * Polarity is inverted from the map's legend, deliberately: there, pressed
 * means "this category is chosen". Here everything is shown at load and
 * pressing hides, so pressed means SHOWN.
 */

const ready = async (page) => {
  await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
    { timeout: 90000 });
  await page.waitForTimeout(700);
};

test.describe('the graph legend filters from a keyboard', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('every row is a button, and all start shown', async ({ page }) => {
    await ready(page);
    const rows = page.locator('#graphwrap #legend .row');
    expect(await rows.count()).toBeGreaterThan(8);

    const tags = await rows.evaluateAll(els => [...new Set(els.map(e => e.tagName))]);
    expect(tags, 'legend rows must be real buttons').toEqual(['BUTTON']);

    const unpressed = await rows.evaluateAll(
      els => els.filter(e => e.getAttribute('aria-pressed') !== 'true').map(e => e.dataset.nkey || e.dataset.ekey));
    expect(unpressed, 'everything is visible at load, so everything is pressed').toEqual([]);
  });

  test('Space hides a class and says so', async ({ page }) => {
    await ready(page);
    const row = page.locator('#graphwrap #legend .row[data-nkey]').first();
    const key = await row.getAttribute('data-nkey');

    await row.focus();
    await expect(row).toBeFocused();
    await page.keyboard.press('Space');

    const after = page.locator(`#graphwrap #legend .row[data-nkey="${key}"]`);
    await expect(after).toHaveAttribute('aria-pressed', 'false');
    await expect(after).toHaveClass(/off/);

    // Focus survives, so two can be toggled in a row.
    await expect(after).toBeFocused();
    await page.keyboard.press('Space');
    await expect(after).toHaveAttribute('aria-pressed', 'true');
    await expect(after).not.toHaveClass(/off/);
  });

  test('hiding an edge type actually hides edges', async ({ page }) => {
    await ready(page);
    const before = await page.evaluate(
      () => graphApi.cy.edges().filter(e => e.style('display') !== 'none').length);

    await page.locator('#graphwrap #legend .row[data-ekey]').first().click();
    await page.waitForTimeout(400);

    const after = await page.evaluate(
      () => graphApi.cy.edges().filter(e => e.style('display') !== 'none').length);
    expect(after, 'the legend row did not filter the graph').toBeLessThan(before);
  });

  test('the key is shown unconditionally, so the toggle is hidden', async ({ page }) => {
    await ready(page);
    await expect(page.locator('#graphwrap #legend .legtoggle')).toBeHidden();
    await expect(page.locator('#graphwrap #legend .legbody')).toBeVisible();
    // Bounded by its own container rather than a guess at the page chrome.
    const mh = await page.locator('#graphwrap #legend').evaluate(e => getComputedStyle(e).maxHeight);
    expect(mh).not.toContain('100vh');
  });
});

test.describe('the graph legend collapses on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('it starts as one 44px row and opens from the keyboard', async ({ page }) => {
    await ready(page);
    const toggle = page.locator('#graphwrap #legend .legtoggle');
    const body = page.locator('#graphwrap #legend .legbody');

    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(body).toBeHidden();

    const h = await toggle.evaluate(e => Math.round(e.getBoundingClientRect().height));
    expect(h).toBeGreaterThanOrEqual(44);

    await toggle.focus();
    await page.keyboard.press('Enter');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(body).toBeVisible();
  });

  test('rows clear 44px once open', async ({ page }) => {
    await ready(page);
    await page.locator('#graphwrap #legend .legtoggle').click();
    await page.waitForTimeout(250);

    const small = await page.locator('#graphwrap #legend .row').evaluateAll(els =>
      els.map(e => ({ k: e.dataset.nkey || e.dataset.ekey, h: Math.round(e.getBoundingClientRect().height) }))
         .filter(r => r.h < 44));
    expect(small, `legend rows under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });
});
