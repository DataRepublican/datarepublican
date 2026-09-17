const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

// Three blockers a code review caught that the existing suite did not. Each was
// a selector left pointing at something a refactor had renamed or restructured,
// so the page rendered and the data was right — only a control was dead. The
// specs below exercise the control, not its presence.

test.describe('graph chrome survives the extraction', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const load = async (page) => {
    await page.goto(HOST + '/noblogs/graph/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof cy !== 'undefined' && typeof cy.nodes === 'function' && cy.nodes().length > 0,
      { timeout: 90000 }
    );
    await page.waitForTimeout(2500);
  };

  test('the detail panel actually collapses', async ({ page }) => {
    await load(page);
    // graph.js puts `collapsed` on the root, but the CSS still said
    // `.nbgraph #app.collapsed` — #app having been deleted by the extraction.
    // Nothing matched, so the graph booted showing an empty 370px aside and the
    // toggle did nothing.
    const cols = () => page.evaluate(
      () => getComputedStyle(document.getElementById('graphroot')).gridTemplateColumns
    );
    const collapsed = await cols();
    await page.click('#panelToggle');
    await page.waitForTimeout(300);
    const expanded = await cols();
    expect(collapsed).not.toBe(expanded);
    expect(expanded).toMatch(/370px/);
  });

  test('the search box keeps its overlay positioning', async ({ page }) => {
    await load(page);
    // #search was renamed #gsearch to stop colliding with the explorer's own
    // #search; only the phone media query was updated, so at desktop width the
    // field fell into #stage's flow and out of view.
    const s = await page.evaluate(() => {
      const el = document.getElementById('gsearch');
      const r = el.getBoundingClientRect();
      return { position: getComputedStyle(el).position, width: r.width, top: r.top };
    });
    expect(s.position).toBe('absolute');
    expect(s.width).toBeGreaterThan(100);
  });
});

test.describe('dsa-explorer legend is reachable on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('the toggle is visible and opens the ideology filter', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });
    await page.waitForTimeout(3500);

    // The mobile rule hid .legbar — which contains .legtoggle, the only control
    // that can expand the legend. The ideology filter, the tool's main faceting
    // control, was unreachable on a phone.
    const toggle = page.locator('#legToggle');
    await expect(toggle).toBeVisible();
    expect(await toggle.evaluate((e) => Math.round(e.getBoundingClientRect().height)))
      .toBeGreaterThanOrEqual(44);

    await expect(page.locator('#legend .legchips')).toBeHidden();
    await toggle.click();
    await expect(page.locator('#legend .legchips')).toBeVisible();
  });
});

test.describe('standalone map popup', () => {
  test.use({ viewport: { width: 1200, height: 800 } });

  test('offers a way to reach the blog', async ({ page }) => {
    await page.goto(HOST + '/noblogs/world_hyperlocal_map.html', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForTimeout(2500);

    // Rewriting the popup dropped the hostname and the outbound link. On this
    // page the popup IS the detail view, so there was no way to reach the blog.
    const openOne = async () => {
      await page.evaluate(() => document.querySelector('.leaflet-marker-icon')?.click());
      await page.waitForTimeout(800);
      return page.locator('.leaflet-popup-content').first().innerHTML().catch(() => '');
    };
    let html = await openOne();
    if (!html) {
      await page.evaluate(() => document.querySelector('.marker-cluster')?.click());
      await page.waitForTimeout(1500);
      html = await openOne();
    }
    expect(html, 'no popup opened').toBeTruthy();
    expect(html).toMatch(/href="https:\/\//);
    expect(html).toContain('full details');
  });
});
