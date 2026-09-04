#!/usr/bin/env bash
# Unattended chain after census drain:
#   geolocate_api (public Photon + geocode.maps.co + OpenCage)
#   → pattern preprocess (geocode_tail / geocoding_patterns.json)
#   → grant_match
#   → OFAC co-location reports
#
# Self-hosted Photon is intentionally NOT used (unset PHOTON_*).
# Status: overnight_pipeline_status.txt  Log: logs/overnight_api_grant_reports_*.log
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
TS=$(date +%Y%m%d_%H%M%S)
LOG="${JOB_LOG:-$ROOT/logs/overnight_api_grant_reports_${TS}.log}"
STATUS="$ROOT/overnight_pipeline_status.txt"
PIDFILE="$ROOT/overnight_pipeline.pid"
DB="/Volumes/Data/final/irs990.duckdb"
FINAL="/Volumes/Data/final"

# Keys from direnv / parent env if present
if [[ -f "$ROOT/../.envrc" ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/../.envrc" 2>/dev/null || true
  set +a
fi

# Free public Photon only — paid/self-hosted instance is offline
unset PHOTON_DOMAIN PHOTON_SCHEME || true

export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-12GB}"
export GEOCODE_SKIP_OWNER_COLOCATORS="${GEOCODE_SKIP_OWNER_COLOCATORS:-1}"
export SKIP_POST_STEP_OPTIMIZE="${SKIP_POST_STEP_OPTIMIZE:-1}"
export GEOCODE_CENSUS_CONSUMER_BATCH="${GEOCODE_CENSUS_CONSUMER_BATCH:-100}"

mkdir -p "$ROOT/logs" "$FINAL/duckdb_tmp"
echo $$ >"$PIDFILE"

write_status() {
  {
    echo "updated_at=$(date '+%Y-%m-%d %H:%M:%S')"
    echo "pid=$$"
    echo "log=$LOG"
    echo "status=$1"
    echo "phase=$2"
    shift 2
    for kv in "$@"; do
      echo "$kv"
    done
  } >"$STATUS"
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

status_counts() {
  python3 - <<'PY' 2>>"$LOG" || echo "counts=error"
import duckdb, os
con = duckdb.connect(
    os.environ.get("DB", "/Volumes/Data/final/irs990.duckdb"),
    read_only=True,
    config={"memory_limit": "4GB", "threads": "1"},
)
rows = con.execute(
    """
    SELECT geocoding_status, COUNT(*)::BIGINT
    FROM Geocoding
    WHERE geocoding_status IN (
      'pending_api', 'pending', 'grok_pending', 'geocode_tail',
      'Match:Photon', 'Match:GeocodeMapsCo', 'Match:OpenCage',
      'Match:PatternOwners', 'No_Match'
    )
    GROUP BY 1 ORDER BY 2 DESC
    """
).fetchall()
con.close()
parts = [f"{s}={n}" for s, n in rows]
print(" ".join(parts) if parts else "counts=empty")
PY
}

export DB
write_status running init "steps=geolocate_api,pattern_preprocess,grant_match,ofac_reports" \
  "duckdb_memory=$DUCKDB_MEMORY_LIMIT" "photon=public_komoot" "maps=geocode.maps.co" "opencage=on"
log "=== pipeline START memory=$DUCKDB_MEMORY_LIMIT photon=public maps+opencage ==="
log "keys: MAPS=${GEOCODE_MAPS_API_KEY:+set} OPENCAGE=${OPENCAGE_API_KEY:+set} PHOTON_DOMAIN=${PHOTON_DOMAIN:-unset}"
log "baseline: $(status_counts)"
overall_rc=0

# ----- Phase 1: geolocate_api -----
write_status running geolocate_api "note=pending_api via photon+maps+opencage"
log "=== PHASE geolocate_api ==="
set +e
caffeinate -i -s python3 -u irs990processor.py \
  --start-step geolocate_api \
  --stop-step geolocate_api \
  --final-dir "$FINAL" \
  --db-path "$DB" \
  --workers 4 \
  --db-threads 1 \
  --nostats \
  -v \
  >>"$LOG" 2>&1
rc=$?
set -e
log "geolocate_api exit rc=$rc counts=$(status_counts)"
if [[ $rc -ne 0 ]]; then
  overall_rc=$rc
  log "geolocate_api FAILED — continuing to pattern preprocess (idempotent / free)"
fi

# ----- Phase 2: pattern preprocess on geocode_tail -----
write_status running pattern_preprocess "note=geocode_tail + geocoding_patterns.json"
log "=== PHASE pattern_preprocess (geocode_tail) ==="
set +e
caffeinate -i -s python3 -u preprocess_geocode_tail.py \
  --db-path "$DB" \
  --final-dir "$FINAL" \
  >>"$LOG" 2>&1
rc=$?
set -e
log "pattern_preprocess exit rc=$rc counts=$(status_counts)"
if [[ $rc -ne 0 ]]; then
  overall_rc=$rc
  log "pattern_preprocess FAILED — continuing to grant_match"
fi

# Optional: re-export remaining pending_api for offline mining
set +e
python3 -u - <<'PY' >>"$LOG" 2>&1
from database_operations import DatabaseOperations
from geocoding_api_processor import GeocodingAPIProcessor
from config import global_config
global_config.final_dir = "/Volumes/Data/final"
db = DatabaseOperations("/Volumes/Data/final/irs990.duckdb")
n = GeocodingAPIProcessor(db).export_census_failures_for_patterns()
print(f"re-exported pending_api failures: {n}", flush=True)
db.close()
PY
set -e

# ----- Phase 3: grant_match -----
write_status running grant_match "note=colocator hail-mary match"
log "=== PHASE grant_match ==="
set +e
DUCKDB_MEMORY_LIMIT=5GB caffeinate -i -s python3 -u irs990processor.py \
  --start-step grant_match \
  --stop-step grant_match \
  --final-dir "$FINAL" \
  --db-path "$DB" \
  --workers 4 \
  --db-threads 1 \
  --nostats \
  -v \
  >>"$LOG" 2>&1
rc=$?
set -e
log "grant_match exit rc=$rc"
if [[ $rc -ne 0 ]]; then
  overall_rc=$rc
  log "grant_match FAILED — skipping reports"
  write_status failed grant_match "exit_code=$rc" "log=$LOG"
  echo "done rc=$overall_rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
  exit $overall_rc
fi

# ----- Phase 4: OFAC reports -----
write_status running ofac_reports "note=generate_ofac_reports"
log "=== PHASE ofac_reports ==="
set +e
caffeinate -i -s python3 -u ofac_reporting/generate_ofac_reports.py \
  --db-path "$DB" \
  >>"$LOG" 2>&1
rc=$?
set -e
log "ofac_reports exit rc=$rc"
if [[ $rc -ne 0 ]]; then
  overall_rc=$rc
fi

log "=== pipeline END overall_rc=$overall_rc counts=$(status_counts) ==="
if [[ $overall_rc -eq 0 ]]; then
  write_status success done "exit_code=0" "log=$LOG" "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
else
  write_status failed done "exit_code=$overall_rc" "log=$LOG" "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
fi
echo "done rc=$overall_rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
exit $overall_rc
