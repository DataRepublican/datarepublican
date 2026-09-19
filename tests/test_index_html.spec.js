const { test, expect } = require('@playwright/test');

test('index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/index.html`);
  expect(response.status()).toBe(200);
  await page.waitForFunction('document.title !== ""');
  // The tagline, the home page's <title>/og:title and the social card all
  // paint the same line. `_config.yml` sets it; this is the curly apostrophe.
  await expect(page).toHaveTitle('Exposing what you’re not supposed to know | DataRepublican');
  // Add more assertions here
});