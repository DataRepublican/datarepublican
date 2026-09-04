# Name Rules Creation for the IRS 990 Grant Matching Pipeline

## Purpose and Context in the 990 Tool

This document explains how to generate and maintain name canonicalization rules for the IRS 990 grant processing pipeline. The rules are produced by a dedicated generator and then consumed by the match step (primarily `address_matcher.py`) to maximize the number of grants that receive a `recipient_ein_backfilled` value.

Many grants originate from private foundations that file Form 990-PF. These forms require only the recipient name and address; an EIN is not mandatory. Without normalization, variant spellings, abbreviations, and punctuation prevent reliable matching to authoritative EINs from the BMF and Charities tables. The canonicalization rules solve this by mapping hundreds of thousands of raw name variants to a smaller set of canonical forms. When a grant's normalized name matches a canonical that already carries a known EIN, the backfill succeeds. This dramatically increases EIN coverage for downstream analytics, rollups, fraud detection, and visualizations in DuckDB.

The pipeline also includes special handling for pharmaceutical patient assistance programs (often called "BIG PHARMA SUBSIDY" rows). These represent tax-advantaged subsidy flows after the ~$1B first-pill R&D cost and use a synthetic EIN (`99-7777777`) rather than a real charity EIN. See the dedicated context document for the full economic rationale and pattern list: [pharma_subsidy.md](pharma_subsidy.md).

## Overall Pipeline Flow

1. **Source TSV Generation** (executed against `/Volumes/Data/final/irs990.duckdb.hermesex` or equivalent)
   - `distinct_grantee_names.tsv` (2.2M unique names with grant counts and total dollars, ordered by volume for high-value focus)
   - `bmf_analysis.tsv` (EIN + official filer_name + city/state + totals from BMF join)
   - `ein_name_variants.tsv` (authoritative charity names grouped by EIN and ordered by dollars)

   Example SQL (adapt paths as needed):
   ```sql
   COPY (
     SELECT 
       recipient_name as grantee_name,
       count(*) as grant_count,
       sum(amount) as total_dollars
     FROM grants 
     WHERE recipient_name IS NOT NULL
     GROUP BY recipient_name
     ORDER BY total_dollars DESC
   ) TO 'distinct_grantee_names.tsv' (DELIMITER '\t', HEADER);

   -- Similar COPY statements for bmf_analysis.tsv and ein_name_variants.tsv
   ```

2. **Rule Generation**
   - Edit `name_rule_constants.py` first (add to `SIMPLES`, `GOOD_SINGLE_WORD_PRIORITIES`, `PROBLEM_SUFFIXES`).
   - Clear cache for a full run: `rm -f rules_without_ein_cache.json name_rules_v19.json.gz`
   - Run the generator in the background (full pipeline takes 10-60+ minutes):  
     `.venv/bin/python generate_name_rules_v19.1.py`
   - Output: `name_rules_v19.json.gz` (a dictionary keyed by canonical name with lists of variants).

3. **Validation and Diagnostics**
   - Run the v2 analyzer:  
     `PYTHONPATH=. .venv/bin/python /path/to/analyze_name_space_v2.py --rules name_rules_v19.json.gz --top 30`
     (produces console table + `uncovered_high_value_detailed.tsv` with raw/cleaned/best_canonical/similarity/EIN/reason).
   - Run reverse coverage check:  
     `.venv/bin/python reverse_coverage.py --threshold 0.4`
     (should report "No significant bad variants detected").
   - These steps surface high-value names still uncovered so constants can be refined before the next generator run.

4. **Application in the Match Step** (`address_matcher.py`)
   - The generated rules are loaded lazily via `AddressMatcher._load_rules()` (supports both `.gz` and plain JSON; auto-converts legacy list format to dict).
   - Rules drive two critical phases:
     - **Geo-aware normalization**: sets `grantee_name_geo` by replacing variant names with their canonical form (case-normalized, with small regex cleanups for "B&GC", "BSA", trailing commas, etc.).
     - **Full name + EIN consolidation**: builds `base_name_ein` (sharded by EIN prefix for memory safety), identifies the shortest authoritative name per EIN, applies suffix cleanup, creates a `name_mapping` table, and updates grants to set `grantee_name_conc` and `recipient_ein_backfilled`.
   - Additional address-based backfill (name + canonical_address match against BMF and Charity address tables) further increases coverage.
   - Final canonical name for any grant: `COALESCE(grantee_name_conc, grantee_name_geo, grantee_name_bmf, grantee_name)`.
   - After rules are applied, `grant_match_processor.py` runs for colocation, GIN fallback, and AuthoritativeEin table updates.

