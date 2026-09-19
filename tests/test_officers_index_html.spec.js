const { test, expect } = require('@playwright/test');

// /officers with no query parameters runs a default search for "william
// kristol" and rewrites document.title when it resolves. Reaching that title
// means fetching officials_reverse_index.txt.zip (3.5 MB), unzipping it in the
// browser and running the search — about 0.8s against a plain static server.
//
// The wait is explicit because the assertion depends on real network and CPU
// work rather than on render timing, and toHaveTitle's 5s default says nothing
// about either. It is not a workaround for a slow runner: when this failed in
// CI the cause was the test server, not the clock. `npx serve` rewrites
// /officers/index.html to /officers, so the page's relative script tags
// resolved against / and jquery/jszip/papaparse 404'd. No timeout would have
// fixed that. See the serve step in .github/workflows/ci.yml.
test('officers_index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/officers/index.html`);
  expect(response.status()).toBe(200);
  await expect(page).toHaveTitle(
    'Search results for william kristol - Government NGO tracking',
    { timeout: 30000 }
  );
});
