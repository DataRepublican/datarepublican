#!/usr/bin/env python3
"""
Overnight geolocate_grok loop: wait → mine failures → add patterns → test → kick next iter.

Run:
  nohup python3 -u geolocate_grok_overnight_loop.py >> geolocate_grok_overnight.log 2>&1 &
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

ROOT = Path(__file__).resolve().parent
DB_PATH = "/Volumes/Data/final/irs990.duckdb"
FINAL_DIR = "/Volumes/Data/final"
PATTERNS_PATH = ROOT / "geocoding_patterns.json"
STATE_PATH = ROOT / "geolocate_grok_overnight_state.json"
LOCK_PATH = ROOT / "geolocate_grok_overnight.lock"
PID_PATH = ROOT / "geolocate.pid"

STOP_HOUR = 17  # local time — stop at 5pm
MAX_ITERS = 120
POLL_SEC = 30
DEFAULT_BATCH = 4000

# (cluster_name, pending_sql_like, regex, colocator, min_pending_to_add)
AUTO_PATTERN_RULES: List[Tuple[str, str, str, str, int]] = [
    ("drawer", "%drawer%", r"(?i)\bdrawer\s+[a-z0-9#]+", "PO:{box}:{zip}", 50),
    ("psc", "%psc %", r"(?i)\bpsc\s+\d+", "MILITARY:PSC:{zip}", 20),
    ("remittance", "%remittance dr%", r"(?i)remit(?:tance)?\s*(?:dr|drive)", "PO:MAIL", 20),
    ("mail_location", "%mail location%", r"(?i)mail\s+location\s+\d+", "PO:MAIL", 10),
    ("treasury_ctr", "%treasury ctr%", r"(?i)treasury\s*ctr", "PO:MAIL", 10),
    ("solutions_ctr", "%solutions ctr%", r"(?i)solutions\s*(?:center|ctr)", "PO:MAIL", 10),
    ("housecalls", "%housecalls%", r"(?i)housecalls\s+only", "BOGUS:{zip}", 5),
    ("sp_fr", "%sp-fr-%", r"(?i)\bsp-fr-", "DEPT:{zip}", 5),
    ("crdamc", "%crdamc%", r"(?i)\bcrdamc\b", "DEPT:{zip}", 5),
    ("mchj", "%mchj-%", r"(?i)\bmchj-", "DEPT:{zip}", 10),
    ("dumc", "%dumc %", r"(?i)^dumc\s+\d+", "UNIV:{zip}", 10),
    ("athletic_dept", "%athletic department%", r"(?i)^athletic\s+department\b", "DEPT:{zip}", 5),
    ("intersection_amp", "%&%", r"(?i)^(?!.*\b\d{3,}\b).*\b&\b", "PARTIAL:{zip}", 100),
    ("all_over_state", "%all over the state%", r"(?i)all\s+over\s+the\s+state", "BOGUS:{zip}", 5),
    ("wiesbaden", "%wiesbaden%", r"(?i)\bwiesbaden\b", "FA:INTL", 5),
    ("overseas_army", "%us army%wiesbaden%", r"(?i)\b(usnh|us\s+army)\b.*\b(italy|germany|japan|okinawa|yokosuka|wiesbaden)\b", "MILITARY:OVERSEAS:{zip}", 5),
]


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[overnight {ts}] {msg}"
    print(line, flush=True)


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        with STATE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    return {
        "iter": 12,
        "batch_size": DEFAULT_BATCH,
        "history": [],
        "last_iter_start": None,
        "victory_declared": False,
    }


def save_state(state: Dict[str, Any]) -> None:
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def should_stop() -> bool:
    """Stop once local time reaches STOP_HOUR (default 5pm)."""
    return datetime.now().hour >= STOP_HOUR


def fetch_db_counts() -> Dict[str, int]:
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        rows = con.execute("""
            SELECT geocoding_status, COUNT(*)::BIGINT
            FROM Geocoding
            WHERE geocoding_status IN (
                'pending_api', 'Match:Grok-4', 'Match:PatternOwners',
                'grok:UNKN', 'grok:VAGUE', 'grok:NOTA', 'grok:AMBIG', 'grok_pending'
            )
            GROUP BY 1
        """).fetchall()
        con.close()
        return {status: int(count) for status, count in rows}
    except Exception as e:
        return {"_error": str(e)}


def _rolling_preprocess_pct(history: List[Dict[str, Any]], n: int = 5) -> Optional[float]:
    recent = [
        h["preprocess"] / h["batch"] * 100
        for h in history[-n:]
        if h.get("ok") and h.get("preprocess") is not None and h.get("batch")
    ]
    return sum(recent) / len(recent) if recent else None


def log_rich_iter_block(
    stats: Dict[str, Any],
    state: Dict[str, Any],
    mine_info: Optional[Dict[str, Any]] = None,
) -> None:
    """Multi-line status snapshot after each successful iter."""
    it = stats.get("iter", "?")
    batch = stats.get("batch") or stats.get("batch_size") or 0
    pre = stats.get("preprocess", 0)
    surv = stats.get("survivors", 0)
    matched = stats.get("matched", 0)
    classified = stats.get("classified", 0)
    pre_pct = (pre / batch * 100) if batch else 0
    grok_pct = (matched / surv * 100) if surv else 0

    ok_hist = [h for h in state.get("history", []) if h.get("ok")]
    session_iters = len(ok_hist)
    session_rows = sum(h.get("applied", h.get("batch", 0)) for h in ok_hist)
    roll5 = _rolling_preprocess_pct(ok_hist, 5)

    lines = [
        f"════ ITER-{it} SUMMARY ════",
        f"  batch={batch:,}  preprocess={pre:,} ({pre_pct:.1f}%)  survivors={surv:,}",
        f"  grok: matched={matched:,} ({grok_pct:.1f}%)  classified={classified:,}",
    ]
    if mine_info:
        clusters = mine_info.get("clusters", {})
        top = ", ".join(f"{k}={v}" for k, v in sorted(clusters.items(), key=lambda x: -x[1])[:4])
        added = mine_info.get("patterns_added") or []
        lines.append(f"  mined: {mine_info.get('failures', 0)} failures  clusters: {top}")
        if added:
            lines.append(f"  patterns_added: {', '.join(added)}")

    counts = fetch_db_counts()
    if "_error" not in counts:
        pending = counts.get("pending_api", 0)
        grok4 = counts.get("Match:Grok-4", 0)
        owners = counts.get("Match:PatternOwners", 0)
        grok_fail = sum(counts.get(k, 0) for k in counts if k.startswith("grok:"))
        lines.append(
            f"  db: pending_api={pending:,}  Grok-4={grok4:,}  PatternOwners={owners:,}  grok:*={grok_fail:,}"
        )
    else:
        lines.append(f"  db: (locked — pipeline busy)")

    trend = ""
    if roll5 is not None:
        trend = f"  rolling5 preprocess={roll5:.1f}%"
    lines.append(
        f"  session: {session_iters} ok iters  ~{session_rows:,} rows applied"
        + (f"  |{trend}" if trend else "")
    )
    lines.append(
        f"  next: iter-{state.get('iter')} batch={state.get('batch_size', batch):,}"
        f"  stop_at={STOP_HOUR}:00"
    )
    lines.append("═" * 28)
    for line in lines:
        log(line)


def parse_iter_log(log_path: Path) -> Dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    stats: Dict[str, Any] = {"ok": False}
    m = re.search(r"\[geolocate_grok\] preprocess matched=(\d+) survivors=(\d+)/(\d+)", text)
    if m:
        stats["preprocess"] = int(m.group(1))
        stats["survivors"] = int(m.group(2))
        stats["batch"] = int(m.group(3))
    m = re.search(
        r"\[geolocate_grok\] batch \d+ done matched=(\d+) classified=(\d+) total_applied=(\d+)",
        text,
    )
    if m:
        stats["matched"] = int(m.group(1))
        stats["classified"] = int(m.group(2))
        stats["applied"] = int(m.group(3))
        stats["ok"] = "SUMMARY" in text and "Traceback" not in text
    m = re.search(r"Completed step: geolocate_grok", text)
    if m:
        stats["completed"] = True
    if "Traceback" in text or "ERROR" in text.split("Completed step")[-1] if "Completed step" in text else text:
        stats["error"] = "Traceback" in text
    return stats


def process_running(pid: int) -> bool:
    """True only if pid exists and is not a zombie (os.kill misses zombies)."""
    r = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return False
    stat = (r.stdout or "").strip()
    return bool(stat) and "Z" not in stat


def wait_for_pid(pid: int, timeout_sec: int = 7200) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not process_running(pid):
            return True
        time.sleep(POLL_SEC)
    return False


def kick_iter(iter_num: int, batch_size: int) -> Tuple[int, Path]:
    log_path = ROOT / f"geolocate_step_20260708_grok_iter{iter_num}.log"
    env = os.environ.copy()
    env.pop("GEOCODING_GROK_TEST_SET", None)
    cmd = [
        sys.executable, "-u", "irs990processor.py",
        "--step", "geolocate_grok",
        "--max-files", str(batch_size),
        "--final-dir", FINAL_DIR,
        "--db-path", DB_PATH,
        "--db-threads", "1",
        "--nostats", "-v",
    ]
    log(f"Kicking iter-{iter_num} batch={batch_size:,} → {log_path.name}")
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid, log_path


def export_failures(since: str, out_path: Path) -> int:
    import csv

    con = duckdb.connect(DB_PATH, read_only=True)
    rows = con.execute(
        """
        SELECT geocoding_id, geocoding_status, canonical_address, normalized_address
        FROM Geocoding
        WHERE geocoding_status LIKE 'grok:%'
          AND last_attempt >= ?
        ORDER BY geocoding_status, canonical_address
        """,
        [since],
    ).fetchall()
    con.close()

    def parse_norm(norm: Any) -> dict:
        try:
            return json.loads(norm) if isinstance(norm, str) else (norm or {})
        except json.JSONDecodeError:
            return {}

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["geocoding_id", "status", "canonical_address", "street", "city", "state", "zip"])
        for gid, status, ca, norm in rows:
            d = parse_norm(norm)
            w.writerow([
                gid, status, ca,
                d.get("street", ""), d.get("city", ""), d.get("state", ""), d.get("zip", ""),
            ])
    return len(rows)


def cluster_failures(rows_path: Path) -> Dict[str, int]:
    import csv

    clusters: Dict[str, int] = defaultdict(int)
    if not rows_path.exists():
        return {}
    with rows_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            street = (row.get("street") or "").upper()
            status = row.get("status", "")
            code = status.split(":")[-1] if ":" in status else status
            if re.search(r"\bAPO\b|\bFPO\b|\bDPO\b", street):
                clusters["apo"] += 1
            elif re.search(r"DRAWER|PO BOX", street):
                clusters["drawer"] += 1
            elif re.search(r"PSC\s+\d", street):
                clusters["psc"] += 1
            elif re.search(r"REMITTANCE|MAIL SERVICE|MAIL LOCATION", street):
                clusters["mail_center"] += 1
            elif code == "NOTA":
                clusters["nota"] += 1
            elif code == "VAGUE":
                clusters["vague"] += 1
            elif code == "AMBIG":
                clusters["ambig"] += 1
            else:
                clusters["unkn_street"] += 1
    return dict(clusters)


def patterns_contain(regex: str) -> bool:
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    needle = regex.replace("(?i)", "").lower()
    for p in data.get("patterns", []):
        r = (p.get("regex") or "").lower()
        if needle in r or r in needle:
            return True
        for sub in p.get("patterns", []):
            r = (sub.get("regex") or "").lower()
            if needle in r or r in needle:
                return True
    return False


def add_pattern_to_fraud_source(regex: str, colocator: str) -> bool:
    if patterns_contain(regex):
        return False
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    for p in data.get("patterns", []):
        if p.get("name") == "fraud_source_addresses":
            p.setdefault("patterns", []).append({
                "regex": regex,
                "colocator": colocator,
                "status": "owners",
                "action": "match",
            })
            PATTERNS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            return True
    return False


def mine_and_apply_patterns(iter_num: int, since: str) -> Dict[str, Any]:
    out = ROOT / f"failures_iter{iter_num}_mined.tsv"
    n = export_failures(since, out)
    clusters = cluster_failures(out)
    log(f"iter-{iter_num} mined {n} failures → {out.name} clusters={clusters}")

    added: List[str] = []
    con = duckdb.connect(DB_PATH, read_only=True)
    for name, like, regex, colocator, min_pending in AUTO_PATTERN_RULES:
        pending = con.execute(
            "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status='pending_api' AND LOWER(canonical_address) LIKE ?",
            [like.lower()],
        ).fetchone()[0]
        if pending >= min_pending and not patterns_contain(regex):
            if add_pattern_to_fraud_source(regex, colocator):
                added.append(f"{name}(pending={pending})")
                log(f"  added pattern: {name} pending={pending}")
    con.close()
    return {"failures": n, "clusters": clusters, "patterns_added": added}


def run_tests() -> bool:
    log("Running pytest preprocess/pattern tests...")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test_preprocess_bogus.py", "test_normalized_patterns.py", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        log(f"TEST FAIL:\n{r.stdout}\n{r.stderr}")
        return False
    log(r.stdout.strip() or "tests passed")
    return True


def choose_batch_size(stats: Dict[str, Any], current: int) -> int:
    classified = stats.get("classified", 300)
    preprocess = stats.get("preprocess", 0)
    batch = stats.get("batch", current)
    pct = (preprocess / batch * 100) if batch else 0

    if classified < 50:
        new = min(current * 2, 8000)
        reason = f"classified={classified}<50 → double"
    elif classified > 500:
        new = max(current // 2, 1000)
        reason = f"classified={classified}>500 → halve"
    elif pct > 25 and classified > 400:
        new = max(current // 2, 1000)
        reason = f"preprocess={pct:.0f}% + classified={classified} → halve"
    else:
        new = current
        reason = f"classified={classified} sweet spot, preprocess={pct:.1f}% → hold"

    log(f"Batch sizing: {current:,} → {new:,} ({reason})")
    return new


def acquire_lock() -> bool:
    try:
        LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def main() -> int:
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text().strip())
            os.kill(old_pid, 0)
            log(f"Another overnight loop running (pid {old_pid}) — exit")
            return 0
        except (OSError, ValueError):
            LOCK_PATH.unlink(missing_ok=True)

    if not acquire_lock():
        log("Could not acquire lock")
        return 1

    state = load_state()
    if state.get("victory_declared"):
        log(
            "Victory already declared — bulk Grok loop stopped. "
            "Use declare_geocoding_victory.py --undo to re-enable, or run geolocate_grok manually "
            "with GEOCODING_GROK_MIN_ADDRESS_COUNT for high-value rows only."
        )
        LOCK_PATH.unlink(missing_ok=True)
        return 0

    log(f"Overnight loop starting iter={state['iter']} batch={state['batch_size']:,}")

    # If a pipeline is still running, wait for it first
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            log(f"Waiting for existing pipeline pid={pid}")
            wait_for_pid(pid)
        except (ValueError, OSError):
            pass

    while state["iter"] <= MAX_ITERS:
        if should_stop():
            log(f"Stop hour ({STOP_HOUR}:00) reached — done for the night")
            break

        iter_num = state["iter"]
        batch_size = state["batch_size"]

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["last_iter_start"] = started_at
        pid, log_path = kick_iter(iter_num, batch_size)
        save_state(state)

        if not wait_for_pid(pid, timeout_sec=3 * 3600):
            log(f"TIMEOUT waiting for iter-{iter_num} pid={pid}")
            break

        stats = parse_iter_log(log_path)
        stats["iter"] = iter_num
        stats["batch_size"] = batch_size
        stats["started"] = started_at
        stats["finished"] = datetime.now().isoformat()
        state["history"].append(stats)
        state["iter"] = iter_num + 1
        save_state(state)

        if not stats.get("ok"):
            log(f"iter-{iter_num} FAILED — retrying in 60s ({log_path.name}; active_batch may resume)")
            state["iter"] = iter_num
            save_state(state)
            time.sleep(60)
            continue

        since = started_at
        mine_info = mine_and_apply_patterns(iter_num, since)
        if mine_info["patterns_added"]:
            if not run_tests():
                log("Tests failed after pattern add — reverting not implemented, continuing with existing patterns")
        stats["mine"] = mine_info
        state["batch_size"] = choose_batch_size(stats, batch_size)
        save_state(state)
        log_rich_iter_block(stats, state, mine_info=mine_info)
        time.sleep(5)

    log(f"Overnight loop finished. History: {len(state.get('history', []))} iters")
    LOCK_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())