const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* What the facet rail could and could not do before this, measured against the
 * old implementation rather than assumed — two of the specs below passed
 * against it, which is the useful part.
 *
 * Each row was a <div> carrying the click handler, with `pointer-events: none`
 * on the real checkbox inside it.
 *
 *   WORKED:  Tab reached a facet and Space toggled it. `pointer-events: none`
 *            does not remove an input from the tab order, and Space fires a
 *            click that bubbled to the row handler.
 *   BROKEN:  focus did not survive the toggle. buildFacets() rewrites the whole
 *            subtree, so the second keystroke went to <body>. Keyboard support
 *            that ends after one keypress is not support.
 *   BROKEN:  the checkbox itself was unclickable — pointer-events killed it, so
 *            only the row around it responded to a pointer.
 *   BROKEN:  no fieldset/legend grouping, the clear control was a <span>, and
 *            rows were ~24px against a 44px target.
 *
 * Rows are now <label> wrapping <input type="checkbox"> inside a <fieldset>,
 * and the handler listens to the input's `change`.
 */

test.describe('the facet rail works from a keyboard', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const open = async (page) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#facets .fitem input', { timeout: 60000 });
  };

  test('Space on a focused facet filters the grid', async ({ page }) => {
    await open(page);

    const box = page.locator('#facets .fitem[data-f="sc"] input').first();
    await box.focus();
    await expect(box).toBeFocused();          // it is reachable at all
    await expect(box).not.toBeChecked();

    const before = await page.locator('#subcount').textContent();
    await page.keyboard.press('Space');

    await expect(page.locator('#facets .fitem[data-f="sc"] input').first()).toBeChecked();
    await expect.poll(() => page.evaluate(() => F.sc.size)).toBe(1);
    await expect.poll(() => page.evaluate(() => new URL(location.href).searchParams.get('sc')))
      .not.toBeNull();
    expect(before).not.toBeNull();
  });

  test('Space toggles exactly once — the old row handler double-fired', async ({ page }) => {
    await open(page);
    const sel = '#facets .fitem[data-f="sc"] input';

    await page.locator(sel).first().focus();
    await page.keyboard.press('Space');
    await expect.poll(() => page.evaluate(() => F.sc.size)).toBe(1);

    await page.locator(sel).first().focus();
    await page.keyboard.press('Space');
    await expect.poll(() => page.evaluate(() => F.sc.size)).toBe(0);
  });

  test('focus survives the rebuild, so you can toggle two in a row', async ({ page }) => {
    await open(page);

    // buildFacets() replaces this whole subtree on every change. Without the
    // focus restore, one Space drops focus to <body> and the next keystroke
    // goes nowhere — keyboard support that is nominal rather than usable.
    const first = page.locator('#facets .fitem[data-f="sc"]').first();
    const value = await first.getAttribute('data-v');
    await first.locator('input').focus();
    await page.keyboard.press('Space');

    await expect(page.locator(`#facets .fitem[data-v="${value}"] input`)).toBeFocused();
    await page.keyboard.press('Space');
    await expect.poll(() => page.evaluate(() => F.sc.size)).toBe(0);
  });

  test('a clicked facet still cross-filters the map', async ({ page }) => {
    // The facets drive the grid, the map's setHosts and the graph's host set
    // from one filtered() call. Semantics changed; that must not have.
    await open(page);
    await page.locator('#facets .fitem[data-flag="geo"] input').check();
    await expect.poll(() => page.evaluate(() => F.flags.has('geo'))).toBe(true);

    await page.click('.tab[data-v="map"]');
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    const shown = await page.evaluate(() => filtered().length);
    const total = await page.evaluate(() => DATA.length);
    expect(shown).toBeGreaterThan(0);
    expect(shown).toBeLessThan(total);
  });

  test('groups are fieldsets and the clear control is a button', async ({ page }) => {
    await open(page);
    expect(await page.locator('#facets fieldset.fgroup').count()).toBeGreaterThan(3);
    expect(await page.locator('#facets fieldset.fgroup > legend').count()).toBeGreaterThan(3);
    await expect(page.locator('#facets button.clearf')).toBeVisible();
    // No live checkbox may be unreachable.
    expect(await page.locator('#facets .fitem input').evaluateAll(
      els => els.filter(e => getComputedStyle(e).pointerEvents === 'none').length
    )).toBe(0);
  });
});

test.describe('facet rows are tappable on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('every row clears 44px', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    await page.click('#nb-filters');
    await expect(page.locator('#facets')).toBeVisible();

    const small = await page.locator('#facets .fitem').evaluateAll(els =>
      els.map(e => ({ v: e.dataset.v || e.dataset.flag, h: Math.round(e.getBoundingClientRect().height) }))
         .filter(r => r.h < 44)
    );
    expect(small, `rows under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });
});
