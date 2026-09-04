#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
TS=$(date +%Y%m%d_%H%M%S)
LOG="${JOB_LOG:-$ROOT/logs/overnight_census_${TS}.log}"
STATUS="$ROOT/overnight_geolocate_status.txt"
PIDFILE="$ROOT/overnight_geolocate.pid"
DB="/Volumes/Data/final/irs990.duckdb"
FINAL="/Volumes/Data/final"
export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-10GB}"
export GEOLOCATE_PREV_FINALIZE=0
mkdir -p "$ROOT/logs"
echo $$ >"$PIDFILE"
{
  echo "started_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "pid=$$"
  echo "log=$LOG"
  echo "status=running"
  echo "steps=geolocate_census"
  echo "duckdb_memory=$DUCKDB_MEMORY_LIMIT"
  echo "note=restart_after_shutdown_queue_join_deadlock"
} >"$STATUS"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
log "=== geolocate_census RESTART after stuck shutdown join ==="
log "Prior hang: MainThread in pipeline.shutdown/_join_with_timeout; workers idle on empty queues"
set +e
caffeinate -i -s python3 -u irs990processor.py \
  --start-step geolocate_census --stop-step geolocate_census \
  --final-dir "$FINAL" --db-path "$DB" \
  --workers 2 --db-threads 1 --nostats -v \
  >>"$LOG" 2>&1
rc=$?
set -e
if [[ $rc -eq 0 ]]; then log "completed successfully"; else log "exited rc=$rc"; fi
{
  echo "finished_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "pid=$$"
  echo "log=$LOG"
  echo "status=$([[ $rc -eq 0 ]] && echo success || echo failed)"
  echo "exit_code=$rc"
} >"$STATUS"
log "=== census END rc=$rc ==="
echo "done rc=$rc $(date '+%Y-%m-%d %H:%M:%S')" >>"$PIDFILE"
exit $rc
