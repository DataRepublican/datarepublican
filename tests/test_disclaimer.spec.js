const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The disclaimer is the one piece of text on this site with legal consequence,
 * and it was the smallest type on the page: 10–11px across three copies,
 * clipped to a few lines on a phone with a click handler bolted onto a <p>.
 *
 * TWO MECHANISMS, deliberately, and this file is split along that line.
 *
 * noblogs opens a modal <dialog>. Its callout was a permanent full-width amber
 * band under the header whose resting state was the word "Disclaimer" and a
 * triangle — a row of a 390px screen spent, on every view, on a notice read
 * once if ever. dsa-explorer still uses the <details> callout; it has not been
 * through this pass yet, and the design system's adoption rule is to migrate
 * what you touched and only what you touched.
 *
 * What both must satisfy is the same and is what these specs actually assert:
 * the full text is reachable without a pointer, and it is never the smallest
 * type on the page. */

const FULL_TEXT_MIN = 300;

test.describe('noblogs disclaimer (modal dialog)', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const open = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#nb-disclaimer-open', { timeout: 60000 });
  };

  test('is closed at rest and costs the header no height', async ({ page }) => {
    await open(page);
    expect(await page.locator('#nb-disclaimer').evaluate(e => e.open)).toBe(false);

    /* Settle first. #subcount is a live region that the map rewrites once
       map_data.js lands, and an unsettled header was measuring the status line
       changing rather than the dialog opening. Poll until the height holds
       still for two reads — a fixed timeout just moves the race. */
    const h = () => page.evaluate(
      () => Math.round(document.getElementById('nb-header').offsetHeight));
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    let before = await h();
    await expect.poll(async () => {
      const now = await h();
      const stable = now === before;
      before = now;
      return stable;
    }, { timeout: 15000 }).toBe(true);

    // The old callout was in the header's flow, so opening it resized the map.
    // A modal is in the top layer and must not move layout at all.
    await page.locator('#nb-disclaimer-open').click();
    await page.waitForTimeout(250);
    expect(await h(), 'opening the disclaimer must not reflow the header').toBe(before);
  });

  test('the status line stays one line on a phone', async ({ page }) => {
    /* The header's height is what the map is sized against, so a status line
       that wraps is a status line that shrinks the map. The first version of
       the map-view count ran to three lines at 390px. */
    await open(page);
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForTimeout(500);

    const { lines, text } = await page.evaluate(() => {
      const el = document.getElementById('subcount');
      const cs = getComputedStyle(el);
      return {
        lines: Math.round(el.getBoundingClientRect().height / parseFloat(cs.lineHeight)),
        text: el.textContent,
      };
    });
    expect(lines, `the status line wraps: "${text}"`).toBeLessThanOrEqual(1);
  });

  test('the opener is a 44px target and the text is never the smallest type', async ({ page }) => {
    await open(page);
    const h = await page.locator('#nb-disclaimer-open')
      .evaluate(e => Math.round(e.getBoundingClientRect().height));
    expect(h, 'the opener is the tap target').toBeGreaterThanOrEqual(44);

    await page.locator('#nb-disclaimer-open').click();
    const px = await page.locator('#nb-disclaimer .dr-dialog__body')
      .evaluate(e => parseFloat(getComputedStyle(e).fontSize));
    expect(px, 'legal text below 13px').toBeGreaterThanOrEqual(13);
  });

  test('opens from the keyboard, traps focus, and Escape closes it', async ({ page }) => {
    await open(page);
    const dlg = page.locator('#nb-disclaimer');
    const body = page.locator('#nb-disclaimer .dr-dialog__body');

    await expect(body).toBeHidden();
    await page.locator('#nb-disclaimer-open').focus();
    await page.keyboard.press('Enter');

    await expect(body).toBeVisible();
    expect(await dlg.evaluate(e => e.open)).toBe(true);
    expect((await body.textContent()).length,
      'the full disclaimer should be present, not a clipped excerpt').toBeGreaterThan(FULL_TEXT_MIN);

    // showModal(), not show(). Only the modal form makes the rest of the
    // document inert and gives us Escape and a ::backdrop for free — if this
    // ever regresses to show(), the whole reason for using <dialog> is gone.
    expect(await dlg.evaluate(e => e.matches(':modal')),
      'must be opened with showModal(), not show()').toBe(true);

    await page.keyboard.press('Escape');
    await expect(body).toBeHidden();
    expect(await dlg.evaluate(e => e.open)).toBe(false);
  });

  test('returns focus to the opener on close', async ({ page }) => {
    await open(page);
    await page.locator('#nb-disclaimer-open').focus();
    await page.keyboard.press('Enter');
    await page.locator('#nb-disclaimer-close').click();
    // The platform does this; the test is here so a hand-rolled replacement
    // cannot quietly drop it.
    expect(await page.evaluate(() => document.activeElement.id)).toBe('nb-disclaimer-open');
  });
});

test.describe('dsa-explorer disclaimer (details callout)', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('is a real details, closed, with a 44px summary', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    const d = page.locator('details.disclaimer');
    await expect(d).toBeVisible();
    expect(await d.evaluate(e => e.open)).toBe(false);

    const h = await page.locator('details.disclaimer > summary')
      .evaluate(e => Math.round(e.getBoundingClientRect().height));
    expect(h, 'the summary is the tap target').toBeGreaterThanOrEqual(44);
  });

  test('is never the smallest type on the page', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.locator('details.disclaimer > summary').click();

    const px = await page.locator('details.disclaimer .disclaimer-body')
      .evaluate(e => parseFloat(getComputedStyle(e).fontSize));
    expect(px, 'legal text below 13px').toBeGreaterThanOrEqual(13);
  });

  test('opens from the keyboard and reveals the full text', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    const d = page.locator('details.disclaimer');
    const body = page.locator('details.disclaimer .disclaimer-body');

    await expect(body).toBeHidden();
    await page.locator('details.disclaimer > summary').focus();
    await page.keyboard.press('Enter');

    await expect(body).toBeVisible();
    expect(await d.evaluate(e => e.open)).toBe(true);
    expect((await body.textContent()).length,
      'the full disclaimer should be present, not a clipped excerpt').toBeGreaterThan(FULL_TEXT_MIN);
  });
});

test.describe('noblogs header measurement', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('--nb-header-h matches the real header height', async ({ page }) => {
    /* The map and the graph are sized against this number, and the tool used to
       be full of a literal 56px that was only right on one screen.

       This used to assert that opening the disclaimer made the header TALLER
       and that the variable followed. It cannot any more, and that is the
       point: the header is a fixed three-row column and the disclaimer is a
       modal, so nothing in normal use reflows it. The measurement still has to
       be correct, so that is what is checked. */
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#nb-header .nb-toolbar', { timeout: 60000 });
    await page.waitForTimeout(250);

    const { v, real, masthead } = await page.evaluate(() => ({
      v: parseInt(getComputedStyle(document.documentElement)
            .getPropertyValue('--nb-header-h'), 10),
      real: Math.round(document.getElementById('nb-header').offsetHeight),
      // The site masthead is also a <header> and comes first in the DOM, so a
      // bare querySelector('header') measured the wrong element.
      masthead: Math.round(document.querySelector('header.page-column').offsetHeight),
    }));

    expect(v).toBe(real);
    expect(v).not.toBe(masthead);
  });
});
