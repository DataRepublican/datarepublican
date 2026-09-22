const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Category filtering on the map, which now lives in two different places.
 *
 * THE STANDALONE PAGE (/noblogs/world_hyperlocal_map.html) still has the
 * clickable legend card. Rows were <div>s with click handlers at about 19px
 * tall — not focusable, no state announced, under half the tap target — and
 * they are <button aria-pressed> now. That markup and the map.js code path
 * behind it (paintLegend, legendCats, #shownCount) are unchanged, so the
 * keyboard specs below simply moved to the page that still has them.
 *
 * THE EXPLORER (/noblogs/?view=map) deleted its copy. The card was pinned to
 * the map's top-left corner, which is where Leaflet puts its zoom control, and
 * its legend was a SECOND category filter ANDed with the facet one — two
 * controls for one question, where the facet version already had counts. The
 * explorer's category filtering is the facet group now, and the second describe
 * is the same property tested through that door.
 *
 * The `off` class stays as a separate thing on the legend: it means "another
 * category is selected and this one is not", which is a dimming, while
 * aria-pressed means "this one is chosen".
 */

test.describe('the standalone map legend filters from a keyboard', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const load = async (page) => {
    await page.goto(HOST + '/noblogs/world_hyperlocal_map.html', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForSelector('.legend .lgrow', { timeout: 30000 });
  };

  test('every row is a button that reports its own state', async ({ page }) => {
    await load(page);
    const rows = page.locator('.legend .lgrow');
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
    const first = page.locator('.legend .lgrow').first();
    const cat = await first.getAttribute('data-cat');

    await first.focus();
    await expect(first).toBeFocused();
    await page.keyboard.press('Space');

    await expect(page.locator(`.legend .lgrow[data-cat="${cat}"]`))
      .toHaveAttribute('aria-pressed', 'true');
    // The others dim, which is the "filtered out" state rather than the
    // "chosen" one — the two must not be conflated.
    await expect.poll(() => page.locator('.legend .lgrow.off').count())
      .toBeGreaterThan(0);
    await expect.poll(() => page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, ''))
    )).toBeGreaterThan(0);
  });

  test('a second Space deselects and restores every pin', async ({ page }) => {
    await load(page);
    const before = await page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, '')));

    const first = page.locator('.legend .lgrow').first();
    await first.focus();
    await page.keyboard.press('Space');
    await expect(first).toHaveAttribute('aria-pressed', 'true');

    // Focus must survive, or you cannot toggle two categories in a row.
    await expect(first).toBeFocused();
    await page.keyboard.press('Space');

    await expect(first).toHaveAttribute('aria-pressed', 'false');
    await expect.poll(() => page.locator('.legend .lgrow.off').count()).toBe(0);
    await expect.poll(() => page.evaluate(
      () => Number(document.getElementById('shownCount').textContent.replace(/\D/g, '')))).toBe(before);
  });
});

/* Category is the map's color key, so on a canvas view at md it lives in the
 * sidebar beside the canvas and NOT in the filter popover — one group rendered
 * in two places at once is the duplication the sidebar removed. Below md, and
 * on the List view, the popover is still where it is, because neither has a
 * sidebar. The rows are the same markup either way: `bindFacets()` binds both
 * copies, so anything asserted about one holds for the other. */
