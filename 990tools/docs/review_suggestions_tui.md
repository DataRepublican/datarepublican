# review_suggestions_tui.py (heavily hardened)

**What:** The interactive TUI for reviewing Splink suggestions: global dedup, near-dupe review, modify/absorb, pre-bless from priority canonicals, export of approved patterns.

**Major 2026-05 improvements (the "inspect" half of the success):**
- Switched from sort-adjacent-only dedup to global normalized-key grouping + best-representative pick + lightweight pairwise.
- `clean_proposed_pattern` now forces UPPER early + does smart stripping of leading THE/A/AN, trailing geo, singular/plural normalization.
- "M" (modify) now triggers immediate absorption of remaining queue items + full safety rescan against the session's normalized set ("Also absorbed N").
- Pre-bless filter runs after dedup/near-dupe for maximum effect.
- Better handling of the persistent "<name> vs THE <name>" class of duplicates.

**Why:** Previous adjacent-only logic + weak normalization let many obvious duplicates through. Modify operations didn't trigger re-testing against the rest of the queue. These changes made the TUI dramatically more effective at the exact moment we started feeding it high-quality category-bucket suggestions.

**Related tools:** `splink_pattern_miner.py` (especially new blocking strategies), `category_splitter.py`, `church_major_resolver.py`, `extract_pharma_no_eins.py`.

This work was done under the Ringmaster process defined in `coding-bootstrap.md` (Obsidian). See RECENTGOALS.md for the success checkpoint context.
