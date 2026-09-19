const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Interface labels stopped shouting, and the result count started speaking.
 *
 * There were THIRTEEN rules doing one job across three files — 10px, 10.5px and
 * 11px, four different letter-spacings, three different greys, every one of them
 * uppercase. They are now one recipe per file, all reading the same tokens.
 *
 * Asserting `textTransform: none` is the point rather than a nicety: it is the
 * only way to catch the recipe losing on source order. Each grouped rule sits
 * BELOW the rules it overrides and carries no extra specificity, so moving it up
 * a few lines silently restores the uppercase. Computed style catches that; a
 * grep of the source does not.
 */

const LABELS = [
  { name: 'noblogs library',
    open: async (page) => {
      await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.card', { timeout: 90000 });
      await page.locator('.card').first().click();
      await page.waitForSelector('#pinner .sec h4', { timeout: 30000 });
    },
    sel: ['.kpi .k', '#pinner .sec h4', '#pinner .q .qhd', '#pinner .ctlab',
          '#pinner details.news>summary'] },

  { name: 'noblogs graph',
    open: async (page) => {
      await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(
        () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
        { timeout: 90000 });
      await page.evaluate(() => { graphApi.cy.nodes().first().emit('tap'); });
      await page.waitForSelector('#gpanel .kv b', { timeout: 30000 });
    },
    sel: ['#gpanel .kv b', '#gpanel .tag'] },

  { name: 'dsa-explorer',
    open: async (page) => {
      await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(
        () => typeof cy !== 'undefined' && cy.nodes && cy.nodes().length > 0, { timeout: 90000 });
      await page.evaluate(() => { cy.nodes().first().emit('tap'); });
      await page.waitForSelector('#panel .tag', { timeout: 30000 });
      // The full key lives inside .legfull, which is display:none until the bar
      // is expanded — so `attached`, not the default `visible`. Nothing asserted
      // here needs layout: text-transform, font-size and letter-spacing all
      // compute inside a display:none subtree.
      await page.waitForSelector('#legend h4', { state: 'attached', timeout: 30000 });
    },
    // #legend h4 and #panel .conns h3 share one grouped rule, so the one that is
    // always present stands for both. .tag is its own rule — it keeps white ink,
    // because its background is set inline from the data.
    sel: ['#legend h4', '#panel .tag'] },
];

for (const t of LABELS) {
  test(`${t.name} labels are 12px sentence case`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await t.open(page);

    const bad = await page.evaluate((sels) => {
      const out = [];
      for (const s of sels) {
        const el = document.querySelector(s);
        if (!el) { out.push({ s, why: 'absent' }); continue; }
        const c = getComputedStyle(el);
        if (c.textTransform !== 'none') out.push({ s, why: `text-transform: ${c.textTransform}` });
        // 12px is the floor. A label may be larger; it may never be smaller.
        if (parseFloat(c.fontSize) < 12) out.push({ s, why: `font-size: ${c.fontSize}` });
        if (c.letterSpacing !== 'normal') out.push({ s, why: `letter-spacing: ${c.letterSpacing}` });
      }
      return out;
    }, t.sel);

    expect(bad, `labels off the recipe: ${JSON.stringify(bad)}`).toEqual([]);
  });
}

/* The library card.
 *
 * Every line of it was under 12px — 10, 10.5 and 11.5 — which made the main
 * content of the library view the smallest type in the tool, on a grey ground.
 * The detail panel got fixed first; the cards that lead to it did not.
 *
 * The floors are the scale's: 12px for a label, 13px for anything read as a
 * sentence. Asserted per element rather than as one number, because .csum is
 * prose and .chost is not, and they are allowed to differ.
 */
test('the library card clears the type floors', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.card', { timeout: 90000 });

  const bad = await page.evaluate(() => {
    const floors = {
      '.cname': 14, '.chost': 12, '.badge': 12, '.cmeta .tag': 12,
      '.cloc': 13, '.csum': 13, '.cfoot': 12,
    };
    const out = [];
    for (const [sel, floor] of Object.entries(floors)) {
      const el = document.querySelector('.card ' + sel);
      if (!el) { out.push({ sel, why: 'absent' }); continue; }
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < floor) out.push({ sel, why: `${fs}px, floor ${floor}px` });
    }
    return out;
  });
  expect(bad, `card text under its floor: ${JSON.stringify(bad)}`).toEqual([]);
});

/* Clear-all was a 20px target at 11px — the smallest hit area in the tool, and
   a real control, not a caption. 32px with a mouse, 44px on a phone. */
