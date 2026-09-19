const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Two different things, deliberately not the same thing.
 *
 * /about/ carries the laurel pull quotes — short, typeset by us, no network.
 * /donate/ carries the tweet wall from the pre-redesign homepage, which is
 * Twitter's embeds and Twitter's iframes. The first version of this page had
 * the pull quotes on both, which read as a repeat.
 */

test.describe('the /about/ pull quotes', () => {
  test('every quote is attributed with a link', async ({ page }) => {
    await page.goto(`${HOST}/about/`);
    const figures = page.locator('figure:has(blockquote)');
    const count = await figures.count();
    expect(count, 'the laurel quotes are gone from /about/').toBeGreaterThan(1);

    for (let i = 0; i < count; i++) {
      const link = figures.nth(i).locator('figcaption a');
      await expect(link).toHaveAttribute('href', /^https?:\/\//);
      expect((await link.textContent()).trim()).not.toBe('');
    }
  });
});

test.describe('the /donate/ tweet wall', () => {
  /* Counts come from the SHIPPED HTML, never from the live DOM. widgets.js
     swaps one blockquote at a time, so mid-upgrade the page holds the original
     and its replacement at once and a DOM count reads roughly double. */
  const shippedHtml = async (request, route) =>
    (await request.get(HOST + route)).text();

  test('renders the embeds, and they upgrade to real tweets', async ({ page, request }) => {
    const html = await shippedHtml(request, '/donate/');
    const shipped = (html.match(/<blockquote class="twitter-tweet"/g) || []).length;
    expect(shipped, 'no tweets in the markup at all').toBeGreaterThan(4);

    await page.goto(`${HOST}/donate/`, { waitUntil: 'load' });
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

    expect(await loaders('/donate/')).toBe(1);
    for (const route of ['/', '/about/', '/browse/']) {
      expect(await loaders(route), `${route} loads widgets.js`).toBe(0);
    }
  });
});
