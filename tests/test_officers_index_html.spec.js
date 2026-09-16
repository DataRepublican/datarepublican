const { test, expect } = require('@playwright/test');

// /officers with no query parameters runs a default search for "william
// kristol" and rewrites document.title when it resolves. Reaching that title
// means fetching officials_reverse_index.txt.zip (3.5 MB), unzipping it in the
// browser and running the search — about 0.9s locally, but well past
// toHaveTitle's 5s default on a CI runner. The wait is explicit so the spec
// says what it is waiting for and how long that is allowed to take.
test('officers_index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/officers/index.html`);
  expect(response.status()).toBe(200);
  await expect(page).toHaveTitle(
    'Search results for william kristol - Government NGO tracking',
    { timeout: 45000 }
  );
});
