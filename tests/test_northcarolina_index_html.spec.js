const { test, expect } = require('@playwright/test');

test('northcarolina_index_html loads correctly', async ({ page }) => {
  const response = await page.goto(`${process.env.HOST || 'http://localhost:4000'}/northcarolina/index.html`);
  expect(response.status()).toBe(200);
  await page.waitForFunction('document.title !== ""');
  await expect(page).toHaveTitle('North Carolina 2026 general election map | DataRepublican');
  // Add more assertions here
});