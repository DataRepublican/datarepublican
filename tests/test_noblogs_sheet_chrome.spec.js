const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The bottom sheet's own chrome, and the things a consumer has to agree with it
 * about. All three failures here were visible on /noblogs/?view=dash with a
 * blog selected, and all three came from the sheet and the panel it wraps
 * making different assumptions.
 */

test.describe('the noblogs detail sheet', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const openSheet = async (page) => {
    await page.goto(
      HOST + '/noblogs/?view=dash&host=antifascistchicago.noblogs.org',
      { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.dr-sheet.is-open', { timeout: 60000 });
    await page.waitForTimeout(400); // the rise
  };

  test('has ONE close button, not two', async ({ page }) => {
    await openSheet(page);
    // DRSheet puts a close in its wrapper and the tool has its own .pclose.
    // Stacked on a phone, the panel grew two X's in two header bars.
    const visible = await page.evaluate(() => {
      const inSheet = [...document.querySelectorAll('.dr-sheet button')];
      return inSheet.filter(b => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
          (b.className || '').match(/close|pclose/);
      }).map(b => b.className);
    });
    expect(visible, `close buttons visible: ${JSON.stringify(visible)}`).toHaveLength(1);
  });

  test('is one continuous surface — no white band above or below the content', async ({ page }) => {
    await openSheet(page);
    // #panel sits on the PAGE ground by design; the sheet defaulted to #fff, so
    // the grip row and the safe-area padding painted white strips that read as
    // a header and a footer the sheet does not have.
    const c = await page.evaluate(() => {
      const sheet = document.querySelector('.dr-sheet');
      const grip = document.querySelector('.dr-sheet__grip');
      const panel = document.getElementById('panel');
      const bg = el => getComputedStyle(el).backgroundColor;
      return { sheet: bg(sheet), grip: bg(grip), panel: bg(panel) };
    });
    expect(c.sheet).toBe(c.panel);
    expect(c.grip).toBe(c.panel);
  });

  test('reserves room for the close button at the top', async ({ page }) => {
    await openSheet(page);
    // The grip is the sheet's header row and has to be at least as tall as the
    // 44px close pinned into it, or the close overhangs whatever the panel
    // renders first.
    const m = await page.evaluate(() => {
      const grip = document.querySelector('.dr-sheet__grip').getBoundingClientRect();
      const close = document.querySelector('.dr-sheet__close').getBoundingClientRect();
      const body = document.getElementById('panel').getBoundingClientRect();
      return { gripH: Math.round(grip.height), closeBottom: close.bottom, bodyTop: body.top };
    });
    expect(m.gripH).toBeGreaterThanOrEqual(44);
    expect(m.closeBottom, 'the close button overhangs the panel content')
      .toBeLessThanOrEqual(m.bodyTop + 1);
  });
});

test.describe('the filter popover reset', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const openFilters = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#nb-filters', { timeout: 60000 });
    await page.click('#nb-filters');
    await page.waitForSelector('#facets .clearf', { timeout: 30000 });
  };

  test('is disabled and right-aligned until something is selected', async ({ page }) => {
    await openFilters(page);
    const clear = page.locator('#facets .clearf');

    await expect(clear).toBeDisabled();
    await expect(clear).toHaveText(/Clear all filters/);

    // Trailing edge of the panel, not the leading one, where it read as the
    // first item of the first filter group.
    const aligned = await page.evaluate(() => {
      const el = document.querySelector('#facets .clearf');
      const panel = document.getElementById('facets');
      const er = el.getBoundingClientRect(), pr = panel.getBoundingClientRect();
      const pad = parseFloat(getComputedStyle(panel).paddingRight);
      return Math.abs((pr.right - pad) - er.right) < 2;
    });
    expect(aligned, 'the reset is not right-aligned in the panel').toBe(true);

    await page.locator('#facets .fitem[data-f="cat"] input').first().check();
    await expect(clear).toBeEnabled();
  });

  test('the count badge is not vertically squashed', async ({ page }) => {
    await openFilters(page);
    await page.locator('#facets .fitem[data-f="cat"] input').first().check();
    await page.waitForTimeout(200);

    const b = await page.locator('#nb-filtercount').evaluate(e => {
      const r = e.getBoundingClientRect();
      return { w: r.width, h: r.height };
    });
    // A flex item with only padding gets squashed to the line box. It has to
    // state its own box, and a single digit should be round-ish.
    expect(b.h).toBeGreaterThanOrEqual(18);
    expect(Math.abs(b.w - b.h), `badge is ${b.w}x${b.h}`).toBeLessThan(6);
  });
});
