# church_major_resolver.py

**What:** Repeatable script (modeled exactly on `university_ein_resolver.py`) that extracts and canonicalizes major church-related names from the clean distinct names TSV. It produces `major_churches.json` in the same shape as `university_ein_mapping.json` so it can be consumed by the same downstream tools (TUI pre-bless, rule generators, etc.).

**Why:** Hundreds of "XXX CHURCH" variants exist in the grant data. Treating "CHURCH" as generic noise is insufficient for the large, high-dollar church networks and denominations (Catholic Charities clusters, etc.). We wanted a curated, reproducible set of major players parallel to how universities were handled. Early runs produced too many raw canonicals until TUI-style normalization (`_normalize_for_dedup` + `clean_proposed_pattern`) was ported in for name-only aggregation.

**How:**
- Loads the 3-column clean TSV.
- Filters for church-like names.
- Uses the normalization functions from the TUI (with fallback minimal versions for standalone repeatability).
- Applies `--min-grants` / `--min-dollars` thresholds.
- Outputs JSON suitable for priority_canonicals / pre-bless.
- Emits intermediate `church_lines.tsv` for inspection.

**Usage:**
```bash
python church_major_resolver.py \
    --input distinct_grantee_names_clean.tsv \
    --output major_churches.json \
    --min-grants 5 --min-dollars 50000
```

After running, manually curate the output down to the truly major players before committing.

**Related:** `category_splitter.py` (the preferred ongoing path for buckets), `university_ein_resolver.py`, `review_suggestions_tui.py` (normalization source).

**Hygiene note:** Part of the 2026-05 category success arc. Created to support targeted Splink on churches. See RECENTGOALS.md and coding-bootstrap.md (Ringmaster prompt) for the surrounding process and docs discipline.
