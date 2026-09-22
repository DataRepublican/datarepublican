/* Split noblogs/data.json into what the page needs to render and what it only
 * needs once you open a blog.
 *
 * The pipeline keeps producing data.json unchanged. This runs at build time, so
 * there is nothing for the pipeline to do differently and no chunking contract
 * for it to honour. If the shape of data.json changes, this adapts here.
 *
 *   noblogs/data.json          16.8 MB   what the pipeline drops in
 *   -> noblogs/data.index.json           everything the page needs to paint
 *   -> noblogs/data.detail.json          the rest, prefetched after first paint
 *
 * WHAT CAN BE DEFERRED, AND WHY IT IS ONLY THESE FIELDS
 *
 * Most of the heavy data turns out to be load-bearing before anything is
 * clicked, which is not obvious from reading the field names:
 *
 *   q   (quotes, 21%)  feeds buildSearchIndex — searching quote text is a
 *                      documented feature, so deferring it would mean search
 *                      quietly missing matches until the second payload landed
 *   au  (authors)      also feeds buildSearchIndex, and buildAuthorMap
 *   ct  (contacts)     feeds the "w/ contact" KPI and the contact facet, via
 *                      Object.keys(b.ct).length — which throws if it is absent
 *   sum (summaries)    drawn on every card
 *
 * And rankBlogs() computes the grid's entire sort order from ri, nq, ct, dxn,
 * ro and ne. Deferring any of those would reorder every card on the page until
 * the second payload arrived. So this precomputes that score at build time and
 * the page uses it, which is what makes ne/ro/ri deferrable at all.
 *
 * That leaves `ne` (news, 37% of the file) as the one big win, plus a few small
 * drawer-only fields.
 */
import { readFileSync, writeFileSync, statSync } from 'node:fs';

const SRC = 'noblogs/data.json';
const INDEX = 'noblogs/data.index.json';
const DETAIL = 'noblogs/data.detail.json';

// Shown only inside the detail drawer. Everything else stays in the index.
const DEFER = ['ne', 'ro', 'ri', 'inst', 'na'];

const mb = (n) => (n / 1048576).toFixed(2);
// Copied from noblogs/index.html, NOT reimplemented. `ct` is
// {group: {channel: …}} and this counts distinct channels across all groups —
// not the number of groups. Using Object.keys(ct).length instead changed the
// impact score for 553 blogs and silently reshuffled the grid; the fidelity
// spec caught it. If ctCount changes there, change it here.
const ctCount = (ct) => {
  const s = new Set();
  for (const g of Object.values(ct || {})) for (const ch of Object.keys(g)) s.add(ch);
  return s.size;
};

// Byte-for-byte the same arithmetic as rankBlogs()'s imp() in noblogs/index.html.
// If that changes, this has to change with it — the spec asserts the ordering
// matches, so a drift fails the build rather than silently reshuffling the grid.
function impact(b) {
  const ri = (b.ri || []).reduce((s, x) => s + (x[1] || 1), 0);
  return ri * 2
    + (b.nq || 0)
    + ctCount(b.ct)
    + (b.dxn || 0) * 3
    + (b.ro || []).length
    + ((b.ne || []).length ? 1 : 0);
}

const raw = readFileSync(SRC, 'utf8');
const src = JSON.parse(raw);
const blogs = src.blogs;
if (!Array.isArray(blogs) || !blogs.length) throw new Error(`${SRC}: no blogs array`);

const indexBlogs = [];
const detail = {};

for (const b of blogs) {
  const keep = {};
  const put = {};
  for (const [k, v] of Object.entries(b)) {
    if (DEFER.includes(k)) put[k] = v;
    else keep[k] = v;
  }
  // Precomputed so the grid sorts identically without the deferred fields.
  keep.imp = impact(b);
  indexBlogs.push(keep);
  if (Object.keys(put).length) detail[b.h] = put;
}

/* ---- Redaction gate -------------------------------------------------------
 * Doxxing-flagged blogs must carry no outbound links. data.json arrives from
 * the pipeline already stripped, and this file is the first thing in this repo
 * to write those records out again, so it re-checks rather than assuming.
 *
 * The rule is about the LINK FIELD, not about URL-shaped text. A news entry is
 * [title, url, date], and some flagged blogs have a URL inside the *title*:
 *
 *   ["anti Peste Noire https://antipestenoire.noblogs.org/", "", "2016-04-23"]
 *
 * That is expected and safe — the url slot is empty, and index.html renders a
 * flagged blog's title as `<span>${esc(t)}</span>` rather than an anchor. An
 * earlier version of this gate scanned the whole record for a URL pattern and
 * failed on exactly that case. Auto-linking titles would republish these, which
 * is why the renderer must never do it.
 *
 * Baselines are pinned. If the pipeline ever starts emitting link fields for
 * flagged blogs, the build stops instead of quietly shipping them.
 */
