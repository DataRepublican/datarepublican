const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const SKIP = /^(docs|node_modules|_site|\.git|test-results|playwright-report|vendor)$/;

/* A file that exists on disk but is not in git passes every other spec in this
 * repo: the dev server reads the working tree, so the page is perfect locally
 * and 404s the moment it is deployed. `.gitignore` has a bare `vendor`, which
 * matches a directory of that name AT ANY DEPTH — `assets/js/vendor/` was
 * silently skipped by `git add -A` while the same commit deleted the per-tool
 * copies it replaced.
 *
 * It fails loudly on staging and silently in review: nginx's
 * `try_files $uri $uri/ /index.html` answers the missing script with the home
 * page, so the browser reports `Unexpected token '<'` rather than a 404.
 */

// `git ls-files` is ~10k lines here (docs/ alone is 10,011 files), which
// overruns execFileSync's 1 MB default and fails as ENOBUFS, not as an error
// about size.
function trackedFiles() {
  return new Set(
    execFileSync('git', ['ls-files'], {
      cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    }).split('\n')
  );
}

function everyHtml(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.test(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) everyHtml(p, out);
    else if (/\.html$/.test(e.name)) out.push(p);
  }
  return out;
}

test('every root-absolute asset the pages reference is committed', () => {
  const tracked = trackedFiles();

  const missing = new Set();
  for (const file of everyHtml(ROOT)) {
    const html = fs.readFileSync(file, 'utf8');
    for (const m of html.matchAll(/(?:src|href)="(\/assets\/[^"?#]+)"/g)) {
      const rel = m[1].slice(1);
      // Built artifacts are generated, not committed as sources.
      if (rel === 'assets/css/styles.css') continue;
      if (!tracked.has(rel)) missing.add(`${rel}  <- ${path.relative(ROOT, file)}`);
    }
  }

  expect([...missing], `referenced but not in git:\n  ${[...missing].join('\n  ')}`)
    .toEqual([]);
});

/* Same failure, one level down: a worker's importScripts is invisible to the
   regex above and to any grep for `<script src>`. */
test('every importScripts target is committed', () => {
  const tracked = trackedFiles();

  const missing = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.test(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { walk(p); continue; }
      if (!/\.js$/.test(e.name)) continue;
      const src = fs.readFileSync(p, 'utf8');
      for (const m of src.matchAll(/importScripts\(\s*['"](\/[^'"]+)['"]/g)) {
        if (!tracked.has(m[1].slice(1))) missing.push(`${m[1]}  <- ${path.relative(ROOT, p)}`);
      }
    }
  })(ROOT);

  expect(missing, `importScripts target not in git:\n  ${missing.join('\n  ')}`).toEqual([]);
});
