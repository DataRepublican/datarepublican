#!/usr/bin/env python3
"""
state_research.py — Count pass clusters by US state for each report focus.

Used to size per-state report pages:
  show_n(state) = min(100, max(1, pass_clusters // 10))   # ≤10%, at least 1 if any

Writes JSON suitable for heatmap + report generators.

Usage:
  python state_research.py --db-path /Volumes/Data/final/irs990.duckdb
  python state_research.py --focuses dot,medicare,fec --out data/state_cluster_research.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
DEFAULT_OUT = SCRIPT_DIR / "reports" / "state_cluster_research.json"

US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD "
    "MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC "
    "SD TN TX UT VT VA WA WV WI WY DC PR VI GU AS MP"
).split()

# Focus definitions: SQL predicate on Addresses.address_type
FOCUSES: dict[str, dict[str, Any]] = {
    # min_* kept for CLI/compat; admission is focus_n > 0, then rank + show_n/max.
    "dot": {
        "label": "DOT carriers",
        "type_sql": "address_type = 'dot_carrier_phy'",
        "min_multi": 0,
        "min_focus": 0,
    },
    "medicare": {
        "label": "Medicare / NPPES",
        "type_sql": "address_type IN ('nppes_practice', 'nppes_mailing')",
        "min_multi": 0,
        "min_focus": 0,
    },
    "fec": {
        "label": "FEC",
        "type_sql": "address_type LIKE 'fec%'",
        "min_multi": 0,
        "min_focus": 0,
    },
    "contractor": {
        "label": "Contractors",
        "type_sql": "address_type = 'contractor'",
        "min_multi": 0,
        "min_focus": 0,
    },
    "grants": {
        "label": "NGO Grants (incoming)",
        "type_sql": "address_type = 'grant'",
        "min_multi": 0,
        "min_focus": 0,
    },
    "grants_out": {
        "label": "NGO Grants (outgoing)",
        "type_sql": "address_type = 'charity'",
        "min_multi": 0,
        "min_focus": 0,
    },
    "usg": {
        "label": "USG NGO Funding",
        "type_sql": "address_type = 'charity'",
        "min_multi": 0,
        "min_focus": 0,
    },
}


def show_cap(pass_clusters: int) -> int:
    """min(100, 10%) with at least 1 when the state has any passing cluster."""
    if pass_clusters <= 0:
        return 0
    return min(100, max(1, pass_clusters // 10))


def open_db(path: str, retries: int = 8, delay: float = 5.0) -> duckdb.DuckDBPyConnection:
    last = None
    for i in range(retries):
        try:
            return duckdb.connect(
                path,
                read_only=True,
                config={"memory_limit": "8GB", "threads": "2"},
            )
        except Exception as e:
            last = e
            print(f"  open retry {i+1}/{retries}: {e}", flush=True)
            time.sleep(delay)
    # fallback geolocate twin
    geo = path + ".geolocate" if not path.endswith(".geolocate") else path
    if geo != path and os.path.exists(geo):
        print(f"  trying fallback {geo}", flush=True)
        return duckdb.connect(geo, read_only=True, config={"memory_limit": "8GB", "threads": "2"})
    raise last  # type: ignore


def research_focus(con: duckdb.DuckDBPyConnection, focus: str) -> dict[str, Any]:
    cfg = FOCUSES[focus]
    type_sql = cfg["type_sql"]
    min_multi = cfg["min_multi"]
    min_focus = cfg["min_focus"]

    # Address-slice clusters: one row per (state, canonical_address)
    sql = f"""
    WITH base AS (
        SELECT
            UPPER(TRIM(state)) AS st,
            TRIM(canonical_address) AS cluster_key,
            COUNT(*)::BIGINT AS total_rows,
            COUNT(DISTINCT address_type)::BIGINT AS multi,
            SUM(CASE WHEN {type_sql} THEN 1 ELSE 0 END)::BIGINT AS focus_n
        FROM Addresses
        WHERE state IS NOT NULL
          AND LENGTH(TRIM(state)) = 2
          AND canonical_address IS NOT NULL
          AND TRIM(canonical_address) != ''
        GROUP BY 1, 2
    ),
    scored AS (
        SELECT *
        FROM base
        WHERE multi >= {int(min_multi)} OR focus_n >= {int(min_focus)}
    )
    SELECT
        st,
        COUNT(*)::BIGINT AS pass_clusters,
        SUM(focus_n)::BIGINT AS focus_rows,
        SUM(total_rows)::BIGINT AS address_rows,
        MAX(focus_n)::BIGINT AS max_focus_in_cluster
    FROM scored
    GROUP BY st
    ORDER BY pass_clusters DESC
    """
    print(f"  researching {focus} (multi>={min_multi} OR focus>={min_focus})...", flush=True)
    t0 = time.time()
    rows = con.execute(sql).fetchall()
    elapsed = time.time() - t0
    states = []
    total_pass = 0
    total_pages = 0
    for st, pass_c, focus_rows, addr_rows, max_f in rows:
        if not st or st not in US_STATES:
            continue
        cap = show_cap(int(pass_c))
        total_pass += int(pass_c)
        total_pages += cap
        states.append(
            {
                "state": st,
                "pass_clusters": int(pass_c),
                "focus_rows": int(focus_rows or 0),
                "address_rows": int(addr_rows or 0),
                "max_focus_in_cluster": int(max_f or 0),
                "show_n": cap,  # min(100, 10%)
            }
        )
    # ensure all states present (0s) for heatmap completeness
    have = {s["state"] for s in states}
    for st in US_STATES:
        if st not in have:
            states.append(
                {
                    "state": st,
                    "pass_clusters": 0,
                    "focus_rows": 0,
                    "address_rows": 0,
                    "max_focus_in_cluster": 0,
                    "show_n": 0,
                }
            )
    states.sort(key=lambda s: (-s["pass_clusters"], s["state"]))
    return {
        "focus": focus,
        "label": cfg["label"],
        "criteria": {"min_multi": min_multi, "min_focus": min_focus, "slice": "address"},
        "elapsed_s": round(elapsed, 1),
        "total_pass_clusters": total_pass,
        "total_detail_pages": total_pages,
        "vs_flat_50x100": 5000,
        "states": states,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Cluster counts by state for report sizing")
    p.add_argument("--db-path", default=os.environ.get("IRS990_DB_PATH", DEFAULT_DB))
    p.add_argument(
        "--focuses",
        default="dot,medicare,fec,contractor,grants",
        help="Comma-separated focus keys",
    )
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args()

    focuses = [f.strip() for f in args.focuses.split(",") if f.strip()]
    for f in focuses:
        if f not in FOCUSES:
            raise SystemExit(f"Unknown focus {f!r}; choose from {list(FOCUSES)}")

    print(f"Opening {args.db_path}...", flush=True)
    con = open_db(args.db_path)
    try:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "db_path": args.db_path,
            "cap_rule": "show_n = min(100, max(1, pass_clusters // 10))",
            "focuses": {},
        }
        for f in focuses:
            payload["focuses"][f] = research_focus(con, f)
            fr = payload["focuses"][f]
            print(
                f"  {f}: pass={fr['total_pass_clusters']:,} "
                f"pages@{fr['total_detail_pages']:,} "
                f"({fr['elapsed_s']}s)",
                flush=True,
            )
            # print top 10 states
            for s in fr["states"][:10]:
                if s["pass_clusters"] == 0:
                    break
                print(
                    f"    {s['state']}: pass={s['pass_clusters']:,} → show {s['show_n']}",
                    flush=True,
                )
    finally:
        con.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
