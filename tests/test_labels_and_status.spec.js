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
