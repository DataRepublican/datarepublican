# 990tools Issue Bootstrap (Minimal Restart)

**Purpose**: Fast, low-token restart for a fresh session after CLI crashes (127/137 kills) or context resets.

**Last major work**: July 2026 — **geolocate_new v9** running on Data2. Prior: geolocate trilogy refactor, Grok failure taxonomy, address dedup (`7ea4a2a1`).

## Current State

### Geolocate (IN PROGRESS — do not run parallel writers)
- **DB:** `/Volumes/Data2/final/irs990.duckdb` (+ `.wal` — copy together)
- **Step:** `geolocate_new` only (Grok deferred to `geolocate_grok`)
- **Run:** v9 — `geolocate_step_20260630_v9.log`, PID in `geolocate.pid`
- **Monitor:** `./geolocate_monitor.sh` → `geolocate_monitor.log`
- **Status (~2026-07-02):** ~38h uptime; fed 50k/10.1M session; hard-tail serial grind (~250–400/hr); Photon 32 workers @ `45.61.62.160:2322`
- **Exit hard tail:** first `census batch=10000 matched=5xxx` on a new 10k feed
- **Watch:**
  ```bash
  tail -5 geolocate_monitor.log
  ps -p $(cat geolocate.pid)
  tail -f geolocate_step_20260630_v9.log | grep -E '→|census batch=10000'
  ```

### After geolocate_new completes
1. `geolocate_grok` — xAI Batch API (needs credits; DB write lock)
2. `geolocate_archive` — export successes + `grok:*` failures to archive TSV
3. `grant_match` — colocator / loose_colocator hail-mary

### Address (production-validated 2026-06-20)
- 95,196,749 addresses; **0** NULL `master_id`
- 14,342,486 Geocoding canonical groups
- Logs: `address_step_20260620_v2.log`, `address_step_20260620_v2_indexes.log`

### External ingests (complete)
- **FEC 2024**, **Medicare**, **Sanctions**, **DOT**, **Einless** — see `docs/RECENTGOALS.md`

## Pipeline Step Order

```
irsfetch → zip → bmf → xml → fec → medicare → sanctions → dot → address → einless → match
  → geolocate_prev → geolocate_new → geolocate_grok → geolocate_archive → photos → grant_match → …
```

**Geolocate trilogy:** wired in `irs990processor.py`. Legacy: `geolocate` → `geolocate_new`, `geolocate1` → `geolocate_prev`.

## Core Philosophy
- Raw `recipient_ein` = filed data; `recipient_ein_backfilled` = inferred. Never mix them.
- DuckDB single-writer — only one pipeline step holding write lock at a time.
- Use `nohup` for long steps (`geolocate_*`, `grant_match`).

## Known Ops Problems
- CLI kills with 127/137 (OOM). Use `nohup` + log redirection.
- Default logging is WARNING — add `-v` for progress lines.
- Old production path was `/Volumes/Data/final` — **now Data2** (Data drive repurposed).

## Docs to read first
- `docs/RECENTGOALS.md` — living scratchpad (geolocate v9 section at top)
- `docs/einless_grantee_resolution_architecture.md` — einless hard tail (paused match integration)