const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

// These use real clicks rather than dispatched events on purpose. A synthetic
// MouseEvent goes straight to its target and cannot be intercepted, so it will
// happily pass while a transparent full-screen overlay is eating every tap a
// real thumb makes — which is exactly the bug this suite caught in the sheet
// scrim.

test.describe('noblogs on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('lands on the dashboard and does not fetch the map payload', async ({ page }) => {
    const fetched = [];
    page.on('request', (r) => {
      const u = r.url();
      if (u.includes('map_data.js') || u.includes('/map.js') || u.includes('leaflet')) fetched.push(u);
    });

    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    await expect(page.locator('.tab.on')).toHaveAttribute('data-v', 'dash');

    // map_data.js is 3.68 MB. The Map tab loads it, Leaflet and map.js on first
    // activation; landing on the dashboard must not. This replaces the old
    // check that the iframe had no src — there is no iframe now, so the
    // question is whether the payload was requested at all.
    expect(fetched, `map payload fetched on landing: ${fetched.join(', ')}`).toEqual([]);
    await expect(page.locator('#mapcanvas')).toHaveCount(1);
  });

  test('the Map tab loads the module and renders pins', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    await page.click('.tab[data-v="map"]');
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });

    await expect(page.locator('#maploading')).toBeHidden();
  });

  // The whole page, not just one view. /noblogs was a shell driving two iframes
  // over postMessage; both are gone.
  test('there are no iframes anywhere on the page', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    expect(await page.locator('iframe').count()).toBe(0);

    for (const view of ['map', 'graph']) {
      await page.click(`.tab[data-v="${view}"]`);
      await page.waitForTimeout(1500);
      expect(await page.locator('iframe').count(), `iframe appeared in ${view}`).toBe(0);
    }
  });

  // quotes.embed.js is 2.0 MB. The frame boundary forced a second copy inside
  // the graph because the two documents could not share a global.
  test('quotes.embed.js is fetched once, not twice', async ({ page }) => {
    const hits = [];
    page.on('request', (r) => { if (r.url().includes('quotes.embed.js')) hits.push(r.url()); });

    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    await page.click('.tab[data-v="graph"]');
    await page.waitForSelector('#graphwrap #cy canvas', { timeout: 90000 });

    expect(hits.length, `quotes.embed.js requested ${hits.length} times`).toBe(1);
  });

  // The graph styles bare `header` and `aside` and owns #panel and #search.
  // That is why it was framed; scoping under .nbgraph is what replaced the frame.
  test('the graph does not restyle or collide with the explorer chrome', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    await page.click('.tab[data-v="graph"]');
    await page.waitForSelector('#graphwrap #cy canvas', { timeout: 90000 });

    // The explorer's sticky header must still be sticky.
    const pos = await page.evaluate(
      () => getComputedStyle(document.querySelector('header')).position
    );
    expect(pos).toBe('sticky');

    // Both panels exist, under different ids, exactly once each.
    expect(await page.locator('#panel').count()).toBe(1);
    expect(await page.locator('#graphwrap #gpanel').count()).toBe(1);
  });

  test('the header height is measured, not assumed to be 56px', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    const { varH, realH } = await page.evaluate(() => ({
      varH: parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nb-header-h'), 10),
      realH: Math.round(document.querySelector('header').offsetHeight),
    }));

    // The header is flex-wrap with a long disclaimer; at 390px it is taller
    // than the 56px the facet rail, scrim, drawer and both iframes assumed.
    expect(varH).toBe(realH);
    expect(realH).toBeGreaterThan(56);
  });

  test('filters open from one button and nothing intercepts the tap', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    await expect(page.locator('#facets')).toBeHidden();
    await page.click('#nb-filters', { timeout: 10000 });
    await expect(page.locator('#facets')).toBeVisible();
    await expect(page.locator('#nb-filters')).toHaveAttribute('aria-expanded', 'true');
  });

  test('tapping a card opens the detail sheet on screen', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    await page.click('.card', { timeout: 10000 });

    const sheet = page.locator('.dr-sheet');
    await expect(sheet).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(400);

    const b = await page.evaluate(() => {
      const r = document.querySelector('.dr-sheet').getBoundingClientRect();
      return { y: r.y, h: r.height, vh: window.innerHeight };
    });
    expect(b.y).toBeGreaterThan(0);
    expect(b.y).toBeLessThan(b.vh);
    expect(b.h).toBeGreaterThan(200);
  });

  test('the tab strip is tappable', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });

    const small = await page.evaluate(() =>
      [...document.querySelectorAll('.tab')]
        .map((t) => ({ v: t.dataset.v, h: Math.round(t.getBoundingClientRect().height) }))
        .filter((t) => t.h < 44)
    );
    expect(small, `tabs under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });
});

// noblogs/graph/logos.embed.js was 12.58 MB on the wire — the largest single
// asset on the site once the dsa-explorer blobs were dealt with. Same fix:
// image files plus a 31 KB manifest.
test.describe('noblogs graph logo payload', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('no base64 logo blob, and paths resolve from both depths', async ({ page }) => {
    const blobs = [];
    const notFound = [];
    page.on('request', (r) => { if (/logos\.embed\.js/.test(r.url())) blobs.push(r.url()); });
    page.on('response', (r) => { if (r.status() === 404) notFound.push(r.url()); });

    // The explorer loads graph.js from /noblogs/, the standalone page from
    // /noblogs/graph/. Logo paths are relative to graph/, so the module is told
    // its assetBase — get that wrong and every logo 404s from one of the two.
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    await page.click('.tab[data-v="graph"]');
    await page.waitForFunction(
      () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
      { timeout: 90000 }
    );
    await page.waitForTimeout(3000);

    expect(blobs, `logos.embed.js still loaded: ${blobs.join(', ')}`).toEqual([]);

    const sample = await page.evaluate(
      () => graphApi.cy.nodes().filter((n) => n.data('hasLogo') === 1).first().data('logoUri')
    );
    expect(sample).toMatch(/^graph\/img\//);
    expect(notFound.filter((u) => u.includes('/img/')), 'logo images 404ing').toEqual([]);
  });

  test('the standalone graph page resolves its own logo paths', async ({ page }) => {
    const notFound = [];
    page.on('response', (r) => { if (r.status() === 404) notFound.push(r.url()); });

    await page.goto(HOST + '/noblogs/graph/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof cy !== 'undefined' && typeof cy.nodes === 'function' && cy.nodes().length > 0,
      { timeout: 90000 }
    );
    await page.waitForTimeout(3000);

    const sample = await page.evaluate(
      () => cy.nodes().filter((n) => n.data('hasLogo') === 1).first().data('logoUri')
    );
    expect(sample).toMatch(/^img\//);
    expect(notFound.filter((u) => u.includes('/img/')), 'logo images 404ing').toEqual([]);
  });
});

// data.json is split at build time into an index the page paints from and a
// detail payload prefetched after first paint. The hard requirement is zero
// change in what is presented, so these check behaviour rather than bytes.
test.describe('noblogs deferred detail', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('paints from the index and does not fetch data.json', async ({ page }) => {
    const seen = [];
    page.on('request', (r) => {
      const u = r.url();
      if (/\/noblogs\/data(\.index|\.detail)?\.json/.test(u)) seen.push(u.split('/').pop());
    });

    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { state: 'attached', timeout: 90000 });

    // The index is what paints. The full 16.8 MB data.json must never be
    // fetched by the page — it stays published as the canonical artifact.
    expect(seen).toContain('data.index.json');
    expect(seen).not.toContain('data.json');
  });

  test('the detail payload arrives on its own and completes every blog', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { state: 'attached', timeout: 90000 });

    // Prefetched without anyone asking.
    await page.waitForFunction(() => detailReady === true, { timeout: 90000 });

    // Every deferred field is merged back onto the blog objects the rest of the
    // page already holds, so existing b.ne / b.ro / b.ri / b.inst reads work.
    const merged = await page.evaluate(() => {
      const withNews = DATA.filter((b) => Array.isArray(b.ne) && b.ne.length).length;
      const withRefs = DATA.filter((b) => Array.isArray(b.ri) && b.ri.length).length;
      return { withNews, withRefs, total: DATA.length };
    });
    expect(merged.total).toBe(7673);
    expect(merged.withNews).toBeGreaterThan(1000);
    expect(merged.withRefs).toBeGreaterThan(100);
  });

  test('a doxxing-flagged blog still renders no links', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { state: 'attached', timeout: 90000 });
    await page.waitForFunction(() => detailReady === true, { timeout: 90000 });

    const host = await page.evaluate(() => {
      const b = DATA.find((x) => x.dox && (x.ne || []).length);
      if (b) openModal(b.h);
      return b && b.h;
    });
    expect(host).toBeTruthy();
    await page.waitForTimeout(600);

    // News titles for flagged blogs render as <span>, never <a> — two of them
    // carry a URL inside the title text, so linkifying would republish it.
    const newsAnchors = await page.locator('#pinner .nart a').count();
    expect(newsAnchors, 'a doxxing-flagged blog must render no news links').toBe(0);
    await expect(page.locator('#pinner .nart')).not.toHaveCount(0);
  });

  test('the grid order is driven by the precomputed impact score', async ({ page }) => {
    await page.goto(HOST + '/noblogs/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { state: 'attached', timeout: 90000 });

    // rankBlogs() reads fields that are now partly deferred, so the score is
    // precomputed at build time. If the two ever disagree the grid silently
    // reshuffles — which is exactly what happened once, for 553 blogs.
    const ok = await page.evaluate(() => {
      const ctCount = (ct) => {
        const s = new Set();
        for (const g of Object.values(ct || {})) for (const ch of Object.keys(g)) s.add(ch);
        return s.size;
      };
      return DATA.every((b) => typeof b.imp === 'number' && b._imp === b.imp)
        && DATA.every((b) => b.imp >= ctCount(b.ct));
    });
    expect(ok).toBe(true);
  });
});
