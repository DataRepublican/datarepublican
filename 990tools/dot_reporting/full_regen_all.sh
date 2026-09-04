#!/bin/bash
# Full regeneration of national + by-state cluster reports, then master_index.
# Stable (undated) suite paths for public deploy (grumpytechbro.com).
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DR="dot_reporting"
DB="${IRS990_DB_PATH:-/Volumes/Data/final/irs990.duckdb}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="${MATRIX_LOG:-$DR/full_regen_${TS}.log}"
failed=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

rebuild_master() {
  python3 -u "$DR/build_master_index.py" --reports-dir "$DR/reports" >>"$LOG" 2>&1 || true
}

run_dot_national() {
  local slice="$1"
  local out="$DR/reports/${slice}_clusters"
  log "---- NATIONAL dot slice=$slice → $out ----"
  if python3 -u "$DR/generate_address_reports.py" \
      --db-path "$DB" --slice-by "$slice" --output-dir "$out" >>"$LOG" 2>&1; then
    log "---- OK national dot $slice ----"
  else
    log "---- FAIL national dot $slice rc=$? ----"
    failed=1
  fi
  rebuild_master
}

run_focus_national() {
  local focus="$1" slice="$2"
  local out="$DR/reports/${focus}_${slice}_clusters"
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
  local out="$DR/reports/${focus}_${slice}_by_state"
  log "---- STATE-FULL focus=$focus slice=$slice → $out ----"
  if python3 -u "$DR/generate_state_reports.py" \
      --db-path "$DB" --focus "$focus" --slice-by "$slice" \
      --output-dir "$out" >>"$LOG" 2>&1; then
    log "---- OK state $focus $slice ----"
    local nst npg
    nst=$(find "$out/states" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    npg=$(find "$out/states" -name '*.html' 2>/dev/null | wc -l | tr -d ' ')
    log "     states=$nst html≈$npg"
  else
    log "---- FAIL state $focus $slice rc=$? ----"
    failed=1
  fi
  rebuild_master
}

log "=== FULL REGEN START (stable undated paths) db=$DB ==="
log "log=$LOG"
if [ ! -r "$DB" ]; then
  log "FATAL: cannot read $DB"
  exit 1
fi

# Phase 1 — national DOT (location + address)
log "=== PHASE 1: National DOT (4 slices) ==="
for slice in colocator zipcode loose_colocator address; do
  run_dot_national "$slice"
done

# Phase 2 — national focus types × location + address
log "=== PHASE 2: National focus (medicare/fec/contractor/grants/grants_out/usg × 4) ==="
for focus in medicare fec contractor grants grants_out usg; do
  for slice in colocator zipcode loose_colocator address; do
    run_focus_national "$focus" "$slice"
  done
done

# Phase 3 — full by-state (heatmap + details)
log "=== PHASE 3: By-state full details (7 types × 4 slices) ==="
for focus in dot medicare fec contractor grants grants_out usg; do
  for slice in colocator zipcode loose_colocator address; do
    run_state_full "$focus" "$slice"
  done
done

rebuild_master
log "=== FULL REGEN DONE failed=$failed ==="
log "Master index: $DR/reports/master_index.html"
ls -ld "$DR/reports"/*_clusters "$DR/reports"/*_by_state 2>/dev/null | tee -a "$LOG" || true
exit $failed