5. **Analytics and Visualization**
   - Pharma subsidy rows keep their synthetic EIN so dollar volume appears correctly without polluting real-charity graphs.
   - All downstream DuckDB queries and fraud-detection logic operate on the backfilled EINs.

## Operational Runbook (How to Run the Tools)

**Always commit before major changes:**
```bash
git add generate_name_rules_v19.1.py name_rule_constants.py big_pharma_subsidy.json name_rules_v19.json.gz
git commit -m "v19.3: ..."
```

**Generator (generate_name_rules_v19.1.py)**
1. Edit `name_rule_constants.py` first (add to `SIMPLES`, `GOOD_SINGLE_WORD_PRIORITIES`, `PROBLEM_SUFFIXES`).
2. Clear cache for full run: `rm -f rules_without_ein_cache.json name_rules_v19.json.gz`
3. Run in background (long running):  
   `.venv/bin/python generate_name_rules_v19.1.py`
   (use terminal with background=true and notify_on_complete=true in Hermes if available).
4. Output: `name_rules_v19.json.gz` (dict keyed by canonical with variants).

**v2 Analyzer**
```bash
cd /path/to/990tools
PYTHONPATH=. .venv/bin/python /path/to/analyze_name_space_v2.py --rules name_rules_v19.json.gz --top 30
```
Outputs: console table + `uncovered_high_value_detailed.tsv` (raw/cleaned/best_canonical/similarity/EIN/reason). Use this for "even better data" before adding rules.

**Reverse Coverage**
```bash
.venv/bin/python reverse_coverage.py --threshold 0.4
```
Checks for bad variants. Should say "No significant bad variants detected".

**Processors** (run after generator)
```bash
.venv/bin/python address_matcher.py && .venv/bin/python grant_match_processor.py
```
Use the hermesex DuckDB copy: `/Volumes/Data/final/irs990.duckdb.hermesex` (or your equivalent).

**Docs**
See `pipeline_overview.md` (source SQL and flow) and `pharma_subsidy.md` (synthetic EIN rationale) for additional context. Edit constants first, run greps + validation table before adding rules.

## Key Architecture Decisions and Trade-offs

- **Canonicalization before matching**: Performing heavy normalization once in the generator (rather than on every query) keeps the match step fast and deterministic.
- **Multi-layer name columns** (`grantee_name_bmf` → `grantee_name_geo` → `grantee_name_conc`): Allows progressive improvement while always preserving the original `grantee_name`. Trade-off: slightly more columns, but excellent auditability and rollback capability.
- **Lazy rule loading + gzipped storage**: Avoids loading 100k+ rules into memory unless the matcher actually runs. Gzip keeps the artifact small for git.
- **EIN-prefix sharding and batched commits**: Essential for processing millions of grants without OOM on machines with 16-32 GB RAM. Trade-off: more complex SQL, but reliable on real datasets.
- **Early pharma siding in generator STAGE 1**: High-volume patient-assistance names are removed from the expensive fuzzy/dedup loop and aggregated under one synthetic canonical. This is cleaner than post-hoc filtering.
- **Synthetic EIN for pharma subsidies**: Preserves $1B+ first-pill cost recovery volume in visualizations and fraud models while guaranteeing no real EIN will ever be assigned to these rows.

## Decision Log

- Chose generator + constants-driven approach over pure ML/fuzzy matching because it gives full human control and reproducibility (critical for audit and IRS-related data).
- Versioned rules (v19.x) with cache-clear flag so full re-runs are explicit and safe.
- Reference to `pharma_subsidy.md` kept external so the main document stays focused on canonicalization mechanics while the economic justification remains in one authoritative place.
- All paths and commands made as portable as possible while retaining the concrete examples from the original operational notes.

This design produces clean, maintainable, and highly effective name rules that directly improve EIN coverage for 990-PF grants in the match step.