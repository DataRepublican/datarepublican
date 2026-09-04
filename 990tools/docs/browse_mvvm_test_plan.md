# Browse MVVM test plan (do not implement yet)

**Why:** `/browse` is already documented as M–V–VM (`models.js` ~697). It is easy to break focus, ghosts, and URL state with a Sankey tweak. Playwright on the full page is too slow and too late. Unit tests belong on **M** and **VM**. The **V** (`script.js` D3) will stay painful; we only move VM-shaped code out of it.

**Do not:** rewrite the Sankey, add Trust-the-phone-book, or load $1M in this workstream.

---

## Layers as they actually are

| Layer | Lives in | Job | Today’s leaks |
|---|---|---|---|
| **M** | `Charity`, `Grant` | Graph identity, kinds (charity / ghost / bmf / leftover), grant amounts, desired/implied flags, place/expand/hide | Static global `charityLookup`; `viewModel` singleton; IDB/TSV loader in the same file |
| **VM** | `BrowseViewModel` | show/hide lists, URL (`e`/`n`/`k`), presets add vs replace, `tunnelNode` / implied visibility, `buildSankeyData` (nodes/links for V) | Writes `history.replaceState` inside `computeImpliedVisibility`; `updateStatus` DOM; zip fetch |
| **V** | `script.js` + HTML/CSS | D3 Sankey, hats, panel HTML, zoom/brush | `compareCharities` / node geometry / click wiring that *decides* behavior |

Comment in the VM is still right: visibility *policy* is VM; *propagation* ended up on Charity. Tests should pin the policy; we do not have to relocate every method on day one.

---

## Why we cannot `import models.js` in Node today

Top of `models.js` pulls CDN ESM (`idb`, `jszip`), `window.d3`, IndexedDB, and `fetch`. A test file that imports the module boots the loader.

**Prerequisite (small extract, still “plan” until you say go):** split before or as the first PR of this track:

1. `browse/graphIdentity.js` — `isGraphKey`, `Charity.kindFrom`, `formatNumber`, `scaleValue` (no DOM, no IDB).
2. `browse/graphModel.js` — `Charity` + `Grant` + registries, **inject** `{ viewModel }` instead of a module global (or a `createGraph()` that returns a fresh lookup).
3. `browse/viewModel.js` — `BrowseViewModel`; URL serialize/parse **pure** (`computeURLParams` / `parseQueryParams`) with `history` behind a tiny adapter.
4. `browse/dataLoader.js` — IDB + zip TSV (`fetchAndStoreTSV`). Untested except a fixture parse of one in-memory TSV string.
5. `browse/models.js` — re-export for the existing V import path so `script.js` does not churn in the same PR.

Vitest (or Node test + `vitest`) + a `resetGraph()` in `beforeEach` that clears `charityLookup` / grant lookup / showList. No jsdom required for M/VM if URL adapter is injectable.

Playwright stays **V smoke only** (page loads, one focus click). Do not grow `test_noking_browse.spec.js` as the unit suite.

---

## Fixture (one tiny graph, reuse everywhere)

Build in a helper, not from production zips:

| id | kind | notes |
|---|---|---|
| `001` | charity (gov) | USG |
| `911663695` | charity | Gates Trust (filer) |
| `562618866` | charity | Gates Foundation (990) |
| `70`+64 hex | ghost | “GATES FOUNDATION” PF name; `suggestedEin = 562618866` |
| `etc911663695` | leftover | see-more stub |
| `042103594` | bmf | MIT, no 990 card |

Edges: Trust → ghost ($42), Trust → leftover ($5), Trust → MIT BMF ($10). One inferred flag on the ghost edge.

---

## M tests (Charity / Grant)

Run with a fresh graph per test. No D3.

