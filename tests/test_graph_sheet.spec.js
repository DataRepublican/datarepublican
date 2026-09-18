const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The graph's detail panel is the bottom sheet on a phone.
 *
 * It was the only one of the three detail surfaces that never got wired to
 * DRSheet. Tapping a node DID populate it — the failure was that it rendered as
 * a block below a full-viewport canvas, at y≈578 on an 844px screen, so the
 * content was there and off the fold and a tap looked like a no-op.
 *
 * On desktop the wrapper is display:contents, so #gpanel stays a direct grid
 * child of the 1fr/370px grid. These check both widths for that reason.
 */

const tapNode = (page) => page.evaluate(() => { graphApi.cy.nodes().first().emit('tap'); });

const ready = async (page) => {
  await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
    { timeout: 90000 });
  await page.waitForTimeout(700);
};

test.describe('graph detail on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('tapping a node opens the sheet on screen', async ({ page }) => {
    await ready(page);
    await tapNode(page);

    const sheet = page.locator('#graphwrap .dr-sheet');
    await expect(sheet).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(500);

    const box = await page.evaluate(() => {
      const p = document.querySelector('#gpanel');
      const w = p.closest('.dr-sheet');
      const r = (w || p).getBoundingClientRect();
      return { wrapped: !!w, top: Math.round(r.top), vh: window.innerHeight,
               contentLen: p.innerHTML.length };
    });
    expect(box.wrapped, '#gpanel is not wrapped in a sheet').toBe(true);
    expect(box.contentLen, 'the panel rendered nothing').toBeGreaterThan(500);
    // The whole point: it is not parked below the fold.
    expect(box.top).toBeLessThan(box.vh * 0.9);
  });

  test('closing the sheet leaves the graph exactly as it was', async ({ page }) => {
    await ready(page);
    await tapNode(page);
    await expect(page.locator('#graphwrap .dr-sheet')).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(700);

    const before = await page.evaluate(() => ({
      faded: graphApi.cy.elements('.faded').length,
      zoom: Math.round(graphApi.cy.zoom() * 1000),
    }));
    expect(before.faded, 'focus mode should have faded the rest').toBeGreaterThan(0);

    await page.locator('#graphwrap .dr-sheet__close').click();
    await expect(page.locator('#graphwrap .dr-sheet')).not.toHaveClass(/is-open/);
    await page.waitForTimeout(500);

    const after = await page.evaluate(() => ({
      faded: graphApi.cy.elements('.faded').length,
      zoom: Math.round(graphApi.cy.zoom() * 1000),
    }));
    // dsa-explorer cleared cy classes in onClose and dismissing the sheet threw
    // away the walk. The graph must not repeat it.
    expect(after.faded, 'closing the sheet reset the graph').toBe(before.faded);
    expect(after.zoom, 'closing the sheet moved the camera').toBe(before.zoom);
  });
});

test.describe('graph detail on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('the panel is still a docked grid column', async ({ page }) => {
    await ready(page);
    await tapNode(page);
    await page.waitForTimeout(600);

    const g = await page.evaluate(() => {
      const p = document.getElementById('gpanel');
      const r = p.getBoundingClientRect();
      const stage = document.querySelector('#graphwrap #stage').getBoundingClientRect();
      const w = p.closest('.dr-sheet');
      return {
        wrapperDisplay: w ? getComputedStyle(w).display : 'none',
        width: Math.round(r.width),
        toTheRight: r.left >= stage.right - 2,
      };
    });
    // display:contents is what keeps the wrapper out of the grid.
    expect(g.wrapperDisplay).toBe('contents');
    expect(g.width).toBeGreaterThan(300);
    expect(g.toTheRight, 'the panel should still dock beside the canvas').toBe(true);
  });
});

/* The category facets carry the map's colours.
 *
 * With the filter popover open it covers the map legend, so choosing
 * "anarchist" meant picking a category with no way to see which colour it is on
 * the map behind. The swatches are read off the legend markup at boot rather
 * than restated in JS, so the two cannot drift. */
test.describe('category facets show the map colours', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('every category row has a swatch, and it matches the legend', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#facets .fitem[data-f="cat"]', { timeout: 60000 });

    const r = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#facets .fitem[data-f="cat"]')];
      const legend = {};
      document.querySelectorAll('#mapwrap .legend .lgrow').forEach(l => {
        const sw = l.querySelector('span');
        if (sw) legend[l.dataset.cat] = getComputedStyle(sw).backgroundColor;
      });
      const mismatched = rows.filter(row => {
        const sw = row.querySelector('.sw');
        if (!sw) return true;
        const want = legend[row.dataset.v];
        return want ? getComputedStyle(sw).backgroundColor !== want : false;
      }).map(row => row.dataset.v);
      const first = document.querySelector('#facets fieldset.fgroup > legend');
      return { total: rows.length, mismatched,
               firstGroup: first && first.textContent.trim(),
               scopeSwatches: document.querySelectorAll('#facets .fitem[data-f="sc"] .sw').length };
    });

    expect(r.total).toBeGreaterThan(10);
    // Category leads: it is the group tied to the map, and on a phone anything
    // below the first group is behind a scroll.
    expect(r.firstGroup).toBe('Category');
    expect(r.mismatched, `category rows missing or mismatching a swatch: ${r.mismatched}`).toEqual([]);
    // Only the category group is colour-coded; the others would be noise.
    expect(r.scopeSwatches).toBe(0);
  });
});
