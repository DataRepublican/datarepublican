const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const SHARED = path.join(ROOT, 'assets', 'js', 'lib');
const SKIP = /^(docs|node_modules|_site|\.git|test-results|playwright-report|vendor)$/;

/* Two copies of one library is two things to patch, and the second is always
   the one nobody remembers. The shared copies are version-suffixed because two
   jszips and two papaparses are both in use. */

/* Per-tool config that is identical today and is allowed to diverge tomorrow:
   each county map owns its own pins and its own interactions. Sharing these
   would mean a change to one map silently changing three others. Only add a
   name here if the copies are project files, never a third-party library. */
const PROJECT_OWNED = new Set(['pins-config.js', 'map-interact.js']);

function walk(dir, match, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.test(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, match, out);
    else if (match.test(e.name)) out.push(p);
  }
  return out;
}

test('no library is vendored twice', () => {
  const byFile = new Map();
  for (const p of walk(ROOT, /\.js$/)) {
    if (PROJECT_OWNED.has(path.basename(p))) continue;
    const hash = crypto.createHash('md5').update(fs.readFileSync(p)).digest('hex');
    // Same bytes under the same NAME in two places is a duplicate. Same bytes
    // under different names is someone's deliberate copy, not this rule.
    const key = `${path.basename(p)}@${hash}`;
    if (!byFile.has(key)) byFile.set(key, []);
    byFile.get(key).push(path.relative(ROOT, p));
  }

  const dupes = [...byFile.values()]
    .filter((files) => files.length > 1)
    .map((files) => `${path.basename(files[0])} x${files.length}: ${files.join(', ')}`);

  expect(dupes, `duplicated:\n  ${dupes.join('\n  ')}`).toEqual([]);
});

test('every shared copy is actually referenced', () => {
  const shared = fs.readdirSync(SHARED);
  expect(shared.length, 'the shared vendor directory is empty').toBeGreaterThan(5);

  // Read the consuming files once, not once per library.
  const consumers = walk(ROOT, /\.(html|js)$/)
    .filter((p) => !p.startsWith(SHARED))
    .map((p) => fs.readFileSync(p, 'utf8'));

  const unreferenced = shared.filter(
    (f) => !consumers.some((src) => src.includes(`/assets/js/lib/${f}`))
  );

  expect(unreferenced, `nothing references: ${unreferenced.join(', ')}`).toEqual([]);
});
