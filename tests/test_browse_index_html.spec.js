const { test, expect } = require('@playwright/test');

// This was test.fixme until the v2 chrome landed. browse/index.html declared
// `layout: nofooter`, a layout that had never existed, so Jekyll rendered the
// page with no layout at all and production shipped it with no <head>, no
// <title>, no nav and no SEO tags. _layouts/nofooter.html now exists.
test('browse_index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/browse/index.html`);
  expect(response.status()).toBe(200);
  await expect(page).toHaveTitle('Charity explorer - Sankey chart of NGOs and their flows | DataRepublican');
});
