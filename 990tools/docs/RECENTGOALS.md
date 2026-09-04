# RECENTGOALS.md — 990tools

Active scratchpad (What / Why / How + hashes). Older detail lives in CHANGELOG.md.

---

## 2026-09-04: Sticky inspector + Zoom camera

**What:** Inspect opens a right drawer (kind, money, top-5 in/out, compact links). Graph click does not close it (Escape / ×). Click mode **Zoom** (and the card’s Zoom ±1 hop) is a camera: same `k`/`translate` as shift-drag box zoom. Leftover See more loads the next hosted band from the card (`$1M` wait scaled from this machine’s `$10M`). Graph surgery stays in click-mode, not the card. Map view later as a popup from the drawer (`openInspectorMap` stub).

**Why:** Overlay controls eat the Sankey. `$1M`/`All` are triggered from See more / inspect, not the top notches. Fitting every 1-hop neighbor (or `2×` column pitch) is the whole 3-column graph, so scale never moved.

**How:** Box is this node’s layout rect; height so the node is ~55% of the view; horizontal margin `min(pitch, 3×nodeH, 8×nodeW)`. `npm run test:browse` (42). Hash `8c18cf27`.

**Next:** Map view later. Overlay layout flyout still optional polish.

---

## 2026-09-03: $1M / All bands on grumpytechbro.com

**What:** `$10M` stays in the Vercel `docs/` deploy. `$1M` (~58 MB / 208 zips) and **All** (~363 MB / 823 zips) `baseFile` is `https://www.grumpytechbro.com/browse/tsv_chunks/{1m,all}/`. CORS `Access-Control-Allow-Origin: *` on that directory. Loader records last `$10M` unzip+IDB time and estimates deeper bands. Leftover “See more” offers the next *hosted* notch. Local zip trees stay untracked.

**Why:** GitHub/Vercel cannot ship All (~350 MB extra in every clone and deploy). Git LFS is for clones, not a CDN. Hugging Face as a free-account website origin is a TOS gray area (community reuse, not a private CDN) and the Hub just sold to Nvidia. DreamHost already rsyncs multi-GB `/fun/` trees.

**How:** `grumpytechbro.com/scripts/rsync-browse-bands.sh` (not `deploy.sh --delete`). After a deeper `export_browse_band.py`, rsync then bump `chunkCount` / `nodes` / `edges` / `zipBytes` in `browse/data_files.js`. Smoke: browser `fetch` of a `$1M` zip from `localhost:4000` (413 707 bytes) then `Loading $1M: 8/208 files`. `npm run test:browse` (40). Doc: `docs/export_browse_band.md`. Hash `58f0659f` (GTB `13e6689`).

**Next:** Re-export `$1M`/All when the DuckDB changes. All is still a 2.6M-node in-browser freeze risk.

---

## 2026-09-02: Biggest Pharma + Patient Subsidies sink

**What:** HIPAA / see-attach / patient-rollup grantee names fold into one **Patient Subsidies** node (`etc997777777`) at **export**, not in the browser. Preset **Biggest Pharma** is seven PAPs (Genentech, J&J, Sanofi, Boehringer, GSK, Pfizer, Otsuka) placing `~0~1` onto that shared edge. $10M chunks rebuilt (`dbVersion` `2026-09-03T05:52:46Z`): 4,777 filers, $194B into the sink. Client-side retarget was a miss (refresh restored the old URL seeds; JSON module import was fragile).

**Why:** Per-GIN “Individual Patient Programs” / leftover See More made a $95B graph with no sharing. Mapping belongs with `big_pharma_subsidy.json`, same as Python reports.

**How:** `export_browse_band.py` + `grant_suppress.is_suppressed_sql`; 9-digit EINs not remapped. `browse/big_pharma_subsidy.js` for identity tests. `python3 test_export_browse_band.py`; `npm run test:browse` (36). Doc: `docs/export_browse_band.md`. Hash `f9e5336e`.

**Next:** Refresh still restores URL seeds — use Replace + Biggest Pharma.

---

## 2026-09-03: Inspector, subtract mode, skip phonebook toggle

**What:** Inspector drops Guide Star / Charity Navigator; adds Google Maps (BMF mailing street). New **Subtract** mode (X / Shift). Focus on an already-desired node expands 3 up / 3 down instead of tunneling again. Modifiers in mode tooltips (⌘/Ctrl add, ⌥/Alt inspect, Shift subtract). Playwright `tests/browse_sankey.spec.js` (`--project=demo`) is a regression walk, not a demo camera — too fast / Gates clip starts by clearing the graph (white). **PR4 Trust-the-phone-book skipped:** ghosts stay dead-ends; a global collapse would merge the ~1/3 bad $100M guesses.

**Why:** Mode buttons should match the modifier set. Maps is mailing-of-record, not a physical site. Collapse without votes is dishonest.

**How:** BMF `street/city/state/zip` on $10M export (`dbVersion` `2026-09-03T17:26:39Z`). `npm run test:browse` (40). Hash `d1301a4c`.

**Next:** Map view (Leaflet) as an inspector popup, not a Sankey overlay.

---
