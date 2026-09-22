const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const HOST = process.env.HOST || 'http://localhost:4000';

// A regex, not a YAML parser: the repo has no YAML dependency. `- href:` at
// the start of a line is the shape of every entry.
const TOOL_COUNT = (
  fs.readFileSync(path.join(__dirname, '..', '_data', 'tools.yml'), 'utf8')
    .match(/^- href:/gm) || []
).length;

// The home page is the tools index. These guard the two things most likely to
// break silently: a typo'd href in _data/tools.yml, which renders a perfectly
// good card pointing at a 404, and the CSS-order sorting, which has no visible
// failure mode — it just quietly stops rearranging.

test('every tool in the registry resolves', async ({ page, request }) => {
  await page.goto(HOST + '/');
  const hrefs = await page.locator('#tool-list > li a[href]').evaluateAll((els) =>
    els.map((e) => new URL(e.getAttribute('href'), location.origin).pathname)
  );

  expect(TOOL_COUNT, 'no tools parsed out of _data/tools.yml').toBeGreaterThan(5);
  expect(hrefs.length, 'a tool in the registry is not rendering a card').toBe(TOOL_COUNT);

  const broken = [];
  for (const href of hrefs) {
    const res = await request.get(HOST + href);
    if (res.status() !== 200) broken.push(`${href} -> ${res.status()}`);
  }
  expect(broken, `broken tool links: ${broken.join(', ')}`).toEqual([]);
});

test('each sort mode reorders the cards', async ({ page }) => {
  await page.goto(HOST + '/');

  // Visual order, not DOM order — the whole mechanism is CSS `order`, so
  // reading the DOM would pass no matter what the stylesheet did.
  const visualOrder = () =>
    page.evaluate(() =>
      [...document.querySelectorAll('#tool-list > li')]
        .filter((li) => li.offsetParent !== null)
        .map((li) => ({ li, r: li.getBoundingClientRect() }))
        .sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left)
        .map((o) => (o.li.querySelector('h3')?.textContent || '').trim())
    );

  await page.selectOption('#tool-sort', 'alpha');
  const alpha = await visualOrder();
  expect(alpha).toEqual([...alpha].sort((a, b) => a.localeCompare(b)));

  await page.selectOption('#tool-sort', 'latest');
  const latest = await visualOrder();
  expect(latest[0]).not.toBe(alpha[0]);
  expect(latest).toHaveLength(TOOL_COUNT);

  await page.selectOption('#tool-sort', 'featured');
  expect(await visualOrder()).toHaveLength(TOOL_COUNT);
});

test('category headers appear only in category mode', async ({ page }) => {
  await page.goto(HOST + '/');
  const headers = page.locator('#tool-list > li.tool-group-header');

  await expect(headers.first()).toBeHidden();

  await page.selectOption('#tool-sort', 'category');
  await expect(headers.first()).toBeVisible();
  expect(await headers.count()).toBeGreaterThan(1);

  // Every card must fall under a heading, so the first item in category mode
  // is a heading rather than a card.
  const first = await page.evaluate(() =>
    [...document.querySelectorAll('#tool-list > li')]
      .filter((li) => li.offsetParent !== null)
      .map((li) => ({ li, r: li.getBoundingClientRect() }))
      .sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left)[0]
      .li.className
  );
  expect(first).toContain('tool-group-header');
});
