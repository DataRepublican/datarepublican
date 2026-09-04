# category_splitter.py

**What:** Repeatable command-line tool that takes the master `distinct_grantee_names_clean.tsv` (or fuller variant) and splits it into category-specific buckets (currently `churches` via denomination keywords, `pharma` via patterns from `big_pharma_subsidy.json`). It also emits small `<category>_seeds.json` files for use as `--priority-canonicals` in the review TUI.

**Why:** The overall name-matching problem is too large for one monolithic Splink + review pass. Category bucketing enables a "hybrid of a hybrid" workflow: run targeted, high-signal Splink on coherent slices (churches are especially valuable because of large consistent networks; pharma no-EIN rows were previously filtered out of the clean TSV). The emitted seeds allow aggressive pre-blessing during TUI review of that bucket's suggestions, dramatically improving review throughput and seed quality for the main pipeline.

**How:**
- Loads the TSV with pandas.
- Applies simple but effective filters (`is_church_name` using `CHURCH` + `MAJOR_DENOMINATIONS`; `is_pharma_name` using the subsidy patterns).
- Optional `--min-grants` filter.
- Writes `<category>.tsv` (preserving original columns) and `<category>_seeds.json` (small curated canonical list for TUI).
- Prints ready-to-paste example commands for `splink_pattern_miner.py --use-clean-tsv` + `review_suggestions_tui.py --priority-canonicals`.

**Usage (typical success path):**
```bash
python category_splitter.py --categories churches,pharma
# Then:
python splink_pattern_miner.py --use-clean-tsv category_buckets/churches.tsv ...
python review_suggestions_tui.py --suggestions suggestions_churches.json --priority-canonicals category_buckets/churches_seeds.json ...
```

**Related:** `church_major_resolver.py`, `extract_pharma_no_eins.py`, `splink_pattern_miner.py`, `review_suggestions_tui.py`, `big_pharma_subsidy.json`.

**Hygiene note:** Created during the major 2026-05 category + TUI success arc. See RECENTGOALS.md and the Ringmaster coding-bootstrap prompt for context.
