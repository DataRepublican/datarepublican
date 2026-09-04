# Project hygiene — reporting stack

**Policy while pipelines run:** git commits, `.gitignore`, and markdown are fine.  
Do **not** delete `/Volumes/Data/final/irs990.duckdb*` while overnight is active.  
Do **not** wipe `dot_reporting/reports/*_YYYY-MM-DD` for the day being written.

## Status snapshot (maintain)

| Item | Location |
|------|----------|
| Overnight rebuild | `/tmp/overnight_rebuild.pid`, `overnight_rebuild_*.log` |
| Hub | `reports/master_index.html` (gitignored; rebuild with `build_master_index.py`) |
| Main DB | `/Volumes/Data/final/irs990.duckdb` |
| Medicare $ sidecar | `/Volumes/Data/final/medicare_provider_rollup.duckdb` |

## Safe anytime
- `git add` / `commit` of **source** under `dot_reporting/` (not `reports/`)
- Edit `.gitignore`, docs (`*.md`)
- `python3 build_master_index.py`
- Delete **smoke** report dirs only
- Kill nothing unless aborting overnight intentionally

## After overnight finishes
1. Confirm `DONE` + `failed=0` in overnight log  
2. Optional: prune older day suites (`*_2026-07-10`, `*_2026-07-11`)  
3. Rebuild master_index  
4. **Disk:** only then consider deleting  
   - `irs990.duckdb.pre_ctas_promote_*`  
   - `irs990.duckdb.geolocate.pre_promote_*`  
   (~170G+ if both go)  
5. Optional: `build_medicare_provider_rollup.py --in-place` when no writers hold the main DB  

## Source map (commit as a unit)
```
dot_reporting/
  generate_address_reports.py
  generate_focus_reports.py
  generate_state_reports.py
  state_research.py
  build_master_index.py
  breadcrumbs.py widen_links.py map_points.py
  html_format.py cluster_table_payload.py grant_suppress.py
  us_state_map.py us_state_paths.py
  templates/ + templates/partials/
  overnight_full_rebuild.sh full_regen_all.sh
build_medicare_provider_rollup.py
schema_duckdb.sql  # medicare_provider_hcpcs / rollup
```

## Ignore (generated)
- `dot_reporting/reports/` (~5G+ HTML)
- `*.log`, `*.pid`

## Serve locally
```bash
cd dot_reporting/reports && python3 -m http.server 8000
# http://localhost:8000/master_index.html
```
