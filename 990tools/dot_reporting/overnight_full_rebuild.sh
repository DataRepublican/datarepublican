#!/bin/bash
# Overnight full rebuild: national + by-state with latest code (breadcrumbs, maps,
# TanStack details, medicare rollup, rank dots). Rebuilds master_index after each suite.
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DR="dot_reporting"
DB="${IRS990_DB_PATH:-/Volumes/Data/final/irs990.duckdb}"
DAY=$(date +%Y-%m-%d)
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$DR/overnight_rebuild_${STAMP}.log"
failed=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

rebuild_master() {
  python3 -u "$DR/build_master_index.py" --reports-dir "$DR/reports" >>"$LOG" 2>&1 || true
}

# Prefer in-place medicare rollup; fall back to sidecar attach path
ensure_medicare_rollup() {
  log "Ensuring medicare provider rollup..."
  if python3 -u build_medicare_provider_rollup.py --in-place --db-path "$DB" \
      --memory-limit "${DUCKDB_MEMORY_LIMIT:-24GB}" --threads 4 >>"$LOG" 2>&1; then
    log "Medicare rollup in-place OK"
  else
    log "In-place rollup locked/failed — building sidecar"
    python3 -u build_medicare_provider_rollup.py \
      --db-path "$DB" \
      --side-db /Volumes/Data/final/medicare_provider_rollup.duckdb \
      --memory-limit "${DUCKDB_MEMORY_LIMIT:-24GB}" --threads 4 >>"$LOG" 2>&1 \
      || log "WARN: medicare rollup build failed (reports degrade gracefully)"
  fi
}

run_dot_national() {
  local slice="$1"
  local out="$DR/reports/${slice}_clusters_${DAY}"
  log "---- NATIONAL DOT slice=$slice → $out ----"
  if python3 -u "$DR/generate_address_reports.py" \
      --db-path "$DB" --slice-by "$slice" --output-dir "$out" >>"$LOG" 2>&1; then
    log "---- OK national DOT $slice ----"
  else
    log "---- FAIL national DOT $slice rc=$? ----"
    failed=1
  fi
  rebuild_master
}

run_focus_national() {
  local focus="$1" slice="$2"
  local out="$DR/reports/${focus}_${slice}_clusters_${DAY}"
  log "---- NATIONAL focus=$focus slice=$slice → $out ----"
  if python3 -u "$DR/generate_focus_reports.py" \
      --db-path "$DB" --focus "$focus" --slice-by "$slice" \
      --output-dir "$out" >>"$LOG" 2>&1; then
    log "---- OK national $focus $slice ----"
  else
    log "---- FAIL national $focus $slice rc=$? ----"
    failed=1
  fi
  rebuild_master
}

run_state_full() {
  local focus="$1" slice="$2"
  local out="$DR/reports/${focus}_${slice}_by_state_${DAY}"
  log "---- STATE-FULL focus=$focus slice=$slice → $out ----"
  if python3 -u "$DR/generate_state_reports.py" \
      --db-path "$DB" --focus "$focus" --slice-by "$slice" \
      --output-dir "$out" >>"$LOG" 2>&1; then
    log "---- OK state $focus $slice ----"
  else
    log "---- FAIL state $focus $slice rc=$? ----"
    failed=1
  fi
  rebuild_master
}

log "=== OVERNIGHT FULL REBUILD START day=$DAY db=$DB ==="
log "log=$LOG"
if [ ! -r "$DB" ]; then
  log "FATAL: cannot read $DB"
  exit 1
fi

ensure_medicare_rollup

log "=== PHASE 1: National DOT (4 slices) ==="
for slice in colocator zipcode loose_colocator address; do
  run_dot_national "$slice"
done

log "=== PHASE 2: National focus × location ==="
for focus in medicare fec contractor grants; do
  for slice in colocator zipcode loose_colocator address; do
    run_focus_national "$focus" "$slice"
  done
done

log "=== PHASE 3: By-state full (5 × 4) ==="
for focus in dot medicare fec contractor grants; do
  for slice in colocator zipcode loose_colocator address; do
    run_state_full "$focus" "$slice"
  done
done

rebuild_master
log "=== OVERNIGHT REBUILD DONE failed=$failed ==="
log "Open: $DR/reports/master_index.html"
exit $failed
