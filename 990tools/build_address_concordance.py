#!/usr/bin/env python3
"""
Build a weighted concordance from pending_api failure export for pattern mining.

Reads pending_api_failures_for_patterns.tsv.gz (or queries DuckDB if export missing),
tokenizes canonical_address, ranks unigrams/bigrams/trigrams by address_count weight,
and writes a human-review report plus JSON concordance.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from config import global_config
from constants import CENSUS_FAILURES_EXPORT_FILE, GEOCODING_STATUS_PENDING_API, DEFAULT_FINAL_DIR

# Street / geography noise — keep tokens that signal narrative or non-address text
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "at", "to", "for", "on", "by", "with",
    "st", "street", "ave", "avenue", "blvd", "boulevard", "rd", "road", "dr", "drive",
    "ln", "lane", "ct", "court", "pl", "place", "way", "cir", "circle", "pkwy", "parkway",
    "hwy", "highway", "ste", "suite", "apt", "apartment", "unit", "bldg", "building",
    "fl", "floor", "rm", "room", "po", "box", "usa", "us", "united", "states",
    "north", "south", "east", "west", "n", "s", "e", "w", "ne", "nw", "se", "sw",
    "tx", "ca", "ny", "fl", "il", "pa", "oh", "ga", "nc", "mi", "nj", "va", "wa",
    "ma", "az", "tn", "in", "mo", "md", "wi", "co", "mn", "sc", "al", "la", "ky",
    "or", "ok", "ct", "ut", "ia", "nv", "ar", "ms", "ks", "nm", "ne", "wv", "id",
    "hi", "nh", "me", "mt", "ri", "de", "sd", "nd", "ak", "dc", "vt", "wy", "pr", "vi",
    "no", "number", "num", "#",
})

# Hints for pattern families when reviewing top tokens
FAMILY_HINTS = {
    "see": "narrative_ref",
    "attached": "narrative_ref",
    "attachment": "narrative_ref",
    "statement": "narrative_ref",
    "schedule": "narrative_ref",
    "request": "privacy",
    "file": "privacy",
    "available": "privacy",
    "exempt": "privacy",
    "various": "vague",
    "multiple": "vague",
    "lockbox": "mail_ops",
    "dept": "mail_ops",
    "department": "mail_ops",
    "remittance": "mail_ops",
    "foreign": "foreign",
    "international": "foreign",
}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)

# Human labels for Addresses.address_type (FEC, DOT, NPPES, etc.)
SOURCE_LABELS = {
    "fec_committee": "FEC committee",
    "fec_contributor": "FEC individual contributor",
    "fec_committee_transaction": "FEC committee transaction",
    "fec_candidate_spending": "FEC candidate spending",
    "fec_operating_expenditure": "FEC operating expenditure",
    "dot_carrier_phy": "DOT carrier (physical)",
    "dot_carrier_mail": "DOT carrier (mailing)",
    "nppes_practice": "NPPES practice",
    "nppes_mailing": "NPPES mailing",
    "ofac_sanction": "OFAC sanction",
    "charity": "IRS 990 charity",
    "grant": "IRS 990 grantee",
    "officer": "IRS 990 officer",
    "bmf": "IRS BMF",
    "politicalcontribution": "Political contribution",
}

ACTBLUE_RE = re.compile(r"act\s*blue", re.IGNORECASE)


@dataclass
class SourceRow:
    canonical_address: str
    weight: int
    geocoding_id: str
    address_type: str
    is_actblue: bool = False


@dataclass
class _TokenStats:
    uni: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bi: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tri: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    uni_rows: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    samples: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    row_count: int = 0
    total_weight: int = 0
    uncovered_rows: int = 0
    uncovered_weight: int = 0


def _source_label(address_type: str) -> str:
    return SOURCE_LABELS.get(address_type, address_type.replace("_", " "))


def _normalize_text(text: str) -> str:
    return (text or "").lower().strip()


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(_normalize_text(text))


def ngrams(tokens: Sequence[str], n: int) -> Iterable[str]:
    if len(tokens) < n:
        return
    for i in range(len(tokens) - n + 1):
        yield " ".join(tokens[i : i + n])


def load_existing_pattern_regexes() -> List[str]:
    path = os.path.join(os.path.dirname(__file__), "geocoding_patterns.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError:
        return []
    regexes: List[str] = []
    for pattern in data.get("patterns", []):
        if pattern.get("regex"):
            regexes.append(pattern["regex"])
        for sub in pattern.get("patterns", []):
            if sub.get("regex"):
                regexes.append(sub["regex"])
    return regexes


def covered_by_existing_patterns(text: str, regexes: Sequence[str]) -> bool:
    for regex in regexes:
        try:
            if re.search(regex, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def load_rows_from_export(path: str) -> List[SourceRow]:
    rows: List[SourceRow] = []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        has_source = "address_type" in (reader.fieldnames or [])
        for row in reader:
            canon = (row.get("canonical_address") or "").strip()
            if not canon:
                continue
            try:
                count = int(row.get("source_count") or row.get("address_count") or 0)
            except ValueError:
                count = 0
            gid = row.get("geocoding_id") or ""
            address_type = (row.get("address_type") or "unknown").strip() or "unknown"
            is_actblue = (row.get("is_actblue") or "").strip() in {"1", "true", "True"}
            if not is_actblue and row.get("sample_name"):
                is_actblue = bool(ACTBLUE_RE.search(row.get("sample_name") or ""))
            rows.append(
                SourceRow(
                    canonical_address=canon,
                    weight=max(count, 1),
                    geocoding_id=gid,
                    address_type=address_type,
                    is_actblue=is_actblue,
                )
            )
        if not has_source:
            print(
                "Warning: export lacks address_type — re-query DuckDB with --from-db for source breakdown",
                file=sys.stderr,
            )
    return rows


def load_rows_from_db(final_dir: str) -> List[SourceRow]:
    import duckdb

    db_path = os.path.join(final_dir, "irs990.duckdb")
    con = duckdb.connect(db_path, read_only=True)
    result = con.execute(
        """
        SELECT
            g.canonical_address,
            g.geocoding_id,
            a.address_type,
            COUNT(*) AS source_count,
            MAX(CASE WHEN LOWER(a.name) LIKE '%actblue%' THEN 1 ELSE 0 END) AS is_actblue,
            MAX(a.name) AS sample_name
        FROM Geocoding g
        INNER JOIN Addresses a ON a.geocoding_id = g.geocoding_id
        WHERE g.geocoding_status = ?
          AND g.canonical_address IS NOT NULL
          AND TRIM(g.canonical_address) != ''
        GROUP BY g.canonical_address, g.geocoding_id, a.address_type
        ORDER BY source_count DESC, g.canonical_address, a.address_type
        """,
        [GEOCODING_STATUS_PENDING_API],
    )
    rows: List[SourceRow] = []
    for canon, gid, address_type, source_count, is_actblue, _sample_name in result.fetchall():
        rows.append(
            SourceRow(
                canonical_address=canon,
                weight=max(int(source_count or 0), 1),
                geocoding_id=str(gid or ""),
                address_type=address_type or "unknown",
                is_actblue=bool(is_actblue),
            )
        )
    con.close()
    return rows


def _accumulate_tokens(
    stats: _TokenStats,
    canon: str,
    weight: int,
    *,
    sample_per_token: int,
    pattern_regexes: Sequence[str],
) -> None:
    stats.row_count += 1
    stats.total_weight += weight
    if not covered_by_existing_patterns(canon, pattern_regexes):
        stats.uncovered_rows += 1
        stats.uncovered_weight += weight

    tokens = [t for t in tokenize(canon) if t not in STOPWORDS and not t.isdigit()]
    for tok in tokens:
        stats.uni[tok] += weight
        stats.uni_rows[tok] += 1
        if len(stats.samples[tok]) < sample_per_token:
            stats.samples[tok].append(canon[:120])
    for ng in ngrams(tokens, 2):
        stats.bi[ng] += weight
    for ng in ngrams(tokens, 3):
        stats.tri[ng] += weight


def _rank_tokens(
    stats: _TokenStats,
    *,
    top_n: int,
    sample_per_token: int,
) -> Dict:
    total_weight = stats.total_weight

    def _rank(counter: Dict[str, int], row_counter: Optional[Dict[str, int]] = None):
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        out = []
        for term, weight in ranked[:top_n]:
            entry = {
                "term": term,
                "weight": weight,
                "pct_of_total": round(100.0 * weight / total_weight, 3) if total_weight else 0,
                "family_hint": FAMILY_HINTS.get(term.split()[0], ""),
                "samples": stats.samples.get(term.split()[0], stats.samples.get(term, []))[:sample_per_token],
            }
            if row_counter is not None:
                entry["row_count"] = row_counter.get(term.split()[0], row_counter.get(term, 0))
            out.append(entry)
        return out

    return {
        "source_rows": stats.row_count,
        "total_address_weight": total_weight,
        "uncovered_by_existing_patterns": {
            "rows": stats.uncovered_rows,
            "weight": stats.uncovered_weight,
            "pct_rows": round(100.0 * stats.uncovered_rows / stats.row_count, 2) if stats.row_count else 0,
        },
        "unigrams": _rank(stats.uni, stats.uni_rows),
        "bigrams": _rank(stats.bi),
        "trigrams": _rank(stats.tri),
    }


def build_concordance(
    rows: Sequence[SourceRow],
    *,
    top_n: int = 100,
    sample_per_token: int = 3,
    pattern_regexes: Sequence[str],
) -> Dict:
    overall = _TokenStats()
    by_source: Dict[str, _TokenStats] = defaultdict(_TokenStats)
    actblue = _TokenStats()
    source_summary: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"rows": 0, "weight": 0, "distinct_geocoding_ids": 0}
    )
    geocoding_ids_by_source: Dict[str, set] = defaultdict(set)

    for row in rows:
        _accumulate_tokens(
            overall,
            row.canonical_address,
            row.weight,
            sample_per_token=sample_per_token,
            pattern_regexes=pattern_regexes,
        )
        _accumulate_tokens(
            by_source[row.address_type],
            row.canonical_address,
            row.weight,
            sample_per_token=sample_per_token,
            pattern_regexes=pattern_regexes,
        )
        if row.is_actblue:
            _accumulate_tokens(
                actblue,
                row.canonical_address,
                row.weight,
                sample_per_token=sample_per_token,
                pattern_regexes=pattern_regexes,
            )

        source_summary[row.address_type]["rows"] += 1
        source_summary[row.address_type]["weight"] += row.weight
        geocoding_ids_by_source[row.address_type].add(row.geocoding_id)

    for address_type, ids in geocoding_ids_by_source.items():
        source_summary[address_type]["distinct_geocoding_ids"] = len(ids)

    by_source_out = {}
    for address_type, stats in sorted(
        by_source.items(),
        key=lambda kv: (-kv[1].total_weight, kv[0]),
    ):
        by_source_out[address_type] = {
            "label": _source_label(address_type),
            **_rank_tokens(stats, top_n=top_n, sample_per_token=sample_per_token),
        }

    source_breakdown = []
    for address_type, summary in sorted(
        source_summary.items(),
        key=lambda kv: (-kv[1]["weight"], kv[0]),
    ):
        entry = {
            "address_type": address_type,
            "label": _source_label(address_type),
            **summary,
        }
        entry["pct_of_weight"] = round(
            100.0 * summary["weight"] / overall.total_weight, 2
        ) if overall.total_weight else 0
        source_breakdown.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_rows": overall.row_count,
        "total_address_weight": overall.total_weight,
        "uncovered_by_existing_patterns": {
            "rows": overall.uncovered_rows,
            "weight": overall.uncovered_weight,
            "pct_rows": round(100.0 * overall.uncovered_rows / overall.row_count, 2)
            if overall.row_count
            else 0,
        },
        "unigrams": _rank_tokens(overall, top_n=top_n, sample_per_token=sample_per_token)["unigrams"],
        "bigrams": _rank_tokens(overall, top_n=top_n, sample_per_token=sample_per_token)["bigrams"],
        "trigrams": _rank_tokens(overall, top_n=top_n, sample_per_token=sample_per_token)["trigrams"],
        "by_address_source": source_breakdown,
        "by_source_concordance": by_source_out,
        "actblue": _rank_tokens(actblue, top_n=top_n, sample_per_token=sample_per_token),
    }


def render_markdown(concordance: Dict, *, source_label: str) -> str:
    lines = [
        "# pending_api Address Concordance Report",
        "",
        f"Generated: {concordance['generated_at']}",
        f"Source: {source_label}",
        "",
        "## Summary",
        "",
        f"- **Source-attributed rows:** {concordance['source_rows']:,}",
        f"- **Total linked-address weight:** {concordance['total_address_weight']:,}",
        f"- **Not matched by current geocoding_patterns.json:** "
        f"{concordance['uncovered_by_existing_patterns']['rows']:,} rows "
        f"({concordance['uncovered_by_existing_patterns']['pct_rows']}%), "
        f"weight {concordance['uncovered_by_existing_patterns']['weight']:,}",
        "",
        "Weights come from `Addresses` rows linked to each `pending_api` geocoding record "
        "(grouped by `address_type`). Review source mix before blaming one dataset.",
        "",
    ]

    if concordance.get("by_address_source"):
        lines.extend([
            "## By Address Source (`Addresses.address_type`)",
            "",
            "| address_type | label | linked rows | weight | % weight | distinct geocoding_ids |",
            "|--------------|-------|-------------|--------|----------|------------------------|",
        ])
        for item in concordance["by_address_source"]:
            lines.append(
                f"| {item['address_type']} | {item['label']} | {item['rows']:,} "
                f"| {item['weight']:,} | {item['pct_of_weight']}% "
                f"| {item['distinct_geocoding_ids']:,} |"
            )
        lines.append("")

    actblue = concordance.get("actblue") or {}
    if actblue.get("total_address_weight", 0) > 0:
        lines.extend([
            "## ActBlue-linked rows",
            "",
            f"- **Linked rows:** {actblue.get('source_rows', 0):,}",
            f"- **Weight:** {actblue.get('total_address_weight', 0):,}",
            "",
            "ActBlue hits are `fec_operating_expenditure` vendor rows whose `Addresses.name` "
            "contains `actblue`. Samples often show mangled city/state (e.g. Somverille, Cambridge Va).",
            "",
            "| term | weight | % actblue | sample |",
            "|------|--------|-----------|--------|",
        ])
        ab_weight = actblue.get("total_address_weight") or 1
        for item in (actblue.get("unigrams") or [])[:20]:
            sample = (item.get("samples") or [""])[0].replace("|", "\\|")[:80]
            pct = round(100.0 * item["weight"] / ab_weight, 2)
            lines.append(f"| {item['term']} | {item['weight']:,} | {pct}% | {sample} |")
        lines.append("")

    lines.extend([
        "Review top tokens below for new **safe** preprocess patterns "
        "(narrative refs, privacy, vague, mail ops). Add to `geocoding_patterns.json`, "
        "then validate with `validate_pattern_changes.py` before re-running pending_api.",
        "",
        "## Top Unigrams (all sources)",
        "",
        "| term | weight | % total | rows | hint | sample |",
        "|------|--------|---------|------|------|--------|",
    ])

    for item in concordance["unigrams"][:50]:
        sample = (item.get("samples") or [""])[0].replace("|", "\\|")[:80]
        lines.append(
            f"| {item['term']} | {item['weight']:,} | {item['pct_of_total']}% "
            f"| {item.get('row_count', '')} | {item.get('family_hint', '')} | {sample} |"
        )

    lines.extend([
        "",
        "## Top Bigrams",
        "",
        "| term | weight | % total |",
        "|------|--------|---------|",
    ])
    for item in concordance["bigrams"][:40]:
        lines.append(
            f"| {item['term']} | {item['weight']:,} | {item['pct_of_total']}% |"
        )

    lines.extend([
        "",
        "## Top Trigrams",
        "",
        "| term | weight | % total |",
        "|------|--------|---------|",
    ])
    for item in concordance["trigrams"][:30]:
        lines.append(
            f"| {item['term']} | {item['weight']:,} | {item['pct_of_total']}% |"
        )

    by_source = concordance.get("by_source_concordance") or {}
    if by_source:
        lines.extend([
            "",
            "## Top Unigrams by Address Source",
            "",
        ])
        for address_type, block in list(by_source.items())[:8]:
            lines.extend([
                f"### {_source_label(address_type)} (`{address_type}`)",
                "",
                f"Weight {block.get('total_address_weight', 0):,} across "
                f"{block.get('source_rows', 0):,} linked rows.",
                "",
                "| term | weight | % source | sample |",
                "|------|--------|----------|--------|",
            ])
            src_weight = block.get("total_address_weight") or 1
            for item in (block.get("unigrams") or [])[:15]:
                sample = (item.get("samples") or [""])[0].replace("|", "\\|")[:80]
                pct = round(100.0 * item["weight"] / src_weight, 2)
                lines.append(
                    f"| {item['term']} | {item['weight']:,} | {pct}% | {sample} |"
                )
            lines.append("")

    lines.extend([
        "",
        "## Suggested next steps",
        "",
        "1. Scan unigrams/bigrams with high weight + narrative hints (`see`, `attachment`, `statement`).",
        "2. Draft regex entries under `privacy_addresses`, `incomplete_addresses`, or new families.",
        "3. Run pattern validation; spot-check samples in this report.",
        "4. Re-run `geolocate_api` — preprocess should short-circuit new matches before Photon/Grok.",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build pending_api address concordance")
    parser.add_argument(
        "--final-dir",
        default=global_config.final_dir or DEFAULT_FINAL_DIR,
        help="Directory with DuckDB and/or export TSV",
    )
    parser.add_argument(
        "--export-file",
        default=CENSUS_FAILURES_EXPORT_FILE,
        help="Export filename (under final-dir)",
    )
    parser.add_argument("--top", type=int, default=100, help="Top N per n-gram class")
    parser.add_argument(
        "--report",
        default="pending_api_concordance_report.md",
        help="Markdown report path (under final-dir)",
    )
    parser.add_argument(
        "--json-out",
        default="pending_api_concordance.json",
        help="JSON concordance path (under final-dir)",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Query DuckDB with Addresses.address_type join (recommended)",
    )
    args = parser.parse_args(argv)

    export_path = os.path.join(args.final_dir, args.export_file)
    if args.from_db or not os.path.isfile(export_path):
        print(f"Querying DuckDB for pending_api rows + address sources...", flush=True)
        rows = load_rows_from_db(args.final_dir)
        source_label = f"DuckDB {args.final_dir}/irs990.duckdb (Geocoding + Addresses.address_type)"
    else:
        rows = load_rows_from_export(export_path)
        source_label = export_path

    if not rows:
        print("No pending_api rows found.", file=sys.stderr)
        return 1

    pattern_regexes = load_existing_pattern_regexes()
    concordance = build_concordance(rows, top_n=args.top, pattern_regexes=pattern_regexes)

    os.makedirs(args.final_dir, exist_ok=True)
    json_path = os.path.join(args.final_dir, args.json_out)
    report_path = os.path.join(args.final_dir, args.report)

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(concordance, handle, indent=2)

    markdown = render_markdown(concordance, source_label=source_label)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    # Copy report into 990tools for easy IDE access
    tools_report = os.path.join(os.path.dirname(__file__), "pending_api_concordance_report.md")
    with open(tools_report, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    print(
        f"Concordance: {len(rows):,} source-attributed rows, "
        f"weight {concordance['total_address_weight']:,}"
    )
    if concordance.get("by_address_source"):
        top = concordance["by_address_source"][0]
        print(
            f"Top source: {top['address_type']} ({top['pct_of_weight']}% of weight)",
            flush=True,
        )
    ab = concordance.get("actblue") or {}
    if ab.get("total_address_weight"):
        print(f"ActBlue-linked weight: {ab['total_address_weight']:,}", flush=True)
    print(f"JSON → {json_path}")
    print(f"Report → {report_path}")
    print(f"Copy → {tools_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())