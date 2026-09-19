const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

// Reads what each page actually paints, not the data file — the point of
// _data/quotes.yml is that /about/ and /donate/ cannot drift apart, and the
// only way to catch drift is to compare the two rendered pages.
async function quotesOn(page, route) {
  await page.goto(`${HOST}${route}`);
  return page.$$eval('figure blockquote', (nodes) =>
    nodes.map((n) => n.textContent.replace(/\s+/g, ' ').trim())
  );
}

test.describe('the pull quotes', () => {
  test('/about/ and /donate/ render the same list', async ({ page }) => {
    const about = await quotesOn(page, '/about/');
    const donate = await quotesOn(page, '/donate/');

    expect(about.length).toBeGreaterThan(1);
    expect(donate).toEqual(about);
  });

  test('every quote is attributed with a link', async ({ page }) => {
    await page.goto(`${HOST}/about/`);
    const figures = page.locator('figure:has(blockquote)');
    const count = await figures.count();
    expect(count).toBeGreaterThan(1);

    for (let i = 0; i < count; i++) {
      const link = figures.nth(i).locator('figcaption a');
      await expect(link).toHaveAttribute('href', /^https?:\/\//);
      expect((await link.textContent()).trim()).not.toBe('');
    }
  });
});