const flagged = blogs.filter((b) => b.dox);
let flaggedNews = 0, flaggedNewsLinked = 0;
let flaggedQuotes = 0, flaggedQuotesLinked = 0;
const offenders = [];

for (const b of flagged) {
  for (const e of b.ne || []) {
    flaggedNews += 1;
    if (Array.isArray(e) && e[1]) { flaggedNewsLinked += 1; offenders.push(`${b.h} news`); }
  }
  for (const q of b.q || []) {
    flaggedQuotes += 1;
    const link = q && (q.u || q.url || q.src);
    if (link) { flaggedQuotesLinked += 1; offenders.push(`${b.h} quote`); }
  }
}

if (flaggedNewsLinked || flaggedQuotesLinked) {
  console.error('\nREDACTION FAILURE — doxxing-flagged blogs carry link fields:');
  for (const o of [...new Set(offenders)].slice(0, 10)) console.error('  ' + o);
  console.error('\nNothing written. Fix upstream in data.json, not here.');
  process.exit(1);
}

// Pinned baselines, from the shipped data.json.
const EXPECT = { flagged: 291, news: 1926, quotes: 515 };
const drift = [];
if (flagged.length !== EXPECT.flagged) drift.push(`flagged blogs ${flagged.length} (expected ${EXPECT.flagged})`);
if (flaggedNews !== EXPECT.news) drift.push(`flagged news entries ${flaggedNews} (expected ${EXPECT.news})`);
if (flaggedQuotes !== EXPECT.quotes) drift.push(`flagged quotes ${flaggedQuotes} (expected ${EXPECT.quotes})`);
if (drift.length) {
  console.warn('\n  note: redaction baselines moved — ' + drift.join('; '));
  console.warn('  Not a failure (the dataset grows), but confirm it is expected and update EXPECT.');
}

const indexOut = JSON.stringify({ generated: src.generated, n: src.n, blogs: indexBlogs });
const detailOut = JSON.stringify(detail);
writeFileSync(INDEX, indexOut);
writeFileSync(DETAIL, detailOut);

/* ---- Reconstruction check -------------------------------------------------
 * index + detail must be exactly data.json again. This is the guarantee that
 * matters when the pipeline drops in a new file: if it grows a field this
 * script has never seen, the field lands in the index untouched and this still
 * passes. If anything is lost or altered, the build stops.
 */
{
  const rebuiltIndex = JSON.parse(indexOut).blogs;
  const rebuiltDetail = JSON.parse(detailOut);
  const problems = [];
  for (let i = 0; i < blogs.length && problems.length < 5; i += 1) {
    const original = blogs[i];
    const { imp, ...rest } = rebuiltIndex[i];
    const merged = { ...rest, ...(rebuiltDetail[original.h] || {}) };
    // Same keys, same values, order-insensitive.
    const a = JSON.stringify(Object.fromEntries(Object.entries(original).sort()));
    const b = JSON.stringify(Object.fromEntries(Object.entries(merged).sort()));
    if (a !== b) problems.push(original.h);
  }
  if (problems.length) {
    console.error('\nRECONSTRUCTION FAILURE — index + detail does not equal data.json:');
    for (const h of problems) console.error('  ' + h);
    process.exit(1);
  }
}

const srcSize = statSync(SRC).size;
console.log(`noblogs data split — ${blogs.length.toLocaleString()} blogs`);
console.log(`  ${SRC.padEnd(26)} ${mb(srcSize).padStart(6)} MB`);
console.log(`  ${INDEX.padEnd(26)} ${mb(indexOut.length).padStart(6)} MB   painted immediately`);
console.log(`  ${DETAIL.padEnd(26)} ${mb(detailOut.length).padStart(6)} MB   prefetched after paint`);
console.log(`  deferred: ${DEFER.join(', ')}`);
console.log(`  redaction gate: ${flagged.length} flagged blogs, 0 links in deferred payload`);
