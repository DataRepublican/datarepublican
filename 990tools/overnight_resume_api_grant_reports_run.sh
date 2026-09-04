#!/usr/bin/env bash
# Resume after failed overnight_api_grant_reports:
#   chunked geolocate_api (remaining pending_api) → grant_match → ofac reports
# Assumes Grants ART already rebuilt if needed.
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
TS=$(date +%Y%m%d_%H%M%S)
LOG="${JOB_LOG:-$ROOT/logs/overnight_resume_api_grant_${TS}.log}"
STATUS="$ROOT/overnight_pipeline_status.txt"
PIDFILE="$ROOT/overnight_pipeline.pid"
DB="/Volumes/Data/final/irs990.duckdb"
FINAL="/Volumes/Data/final"

if [[ -f "$ROOT/../.envrc" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/../.envrc" 2>/dev/null || true
  set +a
fi
unset PHOTON_DOMAIN PHOTON_SCHEME || true

# Tighter than first pass — API tail OOMed at 11.1GiB on 12GB pin
export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-8GB}"
export GEOCODE_SKIP_OWNER_COLOCATORS="${GEOCODE_SKIP_OWNER_COLOCATORS:-1}"
export SKIP_POST_STEP_OPTIMIZE="${SKIP_POST_STEP_OPTIMIZE:-1}"
export GEOCODE_CENSUS_CONSUMER_BATCH="${GEOCODE_CENSUS_CONSUMER_BATCH:-50}"
# Prefer smaller in-flight if constants allow env override (harmless if unused)
export GEOCODING_API_IN_FLIGHT_CAP="${GEOCODING_API_IN_FLIGHT_CAP:-200}"

CHUNK="${API_CHUNK:-400}"
MAX_ROUNDS="${API_MAX_ROUNDS:-40}"
# Fail-stage join can hang indefinitely after max-files drain; hard-cap each round.
ROUND_TIMEOUT_SEC="${API_ROUND_TIMEOUT_SEC:-2100}"  # 35 min

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
    for kv in "$@"; do echo "$kv"; done
  } >"$STATUS"
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

pending_api_count() {
  python3 - <<'PY' 2>>"$LOG" || echo "?"
import duckdb, os
con = duckdb.connect(os.environ.get("DB","/Volumes/Data/final/irs990.duckdb"),
                     read_only=True, config={"memory_limit":"3GB","threads":"1"})
print(con.execute("SELECT COUNT(*) FROM Geocoding WHERE geocoding_status='pending_api'").fetchone()[0])
con.close()
PY
}

export DB
write_status running init "steps=chunked_geolocate_api,grant_match,ofac_reports" \
  "duckdb_memory=$DUCKDB_MEMORY_LIMIT" "chunk=$CHUNK" "photon=public_komoot"
log "=== RESUME START memory=$DUCKDB_MEMORY_LIMIT chunk=$CHUNK ==="
log "keys: MAPS=${GEOCODE_MAPS_API_KEY:+set} OPENCAGE=${OPENCAGE_API_KEY:+set}"
overall_rc=0

# ----- Phase 1: chunked geolocate_api -----
write_status running geolocate_api "chunk=$CHUNK"
for round in $(seq 1 "$MAX_ROUNDS"); do
  p=$(pending_api_count)
  log "--- api round $round/$MAX_ROUNDS pending_api=$p ---"
  if [[ "$p" == "0" ]]; then
    log "pending_api drained"
    break
  fi
  if [[ "$p" == "?" ]]; then
    log "Could not read pending_api — abort api phase"
    overall_rc=1
    break
  fi
  set +e
  caffeinate -i -s python3 -u irs990processor.py \
    --start-step geolocate_api \
    --stop-step geolocate_api \
    --final-dir "$FINAL" \
    --db-path "$DB" \
    --max-files "$CHUNK" \
    --workers 2 \
    --db-threads 1 \
    --nostats \
    -v \
    >>"$LOG" 2>&1 &
  api_pid=$!
  # Wait with timeout — hung fail-stage join leaves zombie pipeline
  waited=0
  while kill -0 "$api_pid" 2>/dev/null; do
    if (( waited >= ROUND_TIMEOUT_SEC )); then
      log "api round $round TIMEOUT after ${ROUND_TIMEOUT_SEC}s — killing pid $api_pid"
      kill -TERM "$api_pid" 2>/dev/null || true
      sleep 8
      kill -KILL "$api_pid" 2>/dev/null || true
      # also kill any leftover processor children
      pkill -f "irs990processor.py --start-step geolocate_api" 2>/dev/null || true
      break
    fi
    sleep 5
    waited=$((waited + 5))
  done
  wait "$api_pid" 2>/dev/null
  rc=$?
  set -e
  log "api round $round exit rc=$rc waited=${waited}s"
  if [[ $rc -ne 0 ]]; then
    overall_rc=$rc
    log "api round non-zero — pause and continue (idempotent)"
    sleep 5
  else
    sleep 2
  fi
done
p=$(pending_api_count)
log "api phase done remaining_pending_api=$p overall_rc=$overall_rc"

# ----- Phase 2: grant_match -----
write_status running grant_match "note=post ART rebuild"
log "=== PHASE grant_match ==="
set +e
DUCKDB_MEMORY_LIMIT=6GB caffeinate -i -s python3 -u irs990processor.py \
  --start-step grant_match \
  --stop-step grant_match \
  --final-dir "$FINAL" \
  --db-path "$DB" \
  --workers 2 \
  --db-threads 1 \
  --nostats \
  -v \
  >>"$LOG" 2>&1
rc=$?
set -e
log "grant_match exit rc=$rc"
if [[ $rc -ne 0 ]]; then
  overall_rc=$rc
  write_status failed grant_match "exit_code=$rc" "log=$LOG"
  echo "done rc=$overall_rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
  exit $overall_rc
fi

# ----- Phase 3: reports -----
write_status running ofac_reports
log "=== PHASE ofac_reports ==="
set +e
caffeinate -i -s python3 -u ofac_reporting/generate_ofac_reports.py \
  --db-path "$DB" \
  >>"$LOG" 2>&1
rc=$?
set -e
log "ofac_reports exit rc=$rc"
[[ $rc -ne 0 ]] && overall_rc=$rc

log "=== RESUME END overall_rc=$overall_rc remaining_pending_api=$(pending_api_count) ==="
if [[ $overall_rc -eq 0 ]]; then
  write_status success done "exit_code=0" "log=$LOG" "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
else
  write_status failed done "exit_code=$overall_rc" "log=$LOG" "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
fi
echo "done rc=$overall_rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
exit $overall_rc
