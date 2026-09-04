# upload_to_hf.py

**What:** Dump the live DuckDB to Parquet and publish `piercewetter3/irs-990-parsed`.

**Why:** The May 2026 Hub dump only had the 990 + FEC tables. The DB now also holds Medicare (NPPES + T-MSIS), DOT carriers, OFAC SDN, BMF-with-streets, and grant-match name tables. The old script hard-coded 18 tables and pointed at `irs990.duckdb.address`.

## What is published

Discovery walks `information_schema`. These stay local unless you `--include` them:

| Skip | Why |
|---|---|
| `medicare_raw_spending` | 238M-row CMS extract; `medicare_provider_spending` is the cleaned grain |
| `Zips_raw` | source for `Zips` |
| `fec_raw_committees` | ingest leftover |
| `PipelineProgress`, `PendingCanonicals`, `_meta_clustering`, `grant_update_map`, `temp_gin_batch` | ops / scratch |

Everything else goes up, including empty public tables (`Contributions`, `PoliticalContributions`, `noc_codes`) so the schema matches.

Tables with ≥ 2M rows are a directory of ~256 MB ZSTD shards (`Grants/*.parquet`). Smaller tables stay `Name.parquet` so existing `data_files="Zips.parquet"` loaders keep working.

UUID columns are `CAST` to `VARCHAR` (same fix as the May dump — Hub's viewer chokes on DuckDB UUID).

## Disk

A full export is tens of GB. Default `--out` is `/Volumes/Data/final/parquet_export_990`. After each table uploads, the local parquet is deleted unless you pass `--keep-local`. Prefer `--export-only` on a disk that can hold the whole set, then `--upload-only`.

## Run

```bash
export HF_TOKEN=hf_...   # write token

# Plan only
python3 upload_to_hf.py --dry-run

# Export + upload (releases each table after a successful push)
python3 upload_to_hf.py

# Local parquet only
python3 upload_to_hf.py --export-only --keep-local

# One table (smoke)
python3 upload_to_hf.py --tables ZipFiles --export-only --out /tmp/hf_smoke

# Force a skipped table in
python3 upload_to_hf.py --include medicare_raw_spending --tables medicare_raw_spending
```

`--db` defaults to `/Volumes/Data/final/irs990.duckdb` (`IRS990_DB` overrides).

## After upload

Hub dataset: https://huggingface.co/datasets/piercewetter3/irs-990-parsed

`README.md` and `manifest.json` are rewritten with live row counts. Stale single-file parquet for tables that are now sharded (and parquet for skipped tables) is deleted from the repo.

The Gradio explorer still loads `Zips.parquet` as a single file. Anything that did `FROM 'Addresses.parquet'` / `'Grants.parquet'` must switch to `'Addresses/*.parquet'` / `'Grants/*.parquet'`.
