#!/usr/bin/env bash
# Chunked census: small --max-files per process + os._exit(75) on DuckDB OOM.
# Fresh process each chunk so a poisoned DuckDB write conn cannot linger.
# 2500 max-files still OOMed on consumer save (1-row bulk_update storm); default 500.
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
TS=$(date +%Y%m%d_%H%M%S)
LOG="${JOB_LOG:-$ROOT/logs/overnight_census_chunked_${TS}.log}"
STATUS="$ROOT/overnight_geolocate_status.txt"
PIDFILE="$ROOT/overnight_geolocate.pid"
DB="/Volumes/Data/final/irs990.duckdb"
FINAL="/Volumes/Data/final"
# 8GB fills during Geocoding+Addresses writes on this DB; 12GB still leaves headroom on 16GB host
export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-12GB}"
export GEOCODE_SKIP_OWNER_COLOCATORS="${GEOCODE_SKIP_OWNER_COLOCATORS:-1}"
export GEOCODE_CENSUS_CONSUMER_BATCH="${GEOCODE_CENSUS_CONSUMER_BATCH:-100}"
# Full ANALYZE of Addresses/Geocoding after every 500-row chunk is slower than Census itself
export SKIP_POST_STEP_OPTIMIZE="${SKIP_POST_STEP_OPTIMIZE:-1}"
CHUNK="${CENSUS_CHUNK:-500}"
MAX_ROUNDS="${CENSUS_MAX_ROUNDS:-200}"  # 200*500 covers ~100k pending with margin

mkdir -p "$ROOT/logs"
echo $$ >"$PIDFILE"
{
  echo "started_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "pid=$$"
  echo "log=$LOG"
  echo "status=running"
  echo "steps=geolocate_census_chunked"
  echo "chunk=$CHUNK"
  echo "duckdb_memory=$DUCKDB_MEMORY_LIMIT"
  echo "skip_owner_colocators=$GEOCODE_SKIP_OWNER_COLOCATORS"
  echo "census_consumer_batch=$GEOCODE_CENSUS_CONSUMER_BATCH"
} >"$STATUS"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

pending_count() {
  python3 - <<'PY'
import duckdb, os
con=duckdb.connect(os.environ.get("DB","/Volumes/Data/final/irs990.duckdb"),
                   read_only=True,
                   config={"memory_limit":"4GB","threads":"1"})
print(con.execute("SELECT COUNT(*) FROM Geocoding WHERE geocoding_status='pending'").fetchone()[0])
con.close()
PY
}

export DB
log "=== chunked census START chunk=$CHUNK max_rounds=$MAX_ROUNDS memory=$DUCKDB_MEMORY_LIMIT ==="
overall_rc=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  p=$(pending_count 2>>"$LOG" || echo "?")
  log "--- round $round/$MAX_ROUNDS pending=$p ---"
  if [[ "$p" == "0" ]]; then
    log "No pending left — done"
    break
  fi
  if [[ "$p" == "?" ]]; then
    log "Could not read pending count — abort"
    overall_rc=1
    break
  fi

  set +e
  caffeinate -i -s python3 -u irs990processor.py \
    --start-step geolocate_census \
    --stop-step geolocate_census \
    --final-dir "$FINAL" \
    --db-path "$DB" \
    --max-files "$CHUNK" \
    --workers 2 \
    --db-threads 1 \
    --nostats \
    -v \
    >>"$LOG" 2>&1
  rc=$?
  set -e
  log "round $round exit rc=$rc"
  if [[ $rc -ne 0 ]]; then
    overall_rc=$rc
    log "round failed — continue next chunk after brief pause (idempotent)"
    sleep 5
  else
    sleep 2
  fi
done

p=$(pending_count 2>>"$LOG" || echo "?")
log "=== chunked census END overall_rc=$overall_rc remaining_pending=$p ==="
{
  echo "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "pid=$$"
  echo "log=$LOG"
  echo "status=$([[ $overall_rc -eq 0 ]] && echo success || echo failed)"
  echo "exit_code=$overall_rc"
  echo "remaining_pending=$p"
} >"$STATUS"
echo "done rc=$overall_rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
exit $overall_rc
