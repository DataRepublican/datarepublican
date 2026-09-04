#!/bin/bash
# Monitor geolocate_new with adaptive cadence from process start:
#   checks at 2h,4h,6h,8h,10h  (every 2h for first 10h)
#   then 11h,12h,13h,14h       (every 1h)
#   then every 30m after 14h

set -euo pipefail
cd "$(dirname "$0")"

PIDFILE=geolocate.pid
LOG=geolocate_step_20260704_census.log
OUT=geolocate_monitor.log
STATE=geolocate_monitor.state
PROGRESS_STATE=geolocate_monitor.progress
METRICS_STATE=geolocate_monitor.metrics
LOCKDIR=/tmp/geolocate_monitor.lockdir
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "geolocate_monitor already running — exit" >&2
    exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

MILESTONES=(
    7200   #  2h
    14400  #  4h
    21600  #  6h
    28800  #  8h
    36000  # 10h
    39600  # 11h
    43200  # 12h
    46800  # 13h
    50400  # 14h
)

strip_commas() {
    echo "$1" | tr -d ','
}

# Bash (( )) treats multi-word values as syntax errors — coerce to a single integer.
as_int() {
    local v
    v=$(strip_commas "${1:-0}")
    v=${v%%[^0-9]*}
    echo "${v:-0}"
}

fmt_num() {
    printf "%'d" "$1" 2>/dev/null || echo "$1"
}

fmt_rate_hr() {
    local n=$1
    if (( n >= 1000000 )); then
        printf "~%.1fM/hr" "$(echo "scale=1; $n / 1000000" | bc)"
    elif (( n >= 1000 )); then
        printf "~%.0fk/hr" "$(echo "scale=0; $n / 1000" | bc)"
    else
        printf "~%d/hr" "$n"
    fi
}

fmt_duration() {
    local secs=$1
    if (( secs < 3600 )); then
        printf "~%dm" "$(( (secs + 59) / 60 ))"
    elif (( secs < 172800 )); then
        local hrs=$(( (secs + 3599) / 3600 ))
        local mins=$(( (secs % 3600 + 59) / 60 ))
        if (( mins > 0 && hrs < 48 )); then
            printf "~%dh%dm" "$hrs" "$mins"
        else
            printf "~%dh" "$hrs"
        fi
    else
        local days=$(( (secs + 86399) / 86400 ))
        printf "~%dd" "$days"
    fi
}

fmt_eta() {
    local remaining=$1 rate=$2 now_epoch=$3
    if (( rate <= 0 || remaining <= 0 )); then
        echo "?"
        return
    fi
    local secs=$(( remaining * 3600 / rate ))
    local finish_epoch=$(( now_epoch + secs ))
    local finish_ts
    if (( secs >= 172800 )); then
        finish_ts=$(date -r "$finish_epoch" '+%b %d %Y %H:%M' 2>/dev/null || echo "?")
    else
        finish_ts=$(date -r "$finish_epoch" '+%b %d %H:%M' 2>/dev/null || echo "?")
    fi
    printf "%s @ %s" "$(fmt_duration "$secs")" "$finish_ts"
}

get_total_pending() {
    local from_log
    from_log=$(/usr/bin/head -n 200 "$LOG" 2>/dev/null \
        | /usr/bin/grep -m1 'pending addresses' \
        | /usr/bin/sed -n 's/.*for \([0-9,]*\) pending addresses.*/\1/p' || true)
    if [[ -n "$from_log" ]]; then
        as_int "$from_log"
        return
    fi
    if [[ -f "$STATE.pending" ]]; then
        as_int "$(cat "$STATE.pending" 2>/dev/null || echo 0)"
        return
    fi
    echo 0
}

