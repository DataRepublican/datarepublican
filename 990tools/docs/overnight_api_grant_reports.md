# Overnight API → grant_match → OFAC

## Why

After Census drains `pending` to zero, residual geocoding sits in **`pending_api`**. Burning OpenCage / maps.co (and free public Photon) there is cheaper and higher-precision than sending everything to Grok. Then **grant_match** needs healthy Grants/Charities indexes and lat/lon so colocator hail-mary can run; OFAC HTML is the first public-facing co-location product on the refreshed DB.

Self-hosted Photon on Kamatera was offline (connect timeout). Scripts **unset `PHOTON_DOMAIN` / `PHOTON_SCHEME`** so the pipeline uses public `photon.komoot.io` (throttled) instead of hanging probes on a dead VPS.

## What these launchers do

| Script | Role |
|--------|------|
| `overnight_api_grant_reports_run.sh` | `geolocate_api` → `preprocess_geocode_tail` → `grant_match` → OFAC |
| `overnight_resume_api_grant_reports_run.sh` | Chunked `geolocate_api` (with per-round timeout) → `grant_match` → OFAC |

Status: `overnight_pipeline_status.txt`. Logs under `logs/overnight_*`.

## Ops defaults (16GB host)

- `DUCKDB_MEMORY_LIMIT` 8–12 GB for API; ~6–8 GB for grant_match
- `GEOCODE_SKIP_OWNER_COLOCATORS=1` during geocode saves
- API chunks of **400** after fail-stage join hangs on larger chunks
- `API_ROUND_TIMEOUT_SEC=2100` — kill hung fail-stage joins so the shell advances

## Failure modes (learned)

1. **OOM on PDC save** (~11 GiB) → process `os._exit(75)`; chunk and continue.
2. **Fail-stage join hang** — queues empty, 0% CPU, CLOSE_WAIT sockets; kill and resume.
3. **Grants/Charities ART FATAL** on bulk lat/lon UPDATE — rebuild via CTAS; fill lat/lon with equality joins (see `grant_match_processor.populate_lat_lon_columns`).
4. **WAL “Bad file descriptor”** after crash — aside WAL (backup first), open base, checkpoint.

## Production snapshot (2026-08-11)

- `pending_api` drained to **0**
- grant_match **success**; OFAC reports under `ofac_reporting/reports/`
- Follow-on: `preprocess_grok_pending.py` before Grok (see `docs/preprocess_grok_pending.md`)

## Related

- Census chunk loop: `docs/overnight_census_chunked.md`
- Live DB: `/Volumes/Data/final/irs990.duckdb`
