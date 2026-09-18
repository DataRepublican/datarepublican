const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The dsa-explorer legend, the last of the three.
 *
 * Its own design won the legend comparison — a slim chip bar with a key that
 * expands upward — and then it was the one legend never converted. Rows and
 * chips were <div>/<span> with a delegated click: not focusable, no state
 * announced, and on a phone they sat at ~19px.
 *
 * The filter is single-select-with-clear, not multi-select: one current at a
 * time, and re-clicking the active one clears it. That is aria-pressed on
 * buttons rather than a radiogroup, because a radio cannot be unset and
 * clearing is the common case.
 *
 * Polarity differs from the other two and is right in each: on the map pressed
 * means "chosen", on the graph everything shows at load so pressed means
 * "shown", here pressed means "this is the current being isolated".
 */

const ready = async (page) => {
  await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof cy !== 'undefined' && cy.nodes && cy.nodes().length > 0, { timeout: 90000 });
  // `attached`, not the default `visible`: below 768px the chip row is
  // display:none until the bar is expanded, and hiding the bar is the point.
  await page.waitForSelector('#legend .chip', { state: 'attached', timeout: 30000 });
};

const expand = async (page) => {
  await page.locator('#legend .legtoggle').click();
  await expect(page.locator('#legend .legtoggle')).toHaveAttribute('aria-expanded', 'true');
};

test.describe('the dsa legend filters from a keyboard', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('every interactive row and chip is a real button', async ({ page }) => {
    await ready(page);
    await expand(page);

    const r = await page.evaluate(() => {
      const bad = (sel) => [...document.querySelectorAll(sel)]
        .filter(e => e.tagName !== 'BUTTON')
        .map(e => e.tagName + ':' + (e.dataset.ideo || e.dataset.country || e.id));
      return {
        chips: document.querySelectorAll('#legend .chip').length,
        notButtons: [...bad('#legend [data-ideo]'), ...bad('#legend [data-country]'),
                     ...bad('#legend .allrow')],
        // The shape key is not interactive, so it must NOT have become a button.
        shapeRow: (() => {
          const rows = [...document.querySelectorAll('#legend .legfull .row')];
          const key = rows.find(e => !e.dataset.ideo && !e.dataset.country);
          return key ? key.tagName : 'MISSING';
        })(),
      };
    });

    expect(r.chips).toBeGreaterThan(3);
    expect(r.notButtons, `legend controls still not buttons: ${r.notButtons}`).toEqual([]);
    expect(r.shapeRow, 'the shape key is a legend, not a control').toBe('DIV');
  });

  test('Space isolates a current, and says which', async ({ page }) => {
    await ready(page);

    // Nothing is filtered at load, so "Show all" is the pressed one.
    await expect(page.locator('#legend .chip[aria-pressed="true"]')).toHaveCount(0);

    const chip = page.locator('#legend .chip[data-ideo]').first();
    const key = await chip.getAttribute('data-ideo');
    const before = await page.evaluate(
      () => cy.nodes('[!isTerritory]').filter(n => n.style('display') !== 'none').length);

    await chip.focus();
    await expect(chip).toBeFocused();
    await page.keyboard.press('Space');
    await page.waitForTimeout(400);

    await expect(chip).toHaveAttribute('aria-pressed', 'true');
    const after = await page.evaluate(
      () => cy.nodes('[!isTerritory]').filter(n => n.style('display') !== 'none').length);
    expect(after, 'the chip did not actually filter the graph').toBeLessThan(before);

    // Exactly one current is ever isolated, across BOTH the bar and the key.
    const pressed = await page.locator('#legend [data-ideo][aria-pressed="true"]')
      .evaluateAll(els => els.map(e => e.dataset.ideo));
    expect([...new Set(pressed)]).toEqual([key]);

    // Re-pressing clears, and focus survives so two can be tried in a row.
    await page.keyboard.press('Space');
    await page.waitForTimeout(400);
    await expect(chip).toHaveAttribute('aria-pressed', 'false');
    await expect(chip).toBeFocused();
    expect(await page.evaluate(
      () => cy.nodes('[!isTerritory]').filter(n => n.style('display') !== 'none').length)).toBe(before);
  });

  test('Show all is pressed exactly when nothing is isolated', async ({ page }) => {
    await ready(page);
    await expand(page);

    const all = page.locator('#legend .allrow');
    await expect(all).toHaveAttribute('aria-pressed', 'true');

    await page.locator('#legend .legfull .row[data-ideo]').first().click();
    await page.waitForTimeout(300);
    await expect(all).toHaveAttribute('aria-pressed', 'false');

    await all.click();
    await page.waitForTimeout(300);
    await expect(all).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#legend [data-ideo][aria-pressed="true"]')).toHaveCount(0);
  });

  test('a country row navigates and is not a toggle', async ({ page }) => {
    await ready(page);
    await expand(page);

    const rows = page.locator('#legend .row[data-country]');
    if (await rows.count() === 0) test.skip(true, 'this slice has no country boxes');

    // A button that does something is not a button that is in a state.
    const withState = await rows.evaluateAll(
      els => els.filter(e => e.hasAttribute('aria-pressed')).map(e => e.dataset.country));
    expect(withState, `country rows must not carry aria-pressed: ${withState}`).toEqual([]);
  });
});

test.describe('the dsa legend on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('the toggle reports its state and the key opens from the keyboard', async ({ page }) => {
    await ready(page);
    const toggle = page.locator('#legend .legtoggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await toggle.focus();
    await page.keyboard.press('Enter');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#legend .legfull')).toBeVisible();
  });

  test('every control clears 44px once open', async ({ page }) => {
    await ready(page);
    await page.locator('#legend .legtoggle').click();
    await page.waitForTimeout(300);

    const small = await page.locator('#legend .row, #legend .chip, #legend .allrow')
      .evaluateAll(els => els
        .filter(e => e.getBoundingClientRect().height > 0)
        .map(e => ({ k: e.dataset.ideo || e.dataset.country || e.className,
                     h: Math.round(e.getBoundingClientRect().height) }))
        .filter(r => r.h < 44));
    expect(small, `legend controls under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });
});
