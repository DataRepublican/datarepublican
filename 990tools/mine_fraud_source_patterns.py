#!/usr/bin/env python3
"""Mine preprocess patterns from pending_api failures, broken down by address source."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import duckdb

from constants import DEFAULT_FINAL_DIR, GEOCODING_STATUS_PENDING_API

US_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "PR", "VI", "GU", "AS", "MP",
})

# Candidate patterns — vetted subset is in geocoding_patterns.json (fraud_source_addresses)
PATTERN_CANDIDATES: List[Dict] = [
    {
        "id": "placeholder_street_prefix",
        "family": "incomplete",
        "label": "Placeholder street (Unknown/None/N/A)",
        "regex": r"(?i)^(unknown|none|n/a|na|tbd|not available|general delivery)\s*,",
        "sources": ["dot_carrier_phy", "dot_carrier_mail", "nppes_practice"],
    },
    {
        "id": "fec_vendor_city_only",
        "family": "fec_vendor",
        "label": "FEC vendor city-only (no street number/name)",
        "regex": r"(?i)^[^,\d]+,\s*[A-Za-z]{2},\s*\d{5}(?:-\d{4})?$",
        "sources": ["fec_operating_expenditure", "fec_committee_transaction", "fec_candidate_spending"],
    },
    {
        "id": "foreign_canada_province",
        "family": "foreign",
        "label": "Canadian province + 3-digit postal fragment",
        "regex": r"(?i),\s*(?:Ab|Bc|Mb|Nb|Nl|Ns|Nt|Nu|On|Pe|Qc|Sk|Yt)\s*,\s*\d{3}\s*$",
        "sources": ["dot_carrier_phy", "dot_carrier_mail"],
    },
    {
        "id": "foreign_mexico_border",
        "family": "foreign",
        "label": "Mexico border city",
        "regex": r"(?i),\s*(?:Tijuana|Mexicali|Nogales|Ciudad Juarez|Baja California)\b",
        "sources": ["dot_carrier_phy", "dot_carrier_mail"],
    },
    {
        "id": "dot_intersection_only",
        "family": "incomplete",
        "label": "Highway intersection without street number",
        "regex": r"(?i)^(?!.*\b\d{3,}\b).*(?:\b&\b|\band\b).*(?:hwy|highway|interstate|i-\d+)",
        "sources": ["dot_carrier_phy"],
    },
    {
        "id": "nppes_extra_comma_unit",
        "family": "nppes_format",
        "label": "Extra comma-number segment (e.g. DC 228)",
        "regex": r",\s*\d{1,4},\s*[A-Za-z]",
        "sources": ["nppes_practice"],
    },
    {
        "id": "nppes_building_in_street",
        "family": "nppes_format",
        "label": "Building/facility name in street field",
        "regex": r"(?i)\b(?:walker building|medical center|health center|hospital)\b",
        "sources": ["nppes_practice"],
    },
    {
        "id": "actblue_mangled_city",
        "family": "fec_vendor",
        "label": "ActBlue mangled city/state typos",
        "regex": r"(?i)(?:somverille|somervile|omerville|someville|sommerville|cambridge,\s*va)",
        "sources": ["fec_operating_expenditure"],
    },
    {
        "id": "fec_payment_processor_zip",
        "family": "fec_vendor",
        "label": "Known payment-processor lockbox zips",
        "regex": (
            r"(?i)(?:fort lauderdale,\s*fl,\s*3333[46]|dallas,\s*tx,\s*75392|"
            r"las vegas,\s*nv,\s*89199|washington,\s*dc,\s*20066|"
            r"washington,\s*dc,\s*20220|saint louis,\s*mo,\s*6317[95]|"
            r"philadelphia,\s*pa,\s*1917[06]|charlotte,\s*nc,\s*2827[28]|omaha,\s*ne,\s*68172)"
        ),
        "sources": ["fec_operating_expenditure"],
    },
]

FOCUS_SOURCES = [
    "nppes_practice",
    "nppes_mailing",
    "dot_carrier_phy",
    "dot_carrier_mail",
    "fec_operating_expenditure",
    "fec_committee_transaction",
    "fec_candidate_spending",
]


def _is_us_address(addr: str) -> bool:
    m = re.search(r",\s*([A-Za-z]{2}),\s*(\S+)\s*$", addr or "")
    if not m:
        return False
    state, zips = m.group(1).upper(), m.group(2)
    if state not in US_STATES:
        return False
    return bool(re.match(r"^\d{5}", zips))


def load_source_rows(db_path: str) -> Dict[str, List[Tuple[str, int]]]:
    con = duckdb.connect(db_path, read_only=True)
    by_source: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    rows = con.execute(
        """
        SELECT a.address_type, g.canonical_address, COUNT(*) AS c
        FROM Geocoding g
        INNER JOIN Addresses a ON a.geocoding_id = g.geocoding_id
        WHERE g.geocoding_status = ?
          AND g.canonical_address IS NOT NULL
          AND TRIM(g.canonical_address) != ''
        GROUP BY a.address_type, g.canonical_address
        """,
        [GEOCODING_STATUS_PENDING_API],
    ).fetchall()
    con.close()
    for address_type, canon, count in rows:
        by_source[address_type].append((canon, int(count)))
    return by_source


def mine_patterns(by_source: Dict[str, List[Tuple[str, int]]]) -> Dict:
    compiled = [(p, re.compile(p["regex"])) for p in PATTERN_CANDIDATES]
    results = []
    source_totals = {src: sum(c for _, c in rows) for src, rows in by_source.items()}

    for cand, rx in compiled:
        entry = {
            **{k: v for k, v in cand.items() if k != "sources"},
            "coverage": {},
            "samples": [],
        }
        total_weight = 0
        for src in cand.get("sources", FOCUS_SOURCES):
            rows = by_source.get(src, [])
            src_total = source_totals.get(src, 0) or 1
            weight = sum(c for addr, c in rows if rx.search(addr))
            if not weight:
                continue
            entry["coverage"][src] = {
                "weight": weight,
                "pct_of_source": round(100.0 * weight / src_total, 2),
            }
            total_weight += weight
            if len(entry["samples"]) < 5:
                for addr, c in sorted(rows, key=lambda x: -x[1]):
                    if rx.search(addr):
                        entry["samples"].append({"address": addr[:120], "weight": c, "source": src})
                        if len(entry["samples"]) >= 5:
                            break
        entry["total_weight"] = total_weight
        if total_weight:
            results.append(entry)

    # Source-level diagnostics not covered by simple regex
    diagnostics = []
    for src in FOCUS_SOURCES:
        rows = by_source.get(src, [])
        total = source_totals.get(src, 0)
        if not total:
            continue
        non_us = sum(c for addr, c in rows if not _is_us_address(addr))
        suite = sum(
            c for addr, c in rows
            if re.search(r"\b(?:ste|suite|#)\s*\d", addr, re.I)
        )
        diagnostics.append({
            "address_type": src,
            "total_weight": total,
            "non_us_pct": round(100.0 * non_us / total, 2),
            "suite_heavy_pct": round(100.0 * suite / total, 2),
            "note": _source_note(src),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pattern_candidates": sorted(results, key=lambda x: -x["total_weight"]),
        "source_diagnostics": diagnostics,
    }


def _source_note(address_type: str) -> str:
    notes = {
        "nppes_practice": (
            "Mostly real US clinic addresses; Census misses suite/building formatting. "
            "Pattern mining won't fix bulk — needs geolocate_api or suite normalization."
        ),
        "nppes_mailing": "Mailing addresses; similar suite/format issues as practice.",
        "dot_carrier_phy": (
            "FMCSA carrier fraud magnets: Unknown street placeholders, foreign carriers, "
            "highway intersections without numbers."
        ),
        "dot_carrier_mail": "Mailing variant; Canadian addresses and suite junk.",
        "fec_operating_expenditure": (
            "88% city-only vendor payment addresses (AmEx, Verizon, USPS lockbox zips). "
            "ActBlue typos are a tiny subset."
        ),
    }
    return notes.get(address_type, "")


def render_markdown(report: Dict) -> str:
    lines = [
        "# Fraud-Source pending_api Pattern Mining",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Source diagnostics",
        "",
        "| address_type | weight | non-US % | suite-heavy % | note |",
        "|--------------|--------|----------|---------------|------|",
    ]
    for d in report["source_diagnostics"]:
        note = d["note"].replace("|", "\\|")[:80]
        lines.append(
            f"| {d['address_type']} | {d['total_weight']:,} | {d['non_us_pct']}% "
            f"| {d['suite_heavy_pct']}% | {note} |"
        )

    lines.extend([
        "",
        "## Pattern candidates (by total weight)",
        "",
    ])
    for p in report["pattern_candidates"]:
        lines.append(f"### {p['label']} (`{p['id']}`)")
        lines.append("")
        lines.append(f"- **Family:** {p['family']}")
        lines.append(f"- **Total weight:** {p['total_weight']:,}")
        lines.append(f"- **Regex:** `{p['regex'][:100]}{'...' if len(p['regex'])>100 else ''}`")
        lines.append("")
        for src, cov in sorted(p["coverage"].items(), key=lambda x: -x[1]["weight"]):
            lines.append(
                f"- `{src}`: {cov['weight']:,} ({cov['pct_of_source']}% of source)"
            )
        if p.get("samples"):
            lines.append("")
            lines.append("Samples:")
            for s in p["samples"]:
                lines.append(f"- [{s['source']}] {s['address']} (weight {s['weight']})")
        lines.append("")

    lines.extend([
        "## Recommended actions",
        "",
        "1. **FEC** — Add `fec_vendor_city_only` + payment-processor zip preprocess (safe; ~88% of FEC pending).",
        "2. **DOT** — Add placeholder-street + foreign Canada/Mexico patterns (~20% non-US + 3% Unknown).",
        "3. **NPPES** — Do **not** blanket-pattern; route to geolocate_api. Optional building/suite normalization.",
        "4. Validate with `mine_fraud_source_patterns.py` then `geolocate_api` preprocess pass.",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR)
    parser.add_argument("--json-out", default="fraud_source_pattern_mining.json")
    parser.add_argument("--report", default="fraud_source_pattern_mining.md")
    args = parser.parse_args(argv)

    db_path = os.path.join(args.final_dir, "irs990.duckdb")
    by_source = load_source_rows(db_path)
    report = mine_patterns(by_source)

    json_path = os.path.join(args.final_dir, args.json_out)
    report_path = os.path.join(args.final_dir, args.report)
    tools_report = os.path.join(os.path.dirname(__file__), args.report)

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    markdown = render_markdown(report)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    with open(tools_report, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    print(f"Patterns with coverage: {len(report['pattern_candidates'])}")
    for p in report["pattern_candidates"][:6]:
        print(f"  {p['id']:30} weight={p['total_weight']:,}")
    print(f"JSON → {json_path}")
    print(f"Report → {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())