1. **Identity:** `isGraphKey` 9-digit / GIN 66 / GIN 130 / `etc`+9 / reject `SEE` and short junk.
2. **`kindFrom`:** xml/org_type `ghost` / `leftover` / `backfill`; GIN length; leftover prefix.
3. **Cards:** `has990Card` true only for real 990 charities; false for ghost, leftover, BMF, gov.
4. **`longEIN`:** hyphenated 9-digit; **empty** for ghost and leftover (never present a GIN as IRS EIN).
5. **`orgShort`:** the three copy strings (ghost / leftover / BMF).
6. **Grant wiring:** `Grant` constructor attaches filer/grantee; ghost picks up `suggestedEin` from the edge.
7. **Focus seeds:** `place(up, down)` marks desiredVisible and reveals that many grants.
8. **Expand:** `expandOutflows(3)` only flips currently invisible outflows, count 3.
9. **Hide:** `hide()` clears desiredVisible on the node (grants follow existing rules — assert current behavior, don’t invent new).
10. **No 990 links conceptually:** `propublica990Id` empty when `xml_name` is `ghost`/`backfill`/`leftover`.

These lock PR2 kinds so a later Trust-the-phone-book PR cannot “fix” a ghost by stuffing the GIN into `longEIN`.

---

## VM tests (BrowseViewModel)

Same fixture. Stub `history` / `updateStatus`.

1. **`tunnelNode` / `clickNode`:** after focus, `getShowList()` is exactly that org; other desired seeds are gone. (This is the spiderweb regression.)
2. **`loadPreset(..., "add")`:** union of eins on the show list.
3. **`loadPreset(..., "replace")`:** show list equals the preset only.
4. **URL round-trip:** `setShowList(["911663695~1~1"])` → `computeURLParams` → `parseQueryParams` recovers the same seed. Cover both `e=` and legacy `ein=`.
5. **Hide list:** hidden ein is not in `buildSankeyData().nodes`.
6. **Implied hop:** seed Trust with one visible outflow to the ghost; ghost is visible; Foundation 990 node is **not** unless seeded (trust-off honesty).
7. **Leftover edge:** leftover stub appears iff that grant is desired/implied; it is not a Charity card.
8. **`buildSankeyData`:** `nodes[].id` / `links` endpoints are graph keys; no GIN in a field the V would label “EIN” (the V reads `longEIN`).

Do **not** unit-test D3 path strings, zoom, or brush.

---

## What should move out of `script.js` (V must still suffer)

Keep in **V** (no unit tests, or Playwright only):

- `generateGraph`, `renderFocusedSankey`, zoom/brush, hat paths, `showControlPanel` HTML, `flashNode`, search typeahead DOM.

Move into **VM** (then unit-test):

| From `script.js` | Why it is VM |
|---|---|
| `compareCharities` / `compareLinks` | Sort policy for the graph, not pixels |
| Click policy already on `clickNode` | V should only `viewModel.clickNode` / `handleUpClick` — **already mostly true after PR2**; delete leftover `handleClick` dead code on Charity when tests exist |
| `updateQueryParams` | Duplicate of `computeAndSaveURLParams` — one URL owner |
| `window.focusNode` / `expandInflows` / … | Stay as 3-line V adapters; logic stays on Charity/VM |

Move into **M** only if we need it without a VM:

- Nothing from geometry (`calculateRegularPosition`, `sankeyLinkHorizontalTrapezoid`). That is V (or a `browse/layout.js` that tests can ignore).

Optional later: `browse/layout.js` for node height math if it keeps breaking; still not “the model.”

---

## PR slices (when implementing)

0. **Extract `graphIdentity.js` + vitest** — `isGraphKey` / `kindFrom` / `formatNumber`. Hours, not a rewrite.
1. **Injectable registries + fixture helper** — `resetGraph()`; M tests 1–10 on the Gates mini-graph.
2. **URL adapter + VM tests 1–8** — tunnel, presets, hide, implied hop.
3. **Move compare/sort + kill URL duplication** in `script.js`. Re-run M/VM tests; one Playwright: load `/browse/?e=911663695~1~1`, click a node, assert other seeds drop.

Each slice should be its own commit. Do not mix with PR3 ($1M load) or PR4 (trust toggle).

---

## Out of scope

- Testing `fetchAndStoreTSV` against live zips (too slow; one golden TSV string parse is enough).
- Visual regression of trapezoid vs octagon.
- Moving D3 into the VM.
- Rewriting Charity so visibility lives only on the VM (comment already says that’s the long-term idea; tests first, move later).
