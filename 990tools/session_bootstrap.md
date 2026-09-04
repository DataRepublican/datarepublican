# 990tools Session Bootstrap

**Last updated:** 2026-07-02 (geolocate v9 on Data2)

> **Note:** For the current phase, prefer `issue_bootstrap.md` — authoritative for pipeline work. This file retains the 2026-05 category/Splink context.

## Current Focus (July 2026)
**`geolocate_new` v9 running** on `/Volumes/Data2/final/irs990.duckdb` — hard-tail serial grind. Monitor via `geolocate_monitor.sh`. After drain: `geolocate_grok` → `geolocate_archive` → `grant_match`. See `issue_bootstrap.md` and `docs/RECENTGOALS.md` (top entry).

## Previous Focus (May 2026)
We were doing targeted Splink discovery on coherent name categories instead of one giant run on the full master list. This is the "hybrid of a hybrid" approach.

Major recent work:
- Created `category_splitter.py` + supporting tools (church_major_resolver, extract_pharma_no_eins, etc.)
- Major hardening of `review_suggestions_tui.py` (global dedup, safety rescan on modify, early cleanup)
- Added `--blocking-strategy` to `splink_pattern_miner.py` (including the very useful "none" strategy for repetitive/redaction data)
- Education category expansion (May 2026)
- **Pharma bucket completion** (May 2026): Significantly hardened `big_pharma_subsidy.json` (compact regex patterns + strong anchors like "UPON REQUEST", "GRANTS? (PAID|APPROVED)"). Completed multiple Splink + TUI review cycles on high-value pure no-EIN pharma data. Added "STICHTING" to simple canonicals. Established bucket-isolated review workflow. User declared the pharma bucket complete.

## Current Category Buckets (as of latest run)
All live in `category_buckets/`:

- `churches.tsv` + `churches_seeds.json`
- `pharma.tsv` + `pharma_seeds.json`
- `school_districts.tsv` + `school_districts_seeds.json`
- `high_schools.tsv` + `high_schools_seeds.json`
- `universities.tsv` + `universities_seeds.json`
- `colleges.tsv` + `colleges_seeds.json`

**Important note:** There was a bug where `universities` and `colleges` were using the same detection function and produced identical output. This was fixed on 2026-05-25. The buckets were re-generated with proper separation (`is_university_name` vs `is_college_name`).

## Blocking Strategy Recommendations (as of 2026-05-25 tests)
Based on quick sampled runs:

- **universities**: `none` — excellent (clean metric=1.0 clusters on systems/associations). User was correct.
- **high_schools**: `none` — worked very well on the big religious/private schools.
- **pharma**: `none` (or `redaction`) — known strong performer.
- **colleges**: `sig_name` (default) — reasonable.
- **churches**: `sig_name` (default) — solid.
- **school_districts**: `sig_name` (default) — "none" and "loose" tend to surface "SCHOOL DISTRICT" itself as a high-metric suggestion too often. Default keeps things more reviewable.

There is now a `quick_tuned.sh` that bakes in these per-bucket strategies.

## How to Review Suggestions
Typical command (adjust as needed):

```bash
python review_suggestions_tui.py \
    --suggestions suggestions_<bucket>.json \
    --priority-canonicals category_buckets/<bucket>_seeds.json \
    --clean-names-tsv distinct_grantee_names_clean.tsv
```

The TUI now has much better global deduplication and modify safety.

## Launching Miners
Use `quick_tuned.sh` (rewritten in zsh 2026-05-25) to kick off miners for all current buckets with per-bucket blocking strategies. It runs everything in the background so you can disconnect:

```zsh
./quick_tuned.sh
```

Then you can safely exit. Monitor with:
```bash
tail -f miner_*.log
```

## Important Files & Locations
- `docs/RECENTGOALS.md` — living scratchpad (read this first on new sessions)
- `docs/education_name_patterns.md` — detailed notes on the education category work and naming patterns
- `docs/pipeline_overview.md` — explains full vs clean TSV, EIN availability, etc.
- Obsidian (primary long-term memory):
  - `coding-bootstrap.md` (the current Ringmaster system prompt)
  - The four Core Values notes
  - `Documentation and Commit Hygiene.md`

## Hygiene Reminders (Ringmaster Process)
- Every time we do real work on a .py, we should have corresponding docs.
- Commit at logical success points with good What/Why/How messages.
- RECENTGOALS.md should reflect current state.

## Next Logical Steps (as of 2026-05-25 evening)
1. Miners running on the six buckets via quick.sh.
2. Review the resulting `suggestions_*.json` files with the TUI (using the matching seeds).
3. Curate high-quality seeds from the reviews.
4. Feed those seeds back into the main name rule generation pipeline.

---

Read this + `docs/RECENTGOALS.md` when you come back to the project. The Obsidian `coding-bootstrap.md` is the ultimate source of truth for how we want to work.