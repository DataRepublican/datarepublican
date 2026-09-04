# Overnight chunked Census (`overnight_census_chunked_run.sh`)

## Why

On a **16GB** Mac, a single `geolocate_census` process that feeds tens of thousands of pending rows tends to **OOM inside DuckDB** during consumer save (Geocoding / Addresses updates). Historically that:

1. Fired OOM handling via `sys.exit` in a **worker thread** (did not kill the process).
2. Left the pipeline **stuck** joining queues with `rows_saved=0`.
3. Made an outer “just restart” loop useless until someone killed PIDs by hand.

Chunked Census exists so each process does a **bounded** `--max-files` batch, **exits cleanly** (including hard-exit code **75** on DuckDB OOM), and the shell starts a **fresh** DuckDB connection for the next batch. Progress is durable because pending rows flip off `pending` as they match or go to `pending_api`.

## What it does

Loops until `Geocoding.geocoding_status = 'pending'` is **0** (or `CENSUS_MAX_ROUNDS`):

```bash
python3 -u irs990processor.py \
  --start-step geolocate_census --stop-step geolocate_census \
  --final-dir /Volumes/Data/final \
  --db-path /Volumes/Data/final/irs990.duckdb \
  --max-files "$CHUNK" --workers 2 --db-threads 1 --nostats -v
```

Writes status to `overnight_geolocate_status.txt` and a timestamped log under `logs/`.

## How to run

```bash
cd /path/to/990tools
# defaults: CHUNK=500, DUCKDB_MEMORY_LIMIT=12GB, skip owner colocators, skip post-step ANALYZE
nohup bash overnight_census_chunked_run.sh > /tmp/census_chunked_launch.out 2>&1 &
cat overnight_geolocate_status.txt
tail -f "$(grep '^log=' overnight_geolocate_status.txt | cut -d= -f2-)"
```

### Environment knobs

| Variable | Default | Why |
|----------|---------|-----|
| `CENSUS_CHUNK` | `500` | `--max-files` per process; larger → fewer rounds but more save pressure |
| `DUCKDB_MEMORY_LIMIT` | `12GB` | DuckDB allocator cap; 8GB filled mid-save on this DB |
| `GEOCODE_SKIP_OWNER_COLOCATORS` | `1` | Skip Charity/Officer/… colocator fan-out during census; Geocoding + Addresses still update |
| `GEOCODE_CENSUS_CONSUMER_BATCH` | `100` | Consumer flush size (PDC merge / save batching) |
| `SKIP_POST_STEP_OPTIMIZE` | `1` | Avoid full-table ANALYZE after every chunk |
| `CENSUS_MAX_ROUNDS` | `200` | Safety cap on loop iterations |

Also: any `--max-files` run skips post-step optimize in `irs990processor.py` even without the env flag.

## Failure modes (and what we chose)

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| DuckDB OOM in worker | Hang at shutdown; `rows_saved=0` | `os._exit(75)` from `_oom_hard_exit`; shell continues |
| 1-row `bulk_update` storm | OOM after ~50–100 UPDATEs | PDC merge consolidates; `UPDATE…FROM (VALUES…)` |
| Whole-tx rollback | Geocoding written then Addresses OOM undoes all | Intermediate commit after Geocoding / Addresses |
| ANALYZE after each chunk | Minutes of CPU for 500 rows of work | Skip optimize for max-files / env |
| Bare `CO` vs `C/O` | census_strip leaves care-of name on street | Word-boundary + street-cue strip in `geocoding_api_processor` |

## After success

- **`pending=0`** does **not** mean every address is geocoded: Census misses become **`pending_api`** (and similar). Export: `pending_api_failures_for_patterns.tsv.gz` under `--final-dir`.
- Next pipeline stages (when ready): paid/self-hosted Photon or `geolocate_api`, then colocator finalize / `geolocate_archive`, then `grant_match` → backfill.

## Related code

- `geolocate_census_processor.py` — step entry
- `geocoding_api_processor.py` — Census + strip + CO patterns + consumer pipeline
- `database_operations.py` / `pending_database_context.py` — OOM exit + bulk save path
