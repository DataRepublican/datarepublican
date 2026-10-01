const { test, expect } = require('@playwright/test');

test('florida_index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/florida/index.html`);
  expect(response.status()).toBe(200);
  await page.waitForFunction('document.title !== ""');
  await expect(page).toHaveTitle('Florida 2026 general election map | DataRepublican');
  // Add more assertions here
});