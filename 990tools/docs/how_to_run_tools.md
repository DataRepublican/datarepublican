# How to Run the Tools

## Generator (generate_name_rules_v19.1.py)
1. Edit name_rule_constants.py first (add to SIMPLES, GOOD_SINGLE_WORD_PRIORITIES, PROBLEM_SUFFIXES).
2. Clear cache for full run: rm -f rules_without_ein_cache.json name_rules_v19.json.gz
3. Run in background (long-running): 
   .venv/bin/python generate_name_rules_v19.1.py
   (use terminal(background=true, notify_on_complete=true) in Hermes)
4. Output: name_rules_v19.json.gz (dict keyed by canonical with variants).

WHY background: Full run takes 10-60+ min. Cache clear forces full pipeline (avoids "Restored session" short runs).

## v2 Analyzer
cd /Users/pierce/Development/datarepublican/990tools
PYTHONPATH=. .venv/bin/python /Users/pierce/.hermes/skills/irs-990-name-matching/scripts/analyze_name_space_v2.py --rules name_rules_v19.json.gz --top 30

Outputs: Console table + uncovered_high_value_detailed.tsv (raw/cleaned/best_canonical/similarity/EIN/reason).

Use this for "even better data" before adding rules.

## Reverse Coverage
.venv/bin/python reverse_coverage.py --threshold 0.4

Checks for bad variants. Should say "No significant bad variants detected".

## Main Pipeline (`irs990processor.py`)

Full step order:
```
irsfetch → zip → bmf → xml → fec → medicare → sanctions → dot → address → einless → match → geolocate_* → grant_match → backfill → photos → ratios → percentiles → export
```

Common invocations:
```bash
# Full pipeline
python -u irs990processor.py --db-path irs990.duckdb

# Single step (resilient to CLI crashes — use nohup)
nohup python -u irs990processor.py --step sanctions --nostats -v > sanctions_step.log 2>&1 &
nohup python -u irs990processor.py --step dot --nostats -v > dot_step.log 2>&1 &
nohup python -u irs990processor.py --step einless --nostats -v > einless_step.log 2>&1 &

# Production resume (June 2026): sanctions + dot complete on /Volumes/Data/final/irs990.duckdb
nohup python -u irs990processor.py --start-step address --nostats -v > address_step.log 2>&1 &

# Resume after einless milestone (earlier checkpoint)
python -u irs990processor.py --start-step match --db-path irs990.duckdb
```

The `einless` step exports TSV inputs from DuckDB, runs phonebook cream + DAF resolution, and sets `recipient_ein_backfilled` (raw `recipient_ein` untouched). See `docs/pipeline_overview.md`.

## Processors (also callable standalone)
- `einless_processor.py` — phonebook backfill (normally run via `--step einless`)
- `address_matcher.py` — name + address backfill (`--step match`)
- `grant_match_processor.py` — colocator, GIN fallback, AuthoritativeEin table

Use the hermesex DuckDB copy: /Volumes/Data/final/irs990.duckdb.hermesex

## Git
git add generate_name_rules_v19.1.py name_rule_constants.py big_pharma_subsidy.json name_rules_v19.json.gz
git commit -m "v19.3: ..."

Always commit before major changes.

## Docs
See pipeline_overview.md and pharma_subsidy.md for SQL, context, and architecture.

Edit constants first, run greps + validation table before adding rules (your strong preference).