parse_run_stats_sum() {
    local line=$1
    local census census_strip preprocess other grok_queued grok_match grok_fail
    census=$(echo "$line" | /usr/bin/grep -oE 'census=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' | /usr/bin/head -1 || echo 0)
    census_strip=$(echo "$line" | /usr/bin/grep -oE 'census_strip=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    preprocess=$(echo "$line" | /usr/bin/grep -oE 'preprocess=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    other=$(echo "$line" | /usr/bin/grep -oE 'other=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    grok_queued=$(echo "$line" | /usr/bin/grep -oE 'grok_queued=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    grok_match=$(echo "$line" | /usr/bin/grep -oE 'grok_match=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    grok_fail=$(echo "$line" | /usr/bin/grep -oE 'grok_fail=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || echo 0)
    echo $(( $(strip_commas "${census:-0}") + $(strip_commas "${census_strip:-0}") \
        + $(strip_commas "${preprocess:-0}") + $(strip_commas "${other:-0}") \
        + $(strip_commas "${grok_queued:-0}") + $(strip_commas "${grok_match:-0}") \
        + $(strip_commas "${grok_fail:-0}") ))
}

parse_progress() {
    local recent=$1
    local total=0 fed=0 fed_line stats_line checkpoint_line drain=0
    local resolved=0 committed=0 in_flight=0 db_committed=0
    local metric_label processed remaining pct

    fed_line=$(echo "$recent" | /usr/bin/grep '→ .* fed' | /usr/bin/tail -1 || true)
    stats_line=$(echo "$recent" | /usr/bin/grep -E '\[geolocate_(new|census|api|grok)\] running' | /usr/bin/tail -1 || true)
    checkpoint_line=$(echo "$recent" | /usr/bin/grep 'FORCE CHECKPOINT at' | /usr/bin/tail -1 || true)
    if echo "$recent" | /usr/bin/grep -qF 'Last batch sent'; then
        drain=1
    fi

    if [[ -n "$fed_line" ]]; then
        fed=$(echo "$fed_line" | /usr/bin/sed -n 's/.*→ \([0-9,]*\)\/\([0-9,]*\) fed.*/\1/p')
        total=$(echo "$fed_line" | /usr/bin/sed -n 's/.*→ \([0-9,]*\)\/\([0-9,]*\) fed.*/\2/p')
        fed=$(strip_commas "${fed:-0}")
        total=$(strip_commas "${total:-0}")
    fi
    if (( total == 0 )); then
        total=$(get_total_pending)
    fi
    total=$(as_int "$total")
    fed=$(as_int "${fed:-0}")

    if [[ -n "$stats_line" ]]; then
        resolved=$(parse_run_stats_sum "$stats_line")
        local committed_field in_flight_field
        committed_field=$(echo "$stats_line" | /usr/bin/grep -oE 'committed=[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || true)
        in_flight_field=$(echo "$stats_line" | /usr/bin/grep -oE 'in_flight≈[0-9,]+' | /usr/bin/grep -oE '[0-9,]+' || true)
        if [[ -n "$committed_field" ]]; then
            committed=$(strip_commas "$committed_field")
        fi
        if [[ -n "$in_flight_field" ]]; then
            in_flight=$(strip_commas "$in_flight_field")
        fi
    fi
    if [[ -n "$checkpoint_line" ]]; then
        local cumulative
        cumulative=$(echo "$checkpoint_line" | /usr/bin/sed -n 's/.*at ~\([0-9,]*\) cumulative.*/\1/p')
        cumulative=$(strip_commas "${cumulative:-0}")
        db_committed=$(( cumulative / 2 ))
        if (( committed == 0 )); then
            committed=$db_committed
        fi
    fi
    if (( in_flight == 0 )) && (( fed > committed )); then
        in_flight=$(( fed - committed ))
    fi

    if (( drain == 1 )); then
        processed=$committed
        metric_label="committed"
        fed=${total:-$fed}
    else
        processed=${fed:-0}
        metric_label="fed"
    fi

    if (( total > 0 )); then
        remaining=$(( total - committed ))
        (( remaining < 0 )) && remaining=0
        pct=$(( committed * 10000 / total ))
    else
        remaining=0
        pct=0
    fi

    echo "${total}|${fed}|${processed}|${remaining}|${pct}|${drain}|${metric_label}|${resolved}|${committed}|${in_flight}"
}

compute_rates() {
    local now_epoch processed etsecs drain
    local last_epoch last_processed last_drain interval_rate avg_rate
    now_epoch=$(as_int "$1")
    processed=$(as_int "$2")
    etsecs=$(as_int "$3")
    drain=$(as_int "$4")
    last_epoch=0
    last_processed=0
    last_drain=0
    if [[ -f "$PROGRESS_STATE" ]]; then
        IFS=' ' read -r last_epoch last_processed last_drain < "$PROGRESS_STATE" || true
        last_epoch=$(as_int "$last_epoch")
        last_processed=$(as_int "$last_processed")
        last_drain=$(as_int "$last_drain")
    fi
    printf '%s %s %s\n' "$now_epoch" "$processed" "$drain" > "$PROGRESS_STATE"

    if (( etsecs > 360 && processed > 0 )); then
        avg_rate=$(( processed * 3600 / etsecs ))
    else
        avg_rate=0
    fi

    if (( last_epoch > 0 && now_epoch > last_epoch && processed > last_processed )); then
        interval_rate=$(( (processed - last_processed) * 3600 / (now_epoch - last_epoch) ))
    elif (( avg_rate > 0 )); then
        interval_rate=$avg_rate
    else
        interval_rate=0
    fi

    echo "${interval_rate}|${avg_rate}"
}

scan_log_metrics() {
    python3 - "$LOG" "$METRICS_STATE" <<'PY'
import re
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
metrics_path = Path(sys.argv[2])

def load_metrics():
    data = {
        "log": log_path.name,
        "last_line": 0,
        "fed": 0,
        "total": 0,
        "resolved": 0,
        "grok_queued": 0,
        "matches": 0,
        "census_calls": 0,
    }
    if metrics_path.exists():
        for line in metrics_path.read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in data:
                if key == "log":
                    data[key] = value
                else:
                    data[key] = int(value or 0)
    return data

def save_metrics(data):
    metrics_path.write_text(
        "\n".join(
            f"{key}={value}"
            for key, value in (
                ("log", data["log"]),
                ("last_line", data["last_line"]),
                ("fed", data["fed"]),
                ("total", data["total"]),
                ("resolved", data["resolved"]),
                ("grok_queued", data["grok_queued"]),
                ("matches", data["matches"]),
                ("census_calls", data["census_calls"]),
            )
        )
        + "\n"
    )

def ic(value: str) -> int:
    return int(value.replace(",", ""))

data = load_metrics()
if data["log"] != log_path.name:
    data = {
        "log": log_path.name,
        "last_line": 0,
        "fed": 0,
        "total": 0,
        "resolved": 0,
        "grok_queued": 0,
        "matches": 0,
        "census_calls": 0,
    }

if not log_path.exists():
    save_metrics(data)
    print(
        f"{data['fed']}|{data['total']}|{data['resolved']}|"
        f"{data['grok_queued']}|{data['matches']}|{data['census_calls']}|{data['last_line']}"
    )
    sys.exit(0)

fed_re = re.compile(r"→ ([\d,]+)/([\d,]+) fed")
grok_re = re.compile(r"grok_pending batch=(\d+)")
pending_api_re = re.compile(r"pending_api batch=(\d+)")
match_re = re.compile(r"batch=(\d+) matched=(\d+)/(\d+)")
census_call_re = re.compile(
    r"\[geolocate_census\] census call stage=(\w+) batch=(\d+) matched=(\d+)/(\d+)"
    r".*?rate=([\d.]+)/hr.*?fed=([\d,]+).*?committed=([\d,]+)"
)
running_re = re.compile(
    r"\[(geolocate_new|geolocate_census|geolocate_api|geolocate_grok)\] running "
    r"(?:census=([\d,]+) census_strip=([\d,]+) preprocess=([\d,]+) "
    r"(?:pending_api=([\d,]+) |)other=([\d,]+) grok_queued=([\d,]+)(?: committed=([\d,]+))?|"
    r"preprocess=([\d,]+) other=([\d,]+) grok_queued=([\d,]+)(?: committed=([\d,]+))?|"
    r"grok_match=([\d,]+) grok_fail=([\d,]+)(?: committed=([\d,]+))?)"
)

with log_path.open("r", errors="replace") as handle:
    for line_no, line in enumerate(handle, start=1):
        if line_no <= data["last_line"]:
            continue

        fed_match = fed_re.search(line)
        if fed_match:
            data["fed"] = max(data["fed"], ic(fed_match.group(1)))
            data["total"] = max(data["total"], ic(fed_match.group(2)))

        grok_match = grok_re.search(line)
        if grok_match:
            queued = int(grok_match.group(1))
            data["grok_queued"] += queued
            data["resolved"] += queued

        pending_api_match = pending_api_re.search(line)
        if pending_api_match:
            queued = int(pending_api_match.group(1))
            data["resolved"] += queued

        batch_match = match_re.search(line)
        if batch_match and "grok_pending" not in line and "census call" not in line:
            matched = int(batch_match.group(2))
            if matched > 0:
                data["matches"] += matched
                data["resolved"] += matched

        census_call_match = census_call_re.search(line)
        if census_call_match and census_call_match.group(1) == "census":
            data["census_calls"] += 1
            matched = int(census_call_match.group(3))
            data["matches"] += matched
            data["resolved"] += matched
            data["fed"] = max(data["fed"], ic(census_call_match.group(6)))
            data["resolved"] = max(data["resolved"], ic(census_call_match.group(7)))

        running_match = running_re.search(line)
        if running_match:
            step = running_match.group(1)
            if step == "geolocate_grok":
                resolved = ic(running_match.group(12) or "0") + ic(running_match.group(13) or "0")
            elif step == "geolocate_api":
                resolved = sum(ic(running_match.group(idx) or "0") for idx in (9, 10, 11))
            else:
                resolved = sum(ic(running_match.group(idx) or "0") for idx in (2, 3, 4, 5, 6, 7))
            data["resolved"] = max(data["resolved"], resolved)

        data["last_line"] = line_no

save_metrics(data)
print(
    f"{data['fed']}|{data['total']}|{data['resolved']}|"
    f"{data['grok_queued']}|{data['matches']}|{data['census_calls']}|{data['last_line']}"
)
PY
}

get_etsecs() {
    local pid=$1
    local start start_epoch now_epoch
    start=$(ps -p "$pid" -o lstart= | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    start_epoch=$(date -j -f "%a %b %d %T %Y" "$start" "+%s")
    now_epoch=$(date "+%s")
    echo $((now_epoch - start_epoch))
}

sleep_until_next() {
    local elapsed=$1
    local m
    for m in "${MILESTONES[@]}"; do
        if (( elapsed < m )); then
            echo $((m - elapsed))
            return
        fi
    done
    local next=$(( ((elapsed / 1800) + 1) * 1800 ))
    echo $((next - elapsed))
}

snapshot() {
    local ts elapsed pid etsecs wal last_batch
    local recent progress census save_err checkpoint status_counts
    local total fed processed remaining pct drain metric_label
    local resolved committed in_flight grok_queued matches
    local interval_rate avg_rate progress_str
    local finish_eta cap_eta pct_str phase_str backlog
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [[ -z "$pid" ]] || ! ps -p "$pid" >/dev/null 2>&1; then
        echo "[$ts] NOT RUNNING (pid=${pid:-none})" >> "$OUT"
        return 1
    fi
    elapsed=$(ps -p "$pid" -o etime= | tr -d ' ')
    etsecs=$(get_etsecs "$pid")
    now_epoch=$(date "+%s")

    IFS='|' read -r fed total resolved grok_queued matches census_calls _scan_lines \
        <<< "$(scan_log_metrics)"
    fed=$(as_int "${fed:-0}")
    total=$(as_int "${total:-0}")
    resolved=$(as_int "${resolved:-0}")
    grok_queued=$(as_int "${grok_queued:-0}")
    matches=$(as_int "${matches:-0}")
    census_calls=$(as_int "${census_calls:-0}")

    # Only scan recent log tail for detail lines — incremental metrics drive ETA.
    recent=$(/usr/bin/tail -c 2000000 "$LOG" 2>/dev/null || true)
    census=$(echo "$recent" | /usr/bin/grep -F '[geolocate_census] census call ' | /usr/bin/tail -1 || true)
    if [[ -z "$census" ]]; then
        census=$(echo "$recent" | /usr/bin/grep -E '\[geolocate_(new|census|api|grok)\] running' | /usr/bin/tail -1 || true)
    fi
    checkpoint=$(echo "$recent" | /usr/bin/grep 'FORCE CHECKPOINT at' | /usr/bin/tail -1 || true)
    status_counts=$(echo "$recent" | /usr/bin/grep 'GEOCODING_STATUS_COUNTS' | /usr/bin/tail -1 || true)

    IFS='|' read -r _tail_total _tail_fed _tail_processed remaining pct drain metric_label \
        _tail_resolved committed in_flight \
        <<< "$(parse_progress "$recent")"
    if (( total == 0 )); then
        total=$(as_int "${_tail_total:-0}")
    fi
    if (( fed == 0 )); then
        fed=$(as_int "${_tail_fed:-0}")
    fi
    committed=$(as_int "${committed:-0}")
    if (( resolved < committed )); then
        resolved=$committed
    fi
    if (( fed > resolved )); then
        in_flight=$(( fed - resolved ))
    else
        in_flight=$(as_int "${in_flight:-0}")
    fi

    IFS='|' read -r interval_rate avg_rate \
        <<< "$(compute_rates "$now_epoch" "$resolved" "$etsecs" "$drain")"

    if [[ -n "$census" ]]; then
        progress="$census"
        save_err=$(echo "$census" | /usr/bin/grep -oE 'save_err=[0-9,]+' || echo "save_err=?")
    elif [[ -n "$checkpoint" ]]; then
        progress="[drain] $checkpoint"
        save_err="save_err=0"
        drain=1
    else
        progress="(no recent running line — using incremental log metrics)"
        save_err=$(echo "$recent" | /usr/bin/grep -oE 'save_err=[0-9,]+' | /usr/bin/tail -1 || echo "save_err=?")
    fi

    if (( total > 0 )); then
        remaining=$(( total - resolved ))
        (( remaining < 0 )) && remaining=0
        pct=$(( resolved * 10000 / total ))
        pct_whole=$(( pct / 100 ))
        pct_frac=$(( pct % 100 ))
        if (( pct_frac >= 10 )); then
            pct_str="${pct_whole}.${pct_frac}%"
        else
            pct_str="${pct_whole}%"
        fi
        finish_eta=$(fmt_eta "$remaining" "$interval_rate" "$now_epoch")
        if (( drain == 1 )); then
            phase_str="drain"
        else
            phase_str="feed"
        fi
        if (( drain == 0 && in_flight > 0 )); then
            backlog=$in_flight
            cap_eta=$(fmt_eta "$backlog" "$interval_rate" "$now_epoch")
        else
            cap_eta="n/a"
        fi
        if (( drain == 0 )); then
            progress_str="progress: fed=$(fmt_num "$fed")/$(fmt_num "$total") resolved=$(fmt_num "$resolved") (matches=$(fmt_num "$matches") grok_q=$(fmt_num "$grok_queued")) ${pct_str} in_flight≈$(fmt_num "$in_flight") rate=$(fmt_rate_hr "$interval_rate") avg=$(fmt_rate_hr "$avg_rate") finish=${finish_eta} cap_clear=${cap_eta} phase=${phase_str}"
        else
            progress_str="progress: resolved=$(fmt_num "$resolved")/$(fmt_num "$total") (${pct_str}) remaining=$(fmt_num "$remaining") rate=$(fmt_rate_hr "$interval_rate") avg=$(fmt_rate_hr "$avg_rate") finish=${finish_eta} phase=${phase_str}"
        fi
    else
        progress_str="progress: (total unknown — check log)"
    fi

    last_batch=$(echo "$recent" | /usr/bin/grep -F 'Last batch sent' | /usr/bin/tail -1 || true)
    wal=$(ls -lah /Volumes/Data/final/irs990.duckdb.wal 2>/dev/null | awk '{print $5}' || echo "none")
    echo "[$ts] pid=$pid elapsed=$elapsed (${etsecs}s) wal=$wal $save_err" >> "$OUT"
    echo "[$ts]   $progress_str" >> "$OUT"
    echo "[$ts]   detail: $progress" >> "$OUT"
    if [[ -n "$status_counts" ]]; then
        echo "[$ts]   geocoding: $status_counts" >> "$OUT"
    fi
    if [[ -n "${census_calls:-}" ]] && (( census_calls > 0 )); then
        echo "[$ts]   census_api_calls=$census_calls" >> "$OUT"
    fi
    if [[ -n "$last_batch" ]]; then
        echo "[$ts] note: $last_batch" >> "$OUT"
    fi

    last_line=$(cat "$STATE" 2>/dev/null || echo 0)
    total_lines=$(wc -l < "$LOG" 2>/dev/null | tr -d ' ' || echo 0)
    if (( total_lines > last_line )); then
        # Cap scan window — never re-read more than 50k lines
        scan_from=$(( total_lines > last_line + 50000 ? total_lines - 50000 : last_line + 1 ))
        new_art=$(/usr/bin/tail -n +"$scan_from" "$LOG" | /usr/bin/grep -c -F 'Corrupted ART' || true)
        if (( new_art > 0 )); then
            echo "[$ts] ALERT: $new_art new Corrupted ART line(s) since last check" >> "$OUT"
        fi
        echo "$total_lines" > "$STATE"
    fi
    return 0
}

LAST_PID_FILE=geolocate_monitor.lastpid
current_pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
previous_pid=$(cat "$LAST_PID_FILE" 2>/dev/null || echo "")
if [[ -n "$current_pid" && "$current_pid" != "$previous_pid" ]]; then
    rm -f "$PROGRESS_STATE"
fi
if [[ -n "$current_pid" ]]; then
    echo "$current_pid" > "$LAST_PID_FILE"
fi

echo "=== geolocate monitor started $(date) ===" >> "$OUT"
pending_total=$(/usr/bin/head -n 200 "$LOG" 2>/dev/null \
    | /usr/bin/grep -m1 'pending addresses' \
    | /usr/bin/sed -n 's/.*for \([0-9,]*\) pending addresses.*/\1/p' || true)
if [[ -n "$pending_total" ]]; then
    as_int "$pending_total" > "$STATE.pending"
fi
snapshot || exit 0

while true; do
    pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [[ -z "$pid" ]] || ! ps -p "$pid" >/dev/null 2>&1; then
        snapshot
        echo "=== geolocate monitor stopped $(date) — process exited ===" >> "$OUT"
        exit 0
    fi
    etsecs=$(get_etsecs "$pid")
    interval=$(sleep_until_next "$etsecs")
    hrs=$((etsecs / 3600))
    mins=$(((etsecs % 3600) / 60))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] next check in ${interval}s (now ${hrs}h${mins}m)" >> "$OUT"
    sleep "$interval"
    snapshot || exit 0
done