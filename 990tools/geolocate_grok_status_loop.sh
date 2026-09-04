#!/bin/bash
# Status report every 30m until 5pm or loop stops.
set -euo pipefail
cd "$(dirname "$0")"
OUT=geolocate_grok_status_30m.log
STOP_HOUR=17

report() {
  echo "======== $(date '+%Y-%m-%d %H:%M:%S') ========"
  if [[ -f geolocate_grok_overnight.lock ]]; then
    LPID=$(cat geolocate_grok_overnight.lock)
    ps -p "$LPID" -o pid=,etime=,command= 2>/dev/null | sed 's/^/  loop: /' || echo "  loop: not running (stale lock)"
  else
    echo "  loop: not running"
  fi
  if [[ -f geolocate.pid ]]; then
    PIPE_PID=$(cat geolocate.pid)
    ps -p "$PIPE_PID" -o pid=,etime=,stat= 2>/dev/null | sed 's/^/  pipe: /' || echo "  pipe: not running"
  else
    echo "  pipe: not running"
  fi
  python3 - <<'PY' 2>/dev/null || echo "  state: unreadable"
import json, re
from pathlib import Path
s = json.loads(Path("geolocate_grok_overnight_state.json").read_text())
print(f"  next_iter: {s['iter']}  batch: {s['batch_size']:,}")
h = [x for x in s.get("history", []) if x.get("ok") and "matched" in x]
if h:
    last = h[-1]
    print(f"  last_ok: iter-{last['iter']} pre={last.get('preprocess')} matched={last.get('matched')} classified={last.get('classified')}")
# current iter log tail
import glob
logs = sorted(glob.glob("geolocate_step_20260708_grok_iter*.log"), key=lambda p: int(re.search(r"iter(\d+)", p).group(1)))
if logs:
    t = Path(logs[-1]).read_text(errors="replace")
    m = re.search(r"iter(\d+)", logs[-1])
    n = m.group(1) if m else "?"
    for pat, label in [
        (r"\[geolocate_grok\] preprocess matched=(\d+) survivors=(\d+)/(\d+)", "preprocess"),
        (r"batch \d+ done matched=(\d+) classified=(\d+)", "done"),
        (r"polling \S+ requests=(\d+) pending=(\d+) success=(\d+)", "poll"),
    ]:
        hits = re.findall(pat, t)
        if hits:
            print(f"  iter-{n} {label}: {hits[-1]}")
PY
  tail -3 geolocate_grok_overnight.log 2>/dev/null | sed 's/^/  /'
  echo
}

while [[ $((10#$(date +%H))) -lt $STOP_HOUR ]]; do
  report >> "$OUT"
  sleep 1800
done
report >> "$OUT"
echo "[status_loop] stopped at ${STOP_HOUR}:00 $(date)" >> "$OUT"