const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The map legend is a filter, and it was built out of <div>s.
 *
 * Each category row carried a click handler at about 19px tall — not focusable,
 * no state announced, under half the tap target — and the card's own collapse
 * control was an <h4> with cursor:pointer. On a phone that heading is what hides
 * a panel covering a third of the map, so it was the least reachable control on
 * the most crowded screen.
 *
 * Rows are <button aria-pressed> now and the collapse is a <button
 * aria-expanded>. The `off` class stays as a separate thing: it means "another
 * category is selected and this one is not", which is a dimming, while
 * aria-pressed means "this one is chosen".
 */

test.describe('the map legend filters from a keyboard', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const load = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForSelector('#mapwrap .legend .lgrow', { timeout: 30000 });
  };

  test('every row is a button that reports its own state', async ({ page }) => {
    await load(page);
    const rows = page.locator('#mapwrap .legend .lgrow');
    expect(await rows.count()).toBe(14);

    const tags = await rows.evaluateAll(els => [...new Set(els.map(e => e.tagName))]);
    expect(tags, 'legend rows must be real buttons').toEqual(['BUTTON']);

    // Nothing selected at load: nothing pressed, and nothing dimmed either.
    const pressed = await rows.evaluateAll(els => els.filter(e => e.getAttribute('aria-pressed') === 'true').length);
    const dimmed = await rows.evaluateAll(els => els.filter(e => e.classList.contains('off')).length);
    expect(pressed).toBe(0);
    expect(dimmed).toBe(0);
  });

  test('Space selects a category and filters the map', async ({ page }) => {
    await load(page);
    const first = page.locator('#mapwrap .legend .lgrow').first();
    const cat = await first.getAttribute('data-cat');

    await first.focus();
    await expect(first).toBeFocused();
    await page.keyboard.press('Space');

    await expect(page.locator(`#mapwrap .legend .lgrow[data-cat="${cat}"]`))
      .toHaveAttribute('aria-pressed', 'true');
    // The others dim, which is the "filtered out" state rather than the
    // "chosen" one — the two must not be conflated.
    await expect.poll(() => page.locator('#mapwrap .legend .lgrow.off').count())
      .toBeGreaterThan(0);
    await expect.poll(() => page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, ''))
    )).toBeGreaterThan(0);
  });

  test('a second Space deselects and restores every pin', async ({ page }) => {
    await load(page);
    const before = await page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, '')));

    const first = page.locator('#mapwrap .legend .lgrow').first();
    await first.focus();
    await page.keyboard.press('Space');
    await expect(first).toHaveAttribute('aria-pressed', 'true');

    // Focus must survive, or you cannot toggle two categories in a row.
    await expect(first).toBeFocused();
    await page.keyboard.press('Space');

    await expect(first).toHaveAttribute('aria-pressed', 'false');
    await expect.poll(() => page.locator('#mapwrap .legend .lgrow.off').count()).toBe(0);
    await expect.poll(() => page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, '')))).toBe(before);
  });
});

test.describe('the map info card collapses from a real control', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('the toggle is a button, not the heading', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#mapwrap .info', { timeout: 60000 });

    const btn = page.locator('#mapwrap .info .info-toggle');
    await expect(btn).toBeVisible();
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
    await expect(btn).toHaveAttribute('aria-controls', 'mapinfo-body');
    // It borrows the heading for its name rather than being an empty button.
    await expect(btn).toHaveAttribute('aria-labelledby', 'mapinfo-title');

    const h = await btn.evaluate(e => Math.round(e.getBoundingClientRect().height));
    expect(h, 'the control that hides a third of the map must be tappable').toBeGreaterThanOrEqual(44);

    await expect(page.locator('#mapinfo-body')).toBeHidden();
    await btn.click();
    await expect(btn).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#mapinfo-body')).toBeVisible();
  });

  test('legend rows clear 44px once the card is open', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#mapwrap .info', { timeout: 60000 });
    await page.locator('#mapwrap .info .info-toggle').click();
    await page.waitForTimeout(200);

    const small = await page.locator('#mapwrap .legend .lgrow').evaluateAll(els =>
      els.map(e => ({ c: e.dataset.cat, h: Math.round(e.getBoundingClientRect().height) }))
         .filter(r => r.h < 44));
    expect(small, `legend rows under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });
});
