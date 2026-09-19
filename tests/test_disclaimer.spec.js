const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The disclaimer is the one piece of text on this site with legal consequence,
 * and it was the smallest type on the page: 10–11px across three copies,
 * clipped to a few lines on a phone with a click handler bolted onto a <p>.
 *
 * Both tools open a modal <dialog> now. The callout it replaced was a
 * permanent full-width amber band under the header whose resting state was the
 * word "Disclaimer" and a triangle — a row of a 390px screen spent, on every
 * view, on a notice read once if ever.
 *
 * What these specs actually assert: the full text is reachable without a
 * pointer, it is never the smallest type on the page, opening it does not move
 * the layout, and it rises on the site's one sheet motion. */

const FULL_TEXT_MIN = 300;
const TOOLS = [
  { name: 'noblogs', path: '/noblogs/?view=map', id: 'nb',
    header: '#nb-header', ready: '.leaflet-marker-icon, .marker-cluster' },
  { name: 'dsa-explorer', path: '/dsa-explorer/', id: 'dsa',
    header: '#dsa-header', ready: '#cy canvas' },
];

for (const t of TOOLS) {
  const OPEN = `#${t.id}-disclaimer-open`;
  const DLG = `#${t.id}-disclaimer`;
  const CLOSE = `#${t.id}-disclaimer-close`;

  test.describe(`${t.name} disclaimer (modal dialog)`, () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

    const open = async (page) => {
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(OPEN, { timeout: 60000 });
    };

    test('is closed at rest and costs the header no height', async ({ page }) => {
      await open(page);
      expect(await page.locator(DLG).evaluate(e => e.open)).toBe(false);

      /* Settle first: a live status line rewrites itself once the data lands,
         and an unsettled header measures that rather than the dialog. Poll
         until the height holds still — a fixed timeout just moves the race. */
      const h = () => page.evaluate(
        (sel) => Math.round(document.querySelector(sel).offsetHeight), t.header);
      await page.waitForSelector(t.ready, { timeout: 90000 });
      let before = await h();
      await expect.poll(async () => {
        const now = await h();
        const stable = now === before;
        before = now;
        return stable;
      }, { timeout: 15000 }).toBe(true);

      // The old callout was in the header's flow, so opening it resized the
      // canvas. A modal is in the top layer and must not move layout at all.
      await page.locator(OPEN).click();
      await page.waitForTimeout(250);
      expect(await h(), 'opening the disclaimer must not reflow the header').toBe(before);
    });

    test('the opener is a 44px target and the text is never the smallest type', async ({ page }) => {
      await open(page);
      const h = await page.locator(OPEN)
        .evaluate(e => Math.round(e.getBoundingClientRect().height));
      expect(h, 'the opener is the tap target').toBeGreaterThanOrEqual(44);

      await page.locator(OPEN).click();
      const px = await page.locator(`${DLG} .dr-dialog__body`)
        .evaluate(e => parseFloat(getComputedStyle(e).fontSize));
      expect(px, 'legal text below 13px').toBeGreaterThanOrEqual(13);
    });

    test('opens from the keyboard, traps focus, and Escape closes it', async ({ page }) => {
      await open(page);
      const dlg = page.locator(DLG);
      const body = page.locator(`${DLG} .dr-dialog__body`);

      await expect(body).toBeHidden();
      await page.locator(OPEN).focus();
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

    test('rises from the bottom edge, on the same motion as the sheet', async ({ page }) => {
      /* It shipped with no transition at all, while the detail sheet eight
         pixels away slid — two bottom-anchored surfaces, two different physics.
         There is one bottom-sheet motion on this site and both use it.

         `allow-discrete` on display/overlay is the part that is easy to lose: a
         <dialog> leaves the top layer the instant close() is called, so without
         it the OPEN direction animates and the close direction silently does
         not. Both durations are asserted for that reason. */
      await open(page);
      const props = await page.evaluate((sel) => {
        const cs = getComputedStyle(document.querySelector(sel));
        return { transition: cs.transitionProperty, duration: cs.transitionDuration };
      }, DLG);
      expect(props.transition).toContain('transform');
      expect(props.transition, 'a dialog without allow-discrete cannot animate closed')
        .toContain('display');
      expect(props.transition).toContain('overlay');
      expect(props.duration).toMatch(/0\.24s|240ms/);

      /* And it actually moves. The closed state cannot be read from
         getComputedStyle — a closed <dialog> is display:none, so its transform
         resolves to "none" no matter what the rule says — so sample the
         position mid-flight instead. */
      const top = () => page.evaluate(
        (sel) => document.querySelector(sel).getBoundingClientRect().top, DLG);
      await page.locator(OPEN).click();
      const mid = await top();
      await page.waitForTimeout(500);
      const settled = await top();
      expect(mid, 'the dialog appears in place instead of rising').toBeGreaterThan(settled);
    });

    test('returns focus to the opener on close', async ({ page }) => {
      await open(page);
      await page.locator(OPEN).focus();
      await page.keyboard.press('Enter');
      await page.locator(CLOSE).click();
      // The platform does this; the test is here so a hand-rolled replacement
      // cannot quietly drop it.
      expect(await page.evaluate(
        () => document.activeElement.id)).toBe(`${t.id}-disclaimer-open`);
    });
  });
}

test.describe('noblogs status line', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('stays one line on a phone', async ({ page }) => {
    /* The header's height is what the map is sized against, so a status line
       that wraps is a status line that shrinks the map. The first version of
       the map-view count ran to three lines at 390px. */
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
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
