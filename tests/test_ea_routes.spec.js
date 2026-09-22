const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const HOST = process.env.HOST || 'http://localhost:4000';
const SECTION = path.join(__dirname, '..', 'ea-explorer');

/* The section moved to extensionless URLs: /ea-explorer/tour, /words/,
   /network/. Both moved pages set a `permalink`, so their assets had to become
   root-absolute — a directory URL resolves `data/…` one level deeper than a
   `.html` URL did. */

const ROUTES = ['/ea-explorer/', '/ea-explorer/tour/', '/ea-explorer/words/', '/ea-explorer/network/'];

for (const route of ROUTES) {
  test(`${route} is served directly`, async ({ request }) => {
    const res = await request.get(HOST + route, { maxRedirects: 0 });
    expect(res.status(), `${route} is not a page`).toBe(200);
    // A marker, not a byte count: writing into the repo triggers a Jekyll
    // rebuild, and a length check reads a mid-rebuild response as a failure.
    expect(await res.text(), `${route} did not render the section`).toContain('EA Explorer');
  });
}

test('the old .html URLs still resolve', async ({ request }) => {
  for (const [from, to] of [
    ['/ea-explorer/network.html', '/ea-explorer/network/'],
    ['/ea-explorer/words/opener.html', '/ea-explorer/tour/'],
  ]) {
    const body = await (await request.get(HOST + from)).text();
    expect(body, `${from} does not point at ${to}`).toContain(to);
  }
});

/* A link left on the old path still "works" through the redirect, so nothing
   would fail — it just costs a round trip and rots quietly. */
test('no page in the section links to a .html URL inside it', () => {
  const offenders = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { walk(p); continue; }
      if (!/\.html$/.test(e.name)) continue;
      const src = fs.readFileSync(p, 'utf8');
      for (const m of src.matchAll(/href="([^"]*(?:network|opener|words\/index)\.html[^"]*)"/g)) {
        offenders.push(`${path.relative(SECTION, p)} -> ${m[1]}`);
      }
    }
  })(SECTION);
  expect(offenders, `stale links:\n  ${offenders.join('\n  ')}`).toEqual([]);
});
