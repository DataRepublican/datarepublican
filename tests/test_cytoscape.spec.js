const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const HOST = process.env.HOST || 'http://localhost:4000';

// Cytoscape was vendored three times — noblogs/graph/, dsa-explorer/ and
// ea-explorer/ — byte-identical at 353 KB each. One copy now, beside the
// shared jQuery, and each consumer points at it.
//
// It is NOT in head-custom.html: four routes need it and 34 do not.

const CANONICAL = '/assets/js/cytoscape.min.js';

const CONSUMERS = [
  { path: '/noblogs/?view=graph', label: 'the noblogs graph tab' },
  { path: '/noblogs/graph/', label: 'the standalone graph page' },
  { path: '/dsa-explorer/', label: 'dsa-explorer' },
  { path: '/ea-explorer/network/', label: 'the EA network' },
];

test('only one cytoscape exists in the tree', () => {
  const found = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (/^(docs|node_modules|_site|\.git|test-results|playwright-report)$/.test(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/^cytoscape.*\.js$/.test(e.name)) found.push(p);
    }
  })(path.join(__dirname, '..'));

  expect(found.map((f) => f.split(path.sep).slice(-3).join('/')),
    'cytoscape is vendored more than once again').toHaveLength(1);
});

test.describe('every consumer loads the shared copy', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const { path: route, label } of CONSUMERS) {
    test(`${label} loads exactly one, from ${CANONICAL}`, async ({ page }) => {
      const loads = [];
      page.on('request', (r) => {
        if (/cytoscape[^/]*\.js/i.test(r.url())) {
          loads.push(r.url().replace(/^https?:\/\/[^/]+/, ''));
        }
      });

      await page.goto(HOST + route, { waitUntil: 'load' });
      // The noblogs graph tab loads it on demand rather than up front.
      await page.waitForFunction(() => typeof window.cytoscape === 'function', { timeout: 30000 });

      expect(loads, `loaded ${loads.length} times: ${loads.join(', ')}`).toEqual([CANONICAL]);
      // Rendered, not merely present: cytoscape paints into its own canvases.
      expect(await page.locator('#cy canvas').count()).toBeGreaterThan(0);
    });
  }
});