test.describe('the explorer filters categories from the facet panel', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  // Canvas view: no click needed, the sidebar is always open.
  const openCats = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForSelector('#nb-side-cats .fitem[data-f="cat"]', { timeout: 30000 });
  };

  const openFilters = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.click('#nb-filters');
    await page.waitForSelector('#facets .fgroup', { timeout: 30000 });
  };

  test('the map carries no permanent overlay, so the zoom control is clear', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-control-zoom', { timeout: 90000 });

    // The deleted card sat exactly here. Whatever is on top of the zoom
    // control's center must be the zoom control.
    const owns = await page.evaluate(() => {
      const z = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
      const hit = document.elementFromPoint(z.left + z.width / 2, z.top + z.height / 2);
      return !!(hit && hit.closest('.leaflet-control-zoom'));
    });
    expect(owns, 'something is covering the map zoom control again').toBe(true);
  });

  test('the Category group carries the swatches the legend used to', async ({ page }) => {
    await openCats(page);
    const rows = page.locator('#nb-side-cats .fitem[data-f="cat"]');
    expect(await rows.count()).toBeGreaterThan(10);

    // The color encoding has to survive the legend's deletion: CATCOLOR used
    // to be scraped out of that markup at load time.
    const swatches = await rows.evaluateAll(els => els.map(e => {
      const sw = e.querySelector('.sw');
      return sw ? getComputedStyle(sw).backgroundColor : null;
    }));
    expect(swatches.filter(Boolean).length,
      'category rows lost their color swatches').toBe(swatches.length);
    expect(new Set(swatches).size,
      'every category is painted the same color — CATCOLOR is not resolving')
      .toBeGreaterThan(5);

    // And counts, which the legend never had.
    const counts = await rows.evaluateAll(els =>
      els.map(e => (e.querySelector('.c') || {}).textContent || '').filter(t => /\d/.test(t)));
    expect(counts.length).toBe(await rows.count());
  });

  test('toggling a category filters the map and the status line', async ({ page }) => {
    await openCats(page);
    // The first number in the line, commas stripped. Not `replace(/[^\d].*/)`
    // — that stops at the thousands separator and reads "4,620" as 4.
    const readCount = () => page.evaluate(() => {
      const m = document.getElementById('subcount').textContent.replace(/,/g, '').match(/\d+/);
      return m ? Number(m[0]) : NaN;
    });

    const before = await readCount();
    expect(before).toBeGreaterThan(0);

    const first = page.locator('#nb-side-cats .fitem[data-f="cat"] input').first();
    await first.check();
    await expect.poll(readCount).toBeLessThan(before);

    // Focus survives the rebuild, or you cannot toggle two in a row —
    // buildFacets() rewrites this whole subtree on every change.
    await expect(first).toBeFocused();

    await first.uncheck();
    await expect.poll(readCount).toBe(before);
  });

  test('the Map group holds the co-citation edge toggle', async ({ page }) => {
    await openFilters(page);
    const edges = page.locator('#facets .fitem[data-map="edges"] input');
    await expect(edges).toBeChecked();

    // It is a display option, not a filter: it must not count toward the badge.
    await edges.uncheck();
    await page.waitForTimeout(200);
    await expect(page.locator('#nb-filtercount')).toBeHidden();

    // And it must actually reach the map, through NBMap.setEdges rather than
    // through a checkbox map.js reads out of the DOM.
    const edgeCount = await page.locator('.coedge').count();
    expect(edgeCount, 'unchecking the toggle left the edges on the map').toBe(0);
  });

  /* Category is drawn twice on a canvas view and the two cannot be allowed to
     drift. Neither copy holds state — buildFacets() renders both out of F on
     every change — but that is exactly the kind of invariant that survives
     until someone optimizes one of the two rebuilds away. */
  test('both copies of Category track the same state', async ({ page }) => {
    const read = () => page.evaluate(() => {
      const of = root => [...document.querySelectorAll(
        `${root} .fitem[data-f="cat"]`)].map(e => [e.dataset.v, e.querySelector('input').checked]);
      return { side: of('#nb-side-cats'), pop: of('#facets') };
    });

    // Set it in the sidebar, with the popover closed.
    await openCats(page);
    const before = await read();
    expect(before.side.length).toBeGreaterThan(10);
    expect(before.pop, 'the popover dropped Category').toEqual(before.side);
    await page.locator('#nb-side-cats .fitem[data-f="cat"] input').first().check();

    // The popover opens already agreeing with it.
    await page.click('#nb-filters');
    await page.waitForSelector('#facets .fitem[data-f="cat"]', { timeout: 30000 });
    const open = await read();
    expect(open.pop[0][1], 'the popover opened out of date').toBe(true);
    expect(open.pop).toEqual(open.side);

    // And clearing it there reaches the sidebar underneath.
    await page.locator('#facets .fitem[data-f="cat"] input').first().uncheck();
    await expect.poll(async () => (await read()).side[0][1]).toBe(false);
    const after = await read();
    expect(after.pop).toEqual(after.side);
  });

  test('the List view has no sidebar, so the rail carries Category alone', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#dashview .card', { timeout: 60000 });
    const onList = await page.evaluate(() => ({
      side: !!document.querySelector('#nb-side-cats .fitem[data-f="cat"]')?.offsetParent,
      rail: !!document.querySelector('#facets .fitem[data-f="cat"]')?.offsetParent,
    }));
    expect(onList).toEqual({ side: false, rail: true });
  });
});
