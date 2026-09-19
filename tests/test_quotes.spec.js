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
