const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* /about/ carries both kinds of praise, and they are not the same thing.
 *
 * The laurel pull quotes are a rail across from the narrative — short, typeset
 * by us, no network. The tweet wall underneath is Twitter's embeds in Twitter's
 * iframes. An earlier version had the pull quotes on /about/ AND /donate/,
 * which read as a repeat; /donate/ now carries neither.
 */

test.describe('the /about/ pull-quote rail', () => {
  test('every quote is attributed with a link', async ({ page }) => {
    await page.goto(`${HOST}/about/`);
    const figures = page.locator('aside figure:has(blockquote)');
    const count = await figures.count();
    expect(count, 'the laurel quotes are gone from /about/').toBeGreaterThan(1);

    for (let i = 0; i < count; i++) {
      const link = figures.nth(i).locator('figcaption a');
      await expect(link).toHaveAttribute('href', /^https?:\/\//);
      expect((await link.textContent()).trim()).not.toBe('');
    }
  });

  /* The point of the rail is that it sits ACROSS FROM the narrative rather
     than under it, and that it gives the width back on a phone. */
  test('sits beside the narrative at lg and stacks below it on a phone', async ({ page }) => {
    /* `main aside`, not a bare `aside`: the promo band is an <aside> too and
       it comes first in the DOM, so an unscoped query measures the banner and
       every assertion below reads as a layout failure. Same trap as the tool
       stylesheets styling bare `header` and reshaping the masthead. */
    const geom = async () => page.evaluate(() => {
      const rail = document.querySelector('main aside[aria-label]').getBoundingClientRect();
      const text = document.querySelector('.text-column').getBoundingClientRect();
      const wall = document.getElementById('praise-title')
        .closest('section').getBoundingClientRect();
      return {
        beside: rail.left >= text.right - 1,
        below: rail.top >= text.bottom - 1,
        railRight: Math.round(rail.right),
        wallRight: Math.round(wall.right),
      };
    });

    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto(`${HOST}/about/`);
    const wide = await geom();
    expect(wide.beside, 'the rail is not across from the narrative').toBe(true);
    // Sizing the narrative rather than the rail left it stopping short of the
    // tweet wall below, which read as a column that had failed to reach.
    expect(Math.abs(wide.railRight - wide.wallRight),
      'the rail does not line up with the wall under it').toBeLessThanOrEqual(1);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${HOST}/about/`);
    const narrow = await geom();
    expect(narrow.beside, 'the rail is still squeezing the text on a phone').toBe(false);
    expect(narrow.below).toBe(true);
  });

  /* The quotes lay themselves out from the CONTAINER, not the viewport, and
     these three rows are why that distinction is load-bearing: ~1000px of
     viewport is one wide block, while 1400px of viewport is a 480px rail. A
     media query sees the second number as the bigger one and would go two-up
     in the narrower box. */
  const LAYOUT = [
    { w: 560,  twoUp: false, note: 'one column while the block is narrow' },
    { w: 900,  twoUp: true,  note: 'two columns once the full-width block has room' },
    { w: 1400, twoUp: false, note: 'back to one column in the 480px rail' },
    { w: 1600, twoUp: true,  note: 'two again once the rail takes the extra width' },
  ];

  for (const { w, twoUp, note } of LAYOUT) {
    test(`at ${w}px: ${note}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: 1000 });
      await page.goto(`${HOST}/about/`);

      const m = await page.evaluate(() => {
        const rail = document.querySelector('main aside[aria-label]');
        const [a, b] = [...rail.querySelectorAll('figure')].map(f => f.getBoundingClientRect());
        const text = document.querySelector('.text-column').getBoundingClientRect();
        return {
          sideBySide: Math.abs(a.top - b.top) < 2,
          railRight: Math.round(rail.getBoundingClientRect().right),
          textRight: Math.round(text.right),
          textW: Math.round(text.width),
        };
      });

      expect(m.sideBySide).toBe(twoUp);
      // Below lg the block is capped at the same measure as the paragraphs; it
      // was overhanging their right edge by up to 150px around 1000px wide.
      if (w < 1024) {
        expect(Math.abs(m.railRight - m.textRight),
          'the quotes overhang the narrative').toBeLessThanOrEqual(1);
      } else {
        // Above lg the narrative stops at the reading measure and the rail
        // takes everything past it.
        expect(m.textW, 'the narrative is not at the reading measure').toBe(832);
      }
    });
  }
});

test.describe('the /about/ tweet wall', () => {
  /* Counts come from the SHIPPED HTML, never from the live DOM. widgets.js
     swaps one blockquote at a time, so mid-upgrade the page holds the original
     and its replacement at once and a DOM count reads roughly double. */
  const shippedHtml = async (request, route) =>
    (await request.get(HOST + route)).text();

  test('renders the embeds, and they upgrade to real tweets', async ({ page, request }) => {
    const html = await shippedHtml(request, '/about/');
    const shipped = (html.match(/<blockquote class="twitter-tweet"/g) || []).length;
    expect(shipped, 'no tweets in the markup at all').toBeGreaterThan(4);

    await page.goto(`${HOST}/about/`, { waitUntil: 'load' });
    await page.waitForFunction(
      (n) => document.querySelectorAll('.twitter-tweet-rendered').length >= n,
      shipped, { timeout: 60000 });

    // A deleted tweet upgrades to a "Not found" card rather than to nothing,
    // so a count of wrappers would not catch one. Each has to hold an iframe.
    expect(await page.locator('.twitter-tweet iframe').count()).toBe(shipped);
  });

  /* The loader is third-party, sets its own cookies, and exactly one page
     needs it. In head-custom.html it would load on all 34 routes. Asserted
     against the markup because widgets.js injects further platform.twitter.com
     scripts of its own once it runs. */
  test('the Twitter loader is on this page and nowhere else', async ({ request }) => {
    const loaders = async (route) =>
      ((await shippedHtml(request, route)).match(/platform\.twitter\.com/g) || []).length;

    expect(await loaders('/about/')).toBe(1);
    for (const route of ['/', '/donate/', '/browse/']) {
      expect(await loaders(route), `${route} loads widgets.js`).toBe(0);
    }
  });
});
