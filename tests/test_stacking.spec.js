const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The detail surface must paint over the canvas, at both widths.
 *
 * These assert what an element at a point actually IS, rather than comparing
 * z-index numbers, because the bug they cover could not be seen from the
 * numbers. noblogs was running 600/850/900/1000/1100/1150/1200 and its mobile
 * sheet — z-index 60 — still opened underneath the map, because Leaflet's panes
 * were never in the same stacking contest: #mapwrap had no stacking context, so
 * .leaflet-top at 1000 was hoisted into the root one.
 *
 * A number can be high and still lose. elementFromPoint cannot be fooled that
 * way, so that is what these ask.
 */

test.describe('the detail surface paints over the map', () => {
  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

    test('the sheet is above the Leaflet panes, not under them', async ({ page }) => {
      await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });

      await page.evaluate(() => openModal(Object.keys(BYHOST)[0]));
      await expect(page.locator('.dr-sheet')).toHaveClass(/is-open/, { timeout: 5000 });
      await page.waitForTimeout(450);   // the 240ms transform, with headroom

      /* Sample inside the intersection of the sheet and the canvas, and nowhere
         else. The obvious point — a little below the sheet's top edge — is
         worthless here: at 390px the tool header is tall enough to push the map
         down to y≈559 while the half-detent sheet starts at y≈380, so that
         point lands in the tab strip and the assertion passes whatever the
         stacking does. Ask for the overlap explicitly, and fail loudly if there
         isn't one, because then the test is measuring nothing. */
      const hit = await page.evaluate(() => {
        const s = document.querySelector('.dr-sheet').getBoundingClientRect();
        const m = document.getElementById('mapwrap').getBoundingClientRect();
        const top = Math.max(s.top, m.top);
        const bottom = Math.min(s.bottom, m.bottom, window.innerHeight);
        if (bottom - top < 8) return { overlap: false, top, bottom };
        const y = (top + bottom) / 2;
        const x = Math.max(s.left, m.left) + Math.min(s.width, m.width) / 2;
        const el = document.elementFromPoint(x, y);
        return {
          overlap: true,
          point: { x: Math.round(x), y: Math.round(y) },
          inSheet: !!(el && el.closest('.dr-sheet')),
          got: el && `${el.tagName.toLowerCase()}.${(el.className || '').toString().slice(0, 40)}`,
        };
      });

      expect(hit.overlap, 'sheet and canvas do not overlap — this test proves nothing').toBe(true);
      expect(hit.inSheet,
        `the map is painting over the open sheet at ${JSON.stringify(hit.point)}; hit ${hit.got}`
      ).toBe(true);
    });

    test('the canvas is an isolated box', async ({ page }) => {
      await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#mapwrap', { timeout: 60000 });
      const iso = await page.evaluate(
        () => getComputedStyle(document.getElementById('mapwrap')).isolation
      );
      expect(iso, 'without this every Leaflet pane escapes into the root context').toBe('isolate');
    });
  });

  test.describe('on a desktop', () => {
    test.use({ viewport: { width: 1280, height: 900 } });

    test('the zoom control does not float over the open drawer', async ({ page }) => {
      await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.leaflet-control-zoom', { timeout: 90000 });

      await page.evaluate(() => openModal(Object.keys(BYHOST)[0]));
      await page.waitForTimeout(450);

      const leafletOnTop = await page.evaluate(() => {
        const z = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
        const p = document.getElementById('panel').getBoundingClientRect();
        const overlaps = !(z.right <= p.left || p.right <= z.left ||
                           z.bottom <= p.top || p.bottom <= z.top);
        if (!overlaps) return false;          // nothing to fight over
        const el = document.elementFromPoint(z.x + z.width / 2, z.y + z.height / 2);
        return !(el && el.closest('#panel'));
      });
      expect(leafletOnTop, 'Leaflet is painting over the open drawer').toBe(false);
    });
  });
});

/* Chrome INSIDE the canvas must also stay above the vendor.
 *
 * The first version of the isolation fix put `isolation: isolate` on #mapwrap
 * only. That contains Leaflet relative to the rest of the page — the sheet and
 * the drawer were fixed by it — but #mapcanvas is position:absolute with
 * z-index:auto, so Leaflet's panes were hoisted exactly one level and competed
 * inside #mapwrap against the info card at 20. Leaflet's .leaflet-top is 1000,
 * so it won, and the card carrying the category filters stopped taking clicks:
 * elementFromPoint over it returned canvas.leaflet-zoom-animated.
 *
 * The tests above did not catch it because they all ask about the sheet and the
 * drawer, which live in the ROOT context. Nothing asked about chrome inside the
 * isolated box. This does. */
test.describe('the map chrome is above the map', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  /* The info card this used to open on is gone — it was permanent chrome
     covering Leaflet's own zoom control, and its contents moved into the filter
     popover. The popover is what sits over the canvas now, so it is what has to
     win the click. Same property, same failure mode, different element. */
  test('the filter popover takes the click, not the Leaflet canvas', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.click('#nb-filters');
    await page.waitForSelector('#facets .fitem[data-f="cat"]', { timeout: 30000 });

    const hit = await page.evaluate(() => {
      const row = document.querySelector('#facets .fitem[data-f="cat"]');
      const r = row.getBoundingClientRect();
      const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return { onRow: el === row || row.contains(el),
               got: el && `${el.tagName.toLowerCase()}.${(el.className || '').toString().slice(0, 40)}` };
    });
    expect(hit.onRow, `Leaflet is covering the filter popover; hit ${hit.got}`).toBe(true);
  });

  test('both the wrapper and the Leaflet container are isolated', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#mapcanvas', { timeout: 60000 });
    const iso = await page.evaluate(() => ({
      wrap: getComputedStyle(document.getElementById('mapwrap')).isolation,
      canvas: getComputedStyle(document.getElementById('mapcanvas')).isolation,
    }));
    expect(iso.wrap).toBe('isolate');
    expect(iso.canvas, 'without this Leaflet escapes one level and covers the chrome').toBe('isolate');
  });
});

/* One scale, and nothing this repo authors goes above it. The cap is what stops
   the next vendored stylesheet restarting the arms race: you contain a high
   z-index with `isolation: isolate`, you never out-bid it. */
test.describe('the z-index scale holds', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const path of ['/', '/noblogs/?view=map', '/noblogs/?view=graph', '/dsa-explorer/', '/about/']) {
    test(`${path} authors nothing above 100`, async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2500);

      const offenders = await page.evaluate(() => {
        const out = [];
        for (const el of document.querySelectorAll('*')) {
          // Vendored subtrees are allowed their own numbers — that is the whole
          // point of containing them rather than competing with them.
          if (el.closest('.leaflet-pane, .leaflet-control-container, #cy, #graphwrap')) continue;
          const z = getComputedStyle(el).zIndex;
          if (z !== 'auto' && Number(z) > 100) {
            out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} = ${z}`);
          }
        }
        return out;
      });
      expect(offenders, `above the scale: ${offenders.join(', ')}`).toEqual([]);
    });
  }
});
