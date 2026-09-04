# extract_pharma_no_eins.py

**What:** Takes the *full* (unfiltered) `distinct_grantee_names.tsv` and produces `pharma_no_eins.tsv` (and a 3-column variant) containing only rows that have no `recipient_ein` **and** match the big pharma subsidy/privacy patterns from `big_pharma_subsidy.json`.

**Why:** The clean TSV used for most Splink work had already dropped the real no-EIN subsidy rows. To run the desired Splink experiments on "SEE ATTACHED / STATEMENT / REDACTED" style redactions in the pharma space (to discover common structures), we needed a repeatable extractor from the raw master list. This produced the 5,475-row input that let us test --blocking-strategy none and other tactics.

**How:**
- Loads the full TSV with pandas.
- Filters for missing/empty `recipient_ein`.
- Matches against the same pharma patterns used elsewhere (normalized to upper).
- Writes both full-column and 3-column versions for miner compatibility.
- Standalone and repeatable (no dependency on the clean TSV).

**Usage (the exact request that triggered it):**
```bash
python extract_pharma_no_eins.py
# Then:
python splink_pattern_miner.py --use-clean-tsv pharma_no_eins.tsv \
    --blocking-strategy none --output suggestions_pharma_no_ein_redaction.json
```

**Related:** `category_splitter.py`, `big_pharma_subsidy.json`, `splink_pattern_miner.py` (especially the new blocking strategy work), `review_suggestions_tui.py`.

**Hygiene note:** Created during the 2026-05 "category and inspect" success arc to unblock Splink experimentation on no-EIN pharma redactions. See RECENTGOALS.md + the Ringmaster coding-bootstrap.md for process context.