for (const [w, h, floor] of [[1280, 900, 32], [390, 844, 44]]) {
  test(`clear-all clears ${floor}px at ${w}px`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.clearf', { state: 'attached', timeout: 90000 });
    // On a phone the facet list lives in the filter popover, so clear-all has no
    // box until it is open. Measuring it closed reports 0 and passes nothing.
    if (w < 768) {
      await page.locator('#nb-filters').click();
      await expect(page.locator('.clearf').first()).toBeVisible();
    }
    const box = await page.locator('.clearf').first().evaluate(e => ({
      h: Math.round(e.getBoundingClientRect().height),
      fs: parseFloat(getComputedStyle(e).fontSize),
    }));
    expect(box.h, `clear-all is ${box.h}px tall`).toBeGreaterThanOrEqual(floor);
    expect(box.fs).toBeGreaterThanOrEqual(12);
  });
}

/* Empty and loading states read at body size.
 *
 * They are the only thing on screen when they show, and they were the smallest
 * copy in the tool — 13px grey on a grey ground. */
test('the map loading veil reads at body size and announces itself', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });

  const veil = await page.locator('#maploading').evaluate(e => ({
    role: e.getAttribute('role'),
    size: parseFloat(getComputedStyle(e).fontSize),
  }));
  expect(veil.role).toBe('status');
  expect(veil.size).toBeGreaterThanOrEqual(16);
});

/* The result count is the tool's only running commentary.
 *
 * render() rewrites it on every filter change and, before this, said nothing to
 * a screen reader. aria-atomic matters as much as aria-live: without it the
 * reader announces only the number that changed, out of its sentence. */
test.describe('the result count speaks', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const ready = async (page) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 90000 });
    await page.waitForFunction(
      () => !/loading/i.test(document.getElementById('subcount').textContent), { timeout: 30000 });
  };

  test('#subcount is an atomic live region', async ({ page }) => {
    await ready(page);
    const a = await page.locator('#subcount').evaluate(e => ({
      role: e.getAttribute('role'),
      live: e.getAttribute('aria-live'),
      atomic: e.getAttribute('aria-atomic'),
    }));
    expect(a).toEqual({ role: 'status', live: 'polite', atomic: 'true' });
  });

  /* Undebounced, this region interrupted the reader on every letter and the
     count was never heard whole — and every keystroke rebuilt #facets.innerHTML
     and re-rendered the grid, the map layer and the graph filter over ~5,000
     records. Both problems have the same fix.

     The assertion has to be that nothing happened YET. A test that only checks
     the count eventually updates passes with the debounce removed. */
  test('typing is debounced, so the count is not rewritten per keystroke', async ({ page }) => {
    await ready(page);
    const count = () => page.locator('#subcount').textContent();

    const before = await count();
    await page.locator('#search').fill('anarch');

    await page.waitForTimeout(80);
    expect(await count(), 'the count moved before the debounce elapsed').toBe(before);

    await page.waitForTimeout(500);
    expect(await count(), 'the count never updated after the debounce').not.toBe(before);
  });
});

/* The status line answers TWO questions and has to keep them apart:
 *
 *   how much of the CORPUS matched   107 of 7,673
 *   how much of the MATCH is drawn   34 mapped
 *
 * The old chrome carried these in two places — the header said "107 of 7,673
 * blogs match" and the map card said "34 of 4620 blogs". Deleting the card
 * made this line take over the card's job and silently drop the header's: on
 * the Map view it read "34 of 107 mapped", which loses the corpus entirely and
 * reads as though the dataset were 107.
 *
 * Short is a requirement, not a preference: the header is what the map's
 * height is calculated from, so a line that wraps shrinks the thing it
 * describes. test_disclaimer.spec.js holds the one-line rule at 390px.
 */
test.describe('the status line keeps the corpus and the map count apart', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const read = async (page, query) => {
    await page.goto(HOST + '/noblogs/' + query, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => !/loading/i.test(document.getElementById('subcount').textContent), { timeout: 90000 });
    if (query.includes('view=map')) {
      await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
      await page.waitForTimeout(400);
    }
    return page.locator('#subcount').textContent();
  };

  test('a filtered map view names the corpus AND the pins', async ({ page }) => {
    const t = await read(page, '?view=map&q=russia');
    // The whole corpus has to still be in there. This is the regression.
    expect(t, `corpus total dropped from the map view: "${t}"`).toMatch(/7,673/);
    expect(t, `match count missing: "${t}"`).toMatch(/107/);
    expect(t, `pin count missing: "${t}"`).toMatch(/\b34\b/);
  });

  test('a filtered list view names the corpus and does not claim pins', async ({ page }) => {
    const t = await read(page, '?view=dash&q=russia');
    expect(t).toMatch(/107/);
    expect(t).toMatch(/7,673/);
    expect(t, 'the List view has no map to count pins on').not.toMatch(/mapped/);
  });

  test('an unfiltered view does not print a fraction of itself', async ({ page }) => {
    const t = await read(page, '?view=dash');
    expect(t, `"7,673 of 7,673" is a fraction nobody needs: "${t}"`).not.toMatch(/of 7,673/);
    expect(t).toMatch(/7,673/);
  });
});
