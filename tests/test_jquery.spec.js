const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

// jQuery was vendored 17 times across the repo and every layouted page loaded
// it twice — once from _includes/head-custom.html and once from the page's own
// copy, with the second silently clobbering the first. The shared copy was
// 3.2.1, the version affected by CVE-2020-11022 and CVE-2020-11023.
//
// Layouted pages now take the shared 3.5.1 and load nothing of their own. The
// unlayouted orphan pages (clark, convex, milwaukee, montgomery, pa,
// philadelphia, wisconsin, wordle) keep theirs, because they have no layout to
// get it from — convex in particular relies on the pre-3.5 htmlPrefilter
// behaviour that expanded `$('<circle … />')`.

const LAYOUTED = [
  '/award_search/', '/browse/', '/expose/', '/graphviz/', '/ned/',
  '/northcarolina/', '/officers/', '/officers/bulk/', '/nonprofit/',
  '/nonprofit/assets/', '/pennsylvania/', '/florida/',
];

test.describe('jQuery is loaded once, from one place', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const path of LAYOUTED) {
    test(`${path} loads exactly one jQuery`, async ({ page }) => {
      const loads = [];
      page.on('request', (r) => {
        if (/jquery[^/]*\.js/i.test(r.url())) loads.push(r.url().replace(/^https?:\/\/[^/]+/, ''));
      });

      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2000);

      expect(loads, `jQuery loaded ${loads.length} times: ${loads.join(', ')}`).toHaveLength(1);

      // And it is the patched one.
      const version = await page.evaluate(
        () => (window.jQuery && window.jQuery.fn && window.jQuery.fn.jquery) || null
      );
      expect(version).not.toBeNull();
      const [major, minor] = version.split('.').map(Number);
      expect(
        major > 3 || (major === 3 && minor >= 5),
        `jQuery ${version} predates 3.5 — CVE-2020-11022 / CVE-2020-11023`
      ).toBe(true);
    });
  }

  test('no page pulls jQuery from a third-party CDN', async ({ page }) => {
    const external = [];
    page.on('request', (r) => {
      const u = r.url();
      if (/jquery/i.test(u) && !u.startsWith(HOST)) external.push(u);
    });

    for (const path of ['/nonprofit/', '/nonprofit/assets/']) {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1500);
    }
    expect(external, `third-party jQuery: ${external.join(', ')}`).toEqual([]);
  });
});
