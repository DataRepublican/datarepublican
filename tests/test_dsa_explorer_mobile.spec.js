const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';
const PHONE = { width: 390, height: 844 };

// The audit finding this guards: on a phone, tapping a node in a graph tool
// produced no visible response, because the detail panel stacked *below* a
// ~700px canvas. These assertions are about reachability, not appearance —
// the existing specs prove the page loads and the data is right, and a tool
// can pass both while being unusable with a thumb.

async function loadGraph(page) {
  await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#cy canvas', { timeout: 60000 });
  // The layout is baked from positions.json, but logos reveal in idle chunks.
  await page.waitForTimeout(4000);
}

const box = (page, sel) =>
  page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  }, sel);

test.describe('dsa-explorer on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true, isMobile: true });

  test('controls are reachable and tappable', async ({ page }) => {
    await loadGraph(page);

    const search = await box(page, '#search');
    const controls = await box(page, '#controls');
    expect(search).not.toBeNull();
    expect(controls).not.toBeNull();

    // These two used to overlap by ~125px, and the search field painted over
    // Zoom / Reset view / Re-layout / Export PNG, which were unreachable.
    const overlaps =
      !(search.x + search.w <= controls.x || controls.x + controls.w <= search.x ||
        search.y + search.h <= controls.y || controls.y + controls.h <= search.y);
    expect(overlaps, 'search must not cover the control cluster').toBe(false);

    // 44px minimum on every control.
    const small = await page.evaluate(() =>
      [...document.querySelectorAll('#controls button')]
        .map((b) => ({ id: b.id || b.textContent.trim(), h: Math.round(b.getBoundingClientRect().height) }))
        .filter((b) => b.h < 44)
    );
    expect(small, `controls under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });

  test('tapping a node opens the detail sheet over the canvas', async ({ page }) => {
    await loadGraph(page);

    const sheet = page.locator('.dr-sheet');
    await expect(sheet).not.toHaveClass(/is-open/);

    // Drive the canvas centre, where the DSA hub sits.
    await page.evaluate(() => {
      const el = document.querySelector('#cy canvas');
      const r = el.getBoundingClientRect();
      const x = r.x + r.width / 2;
      const y = r.y + r.height / 2;
      for (const t of ['mousedown', 'mouseup', 'click']) {
        el.dispatchEvent(new MouseEvent(t, { clientX: x, clientY: y, bubbles: true }));
      }
    });

    await expect(sheet).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(400); // let the transition finish

    const b = await box(page, '.dr-sheet');
    const vh = PHONE.height;
    // The whole point: the response is on screen, not 700px below it.
    expect(b.y).toBeGreaterThan(0);
    expect(b.y).toBeLessThan(vh);
    expect(b.h).toBeGreaterThan(200);

    // The nav pill must not sit on top of the sheet.
    const navDisplay = await page.evaluate(
      () => getComputedStyle(document.querySelector('nav[aria-label="Primary"]')).display
    );
    expect(navDisplay).toBe('none');

    // The grip and close button must survive the panel's innerHTML being
    // rewritten by the tool on every tap — they live in a wrapper for exactly
    // this reason.
    await expect(page.locator('.dr-sheet__grip')).toBeVisible();
    await expect(page.locator('.dr-sheet__close')).toBeVisible();
  });
});

test.describe('dsa-explorer on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('the panel is still a side column, not a sheet', async ({ page }) => {
    await loadGraph(page);

    const stage = await box(page, '#stage');
    const panel = await box(page, '#panel');

    // `.dr-sheet` is display:contents here so the panel stays a grid child.
    expect(panel.x).toBeGreaterThanOrEqual(stage.x + stage.w - 2);
    expect(panel.w).toBeGreaterThan(300);

    // Sheet furniture is hidden. This regressed once: the base `display: none`
    // was purged by Tailwind because the class only exists at runtime, so the
    // drag handle appeared on desktop.
    await expect(page.locator('.dr-sheet__grip')).toBeHidden();
    await expect(page.locator('.dr-sheet__close')).toBeHidden();
  });
});

// The logos were four .embed.js blobs totalling 23.4 MB of base64 PNG, loaded
// as blocking scripts before anything rendered. They are image files now, and
// logos/index.js is the 73 KB manifest. On Fast 3G this took the graph from
// 120.6s to 7.9s.
test.describe('dsa-explorer logo payload', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('no base64 logo blobs are loaded', async ({ page }) => {
    const blobs = [];
    page.on('request', (r) => { if (/\.embed\.js(\?|$)/.test(r.url())) blobs.push(r.url()); });

    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 60000 });
    await page.waitForTimeout(4000);

    expect(blobs, `embed.js still loaded: ${blobs.join(', ')}`).toEqual([]);

    // Logos resolve to paths, not data URIs, and the graph still draws them.
    const info = await page.evaluate(() => {
      const withLogo = cy.nodes().filter((n) => n.data('hasLogo') === 1);
      return {
        count: withLogo.length,
        allPaths: withLogo.map((n) => n.data('logoUri')).every((u) => u.startsWith('logos/img/')),
        globalKB: Math.round(JSON.stringify(window.LOGOS).length / 1024),
      };
    });
    expect(info.count).toBeGreaterThan(400);
    expect(info.allPaths, 'every logoUri should be a path').toBe(true);
    expect(info.globalKB, 'window.LOGOS should be a manifest, not the images').toBeLessThan(200);
  });
});
