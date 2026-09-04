# splink_pattern_miner.py (updated)

**What:** The core Splink-based pattern discovery tool. Given a (clean) names TSV, runs blocking + clustering and produces ranked suggestion JSON for human review in the TUI.

**Recent major updates (2026-05 success arc):**
- Added `--blocking-strategy` selector: `sig_name` (default, first_two_sig_words), `redaction`, `loose`, `none` (pure length bucketing, no semantic blocking).
- Introduced `redaction_sig` column for better redaction handling.
- "none" strategy proved extremely powerful for clustering pure redaction boilerplate variants ("SEE ATTACHED", "ATTACHMENT", "STATEMENT", etc.) to metric=1.0 clusters.
- Better integration with `--use-clean-tsv` path and category buckets.

**Why the changes:** Original sig_name blocking fragmented near-identical redacted rows. The new flexibility (especially "none") unlocked the exact clusters the user expected on pharma no-EIN redactions.

**Related:** `review_suggestions_tui.py`, `category_splitter.py`, `extract_pharma_no_eins.py`.

See RECENTGOALS.md and the Ringmaster bootstrap prompt for the surrounding hygiene and role-switching process.
