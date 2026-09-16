/* Capture tool preview images for the home page cards.
 *
 *   npm run build
 *   python3 -m http.server 4000 --directory _site &
 *   node scripts/capture-previews.mjs [name ...]
 *
 * With no arguments it captures every tool that has no image yet, which is the
 * usual case — the nine older previews were captured by hand and are kept.
 * Name one or more tools to re-shoot them.
 *
 * Two things make the difference between a useful thumbnail and a useless one:
 *
 *   query  a tool showing its empty state is not a preview of anything, so
 *          each entry loads a query that makes the tool show real output
 *   wait   a selector that only exists once the data has rendered, so the
 *          shot is never of a spinner or an empty canvas
 *   focus  the element to frame. Without this the shot is mostly the site
 *          banner, masthead and nav — the same on every card and a preview
 *          of nothing.
 *
 * The viewport is 1200x620, close to the card's ~2:1 image well, so the crop
 * does as little work as possible.
 */

import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(root, 'assets', 'images', 'products');
const BASE = process.env.HOST || 'http://localhost:4000';
const SIZE = { width: 1200, height: 620 };

const TOOLS = [
  {
    name: 'dsa-explorer',
    url: '/dsa-explorer/',
    // #cy is the Cytoscape canvas; it has no size until the graph is laid out.
    wait: '#cy canvas',
    // #stage, not #app — #app includes the detail panel, and the page's own
    // disclaimer strip is outside both. The previously shipped preview was a
    // whole-page grab and carried that strip into the card.
    focus: '#stage',
    // The controls, search pill and legend are absolutely positioned over the
    // canvas and take up most of it at this size. A card wants the graph.
    hide: ['#controls', '#legend', '#search', '#panelToggle'],
    settle: 6000,
  },
  {
    name: 'noblogs',
    // The standalone map rather than /noblogs/?view=map. On the tabbed page the
    // map is an iframe, and an element screenshot of its container came back
    // with the parent's tab bar and disclaimer in it. world_hyperlocal_map.html
    // is a shipped route that is nothing but the map, so the viewport is the
    // shot and there is no frame to reach into.
    url: '/noblogs/world_hyperlocal_map.html',
    wait: '.leaflet-marker-icon, .marker-cluster',
    // Standalone, so it shows its own disclaimer bar; embedded in /noblogs it
    // hides it because the parent header already carries one.
    hide: ['#disclaimerBar'],
    settle: 9000,
  },
  {
    name: 'ned',
    url: '/ned/?keywords=democracy',
    // #resultsContainer is in the markup from the start and is filled in once
    // the index has been fetched and searched, so wait for a child rather than
    // for the container itself.
    wait: '#resultsContainer > *',
    focus: '#resultsContainer',
  },
  {
    name: 'florida',
    url: '/florida/',
    // The county map is an inline SVG whose paths get fills applied from data.
    wait: '#mapbase svg path[fill]:not([fill="none"])',
    focus: '#mapwrapper',
  },
  {
    name: 'pennsylvania',
    url: '/pennsylvania/',
    wait: '#mapbase svg path[fill]:not([fill="none"])',
    focus: '#mapwrapper',
  },
  {
    name: 'northcarolina',
    url: '/northcarolina/',
    wait: '#mapbase svg path[fill]:not([fill="none"])',
    focus: '#mapwrapper',
  },
];

const only = process.argv.slice(2);
const targets = only.length ? TOOLS.filter((t) => only.includes(t.name)) : TOOLS;

if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
let failed = 0;

for (const tool of targets) {
  const out = join(OUT, `${tool.name}.png`);
  if (!only.length && existsSync(out)) {
    console.log(`skip  ${tool.name} — already exists`);
    continue;
  }

  const page = await browser.newPage({ viewport: SIZE, deviceScaleFactor: 2 });
  const problems = [];
  page.on('pageerror', (e) => problems.push(`JS: ${e.message}`));
  page.on('response', (r) => {
    if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`);
  });

  try {
    await page.goto(BASE + tool.url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector(tool.wait, { timeout: 45000 });
    // Let the last paint settle — map fills, graph layouts and chart
    // transitions all land after the element the wait selector matched.
    await page.waitForTimeout(tool.settle ?? 1200);

    if (tool.hide) {
      await page.evaluate((selectors) => {
        for (const sel of selectors) {
          for (const el of document.querySelectorAll(sel)) {
            el.style.visibility = 'hidden';
          }
        }
      }, tool.hide);
    }

    if (tool.focus) {
      // Cap the element's height before shooting it, rather than clipping the
      // page afterwards. Framing an element alone can run to whatever height
      // its content happens to be — /ned's results list came out 1968x18922,
      // which is a strip, not a thumbnail — and a page-level clip picks the
      // wrong region for an element far down a scrolling page.
      await page.evaluate(
        ([sel, max]) => {
          const el = document.querySelector(sel);
          if (el && el.getBoundingClientRect().height > max) {
            el.style.maxHeight = max + 'px';
            el.style.overflow = 'hidden';
          }
        },
        [tool.focus, SIZE.height]
      );
      await page.locator(tool.focus).first().screenshot({ path: out });
    } else {
      await page.screenshot({ path: out });
    }
    console.log(`ok    ${tool.name} -> ${out}${problems.length ? `  (${problems.length} console problems)` : ''}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL  ${tool.name}: ${error.message.split('\n')[0]}`);
    if (problems.length) console.error(`      ${problems.slice(0, 3).join('\n      ')}`);
  } finally {
    await page.close();
  }
}

await browser.close();
process.exit(failed ? 1 : 0);
