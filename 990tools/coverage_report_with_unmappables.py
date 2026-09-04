#!/usr/bin/env python3
"""
coverage_report_with_unmappables.py

Enhanced coverage reporter that explicitly separates "deliberately unmappable"
categories (big pharma subsidy, and in future university_sided / church redaction etc.)
from the "mappable" coverage numbers.

This directly addresses the measurement goal:
- Overall $ and # coverage
- Coverage excluding unmappables (the number that actually matters for the matcher)
- Pharma is the canonical example today; the pattern is now general for any pre-sided bucket.

Usage:
    python coverage_report_with_unmappables.py \
        --rules name_rules_vXX.json.gz \
        --unmappable-patterns big_pharma_subsidy.json \
        --unmappable-label "BIG PHARMA SUBSIDY"
"""

import argparse
import json
import gzip
from collections import defaultdict
from typing import Dict, Set, List

def load_rules(path: str) -> List[Dict]:
    opener = gzip.open if path.endswith(".gz") else open
    mode = "rt" if path.endswith(".gz") else "r"
    with opener(path, mode, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        # Current generator output format: list of [canonical_str, meta_dict] pairs
        # or already list-of-dicts. Normalize to consistent list of dicts.
        result = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                canon = item[0]
                meta = item[1] if isinstance(item[1], dict) else {}
                variants = meta.get("variants", []) if isinstance(meta, dict) else []
                result.append({"canonical": canon, "variants": variants})
            elif isinstance(item, dict):
                result.append(item)
        return result
    if isinstance(data, dict):
        result = []
        for k, v in data.items():
            variants = v.get("variants", []) if isinstance(v, dict) else (v if isinstance(v, list) else [])
            result.append({"canonical": k, "variants": variants})
        return result
    return []

def load_grant_totals(path: str) -> Dict[str, Dict]:
    totals = {}
    with open(path, "r", encoding="utf-8") as f:
        header = next(f).strip().split("\t")
        name_i = header.index("grantee_name") if "grantee_name" in header else 0
        cnt_i = header.index("grant_count") if "grant_count" in header else 1
        dol_i = header.index("dollars") if "dollars" in header else 2
        for line in f:
            p = line.strip().split("\t")
            if len(p) > max(name_i, cnt_i, dol_i):
                name = p[name_i].strip().upper()
                try:
                    totals[name] = {
                        "grant_count": float(p[cnt_i]),
                        "dollars": float(p[dol_i]),
                    }
                except Exception:
                    pass
    return totals

def load_unmappable_patterns(path: str) -> Dict[str, List]:
    """Return {canonical: [compiled_regex, ...]} from a subsidy-style json."""
    if not path:
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        print(f"Warning: could not load unmappable patterns from {path}")
        return {}

    out = {}
    for canon, entry in data.items():
        pats = []
        for p in entry.get("patterns", []):
            try:
                pats.append(re.compile(p, re.IGNORECASE))
            except Exception:
                pass
        if pats:
            out[canon] = pats
    return out

import re

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True, help="name_rules*.json or .gz")
    ap.add_argument("--grants-tsv", default="distinct_grantee_names.tsv")
    ap.add_argument("--unmappable-patterns", default="big_pharma_subsidy.json",
                    help="Subsidy JSON (big_pharma_subsidy.json style) whose names should be treated as deliberately unmapped")
    ap.add_argument("--unmappable-label", default="BIG PHARMA SUBSIDY")
    args = ap.parse_args()

    print("Loading rules...")
    rules = load_rules(args.rules)
    print(f"Loaded {len(rules):,} rules")

    print("Loading grant totals...")
    grant_totals = load_grant_totals(args.grants_tsv)
    total_names = len(grant_totals)
    total_grants = sum(v["grant_count"] for v in grant_totals.values())
    total_dollars = sum(v["dollars"] for v in grant_totals.values())
    print(f"Total grantee names: {total_names:,} | grants: {total_grants:,.0f} | $: ${total_dollars:,.0f}")

    unmappable_pats = load_unmappable_patterns(args.unmappable_patterns)
    print(f"Loaded {len(unmappable_pats)} unmappable pattern sets ({args.unmappable_label})")

    covered_names: Set[str] = set()
    unmappable_names: Set[str] = set()
    rule_to_dollars = defaultdict(float)
    rule_to_grants = defaultdict(float)

    for rule in rules:
        canon = rule["canonical"]
        variants = rule.get("variants", [])
        is_unmappable_canon = args.unmappable_label.upper() in canon.upper() or any(
            args.unmappable_label.upper() in str(v).upper() for v in variants
        )

        for v in variants:
            vstr = str(v).upper().strip() if not isinstance(v, dict) else str(v.get("name", v)).upper()
            if vstr in grant_totals:
                g = grant_totals[vstr]
                if is_unmappable_canon or any(p.search(vstr) for pats in unmappable_pats.values() for p in pats):
                    unmappable_names.add(vstr)
                else:
                    covered_names.add(vstr)
                    rule_to_grants[canon] += g["grant_count"]
                    rule_to_dollars[canon] += g["dollars"]

    # Compute aggregates
    covered_grants = sum(grant_totals[n]["grant_count"] for n in covered_names)
    covered_dollars = sum(grant_totals[n]["dollars"] for n in covered_names)

    unmappable_grants = sum(grant_totals[n]["grant_count"] for n in unmappable_names)
    unmappable_dollars = sum(grant_totals[n]["dollars"] for n in unmappable_names)

    mappable_names = total_names - len(unmappable_names)
    mappable_grants = total_grants - unmappable_grants
    mappable_dollars = total_dollars - unmappable_dollars

    print("\n" + "=" * 75)
    print("COVERAGE REPORT (with explicit unmappables separation)")
    print("=" * 75)
    print(f"Unmappable bucket: {args.unmappable_label}")
    print(f"  Names in unmappable bucket: {len(unmappable_names):,}")
    print(f"  Grants in unmappable:       {unmappable_grants:,.0f}")
    print(f"  Dollars in unmappable:      ${unmappable_dollars:,.0f}")
    print()
    print("OVERALL (including unmappables)")
    print(f"  Names covered: {len(covered_names) + len(unmappable_names):,} / {total_names:,}  ({(len(covered_names)+len(unmappable_names))/total_names*100:.1f}%)")
    print(f"  Grants covered: {covered_grants + unmappable_grants:,.0f} / {total_grants:,.0f}  ({(covered_grants+unmappable_grants)/total_grants*100:.1f}%)")
    print(f"  Dollars covered: ${covered_dollars + unmappable_dollars:,.0f} / ${total_dollars:,.0f}  ({(covered_dollars+unmappable_dollars)/total_dollars*100:.1f}%)")
    print()
    print("MAPPABLE ONLY (excluding unmappables — the number that matters for the matcher)")
    print(f"  Mappable names in universe: {mappable_names:,}")
    print(f"  Names covered (mappable):   {len(covered_names):,} / {mappable_names:,}   ({len(covered_names)/max(mappable_names,1)*100:.1f}%)")
    print(f"  Grants covered (mappable):  {covered_grants:,.0f} / {mappable_grants:,.0f}   ({covered_grants/max(mappable_grants,1)*100:.1f}%)")
    print(f"  Dollars covered (mappable): ${covered_dollars:,.0f} / ${mappable_dollars:,.0f}   ({covered_dollars/max(mappable_dollars,1)*100:.1f}%)")
    print("=" * 75)

    # Top rules by mappable dollars
    print("\nTop 15 rules by mappable dollars covered:")
    sorted_rules = sorted(rule_to_dollars.items(), key=lambda x: -x[1])[:15]
    for canon, dol in sorted_rules:
        print(f"  {canon[:55]:<55}  ${dol:>15,.0f}")

if __name__ == "__main__":
    main()
