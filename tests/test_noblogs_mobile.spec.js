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

    // No iframe for the map any more — it is this document's own DOM.
    const framesInMapView = await page.locator('#mapview iframe').count();
    expect(framesInMapView).toBe(0);

    await expect(page.locator('#maploading')).toBeHidden();
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
