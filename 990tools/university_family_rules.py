#!/usr/bin/env python3
"""
university_family_rules.py

Repeatable generator for university/college family rules.

Purpose (per the main goal):
- Turn the ~24k BMF university/college entities (EIN-grounded "IRS" names)
  + algorithmic family grouping into high-quality canonical + variant + EIN
  mappings suitable for the name roll-up rules consumed by address_matcher.py.

This is the university analogue of the BIG PHARMA SUBSIDY siding in
generate_name_rules.py.

It produces:
1. university_families.json  — siding/priority input (structure parallel to big_pharma_subsidy.json)
2. Enhanced priority canonical list (can be appended to university_non_state_patterns.txt or loaded directly)
3. Stats for coverage measurement (family sizes, satellite capture rate, EIN coverage)

Why this matters:
- Universities/colleges often do not file 990s themselves but receive large grants.
- BMF gives us reliable EINs per entity.
- The family grouping (main + alumni + foundation + faculty + bookstore + ROTC etc.)
  lets us pre-map many variants that appear in real 990 grantee_name data.
- These become "pre-matched" / sided rules with real EINs, dramatically improving
  recipient_ein backfill in address_matcher without relying on 990 filings from the institutions.

Usage (repeatable):
    python university_family_rules.py \
        --bmf-subset bmf_university_college_subset.tsv \
        --grouped-families bmf_university_college_families.json \
        --output university_families.json \
        --emit-priority-list university_priority_additions.txt

Then feed university_families.json into a future (or patched) generate_name_rules.py
as UNIVERSITY_FAMILIES_JSON, exactly like BIG_PHARMA_JSON.

This keeps the generator repeatable and the "siding for pre-matched things" pattern
general (pharma today, universities now, high schools / churches later).
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd


def load_grouped_families(path: str) -> Dict[str, Dict]:
    """Load the output of group_bmf_university_entities.py (or equivalent)."""
    p = Path(path)
    if p.suffix == ".json":
        with open(p) as f:
            data = json.load(f)
        # Support both the {"clusters": {...}} wrapper and flat dict
        if "clusters" in data:
            return data["clusters"]
        return data
    else:
        # Fall back to reading the grouped TSV and rebuilding minimal families
        df = pd.read_csv(p, sep="\t")
        families = defaultdict(lambda: {"count": 0, "entity_types": {}, "names": [], "eins": []})
        for _, row in df.iterrows():
            canon = str(row.get("Categorized_Institution", "")).strip()
            if not canon or canon == "nan":
                continue
            fam = families[canon]
            fam["count"] += 1
            et = str(row.get("Entity_Type", "Other"))
            fam["entity_types"][et] = fam["entity_types"].get(et, 0) + 1
            if "NAME" in row:
                fam["names"].append(str(row["NAME"]))
            if "EIN" in row and pd.notna(row["EIN"]):
                fam["eins"].append(str(int(row["EIN"])))
        return dict(families)


def pick_best_ein(eins: List[str], names: List[str]) -> str:
    """Heuristic: prefer the EIN that appears with the shortest/cleanest main name."""
    if not eins:
        return ""
    # Count frequency
    from collections import Counter
    freq = Counter(eins)
    # Pick the most frequent; tie-break by shortest associated name if possible
    best = freq.most_common(1)[0][0]
    return best


def build_university_families_json(grouped: Dict[str, Dict], max_families: int = 2000) -> Dict[str, Any]:
    """
    Convert grouped BMF families into the siding format expected by the generator.

    Output shape is deliberately parallel to big_pharma_subsidy.json so the same
    loading + priority seeding + siding code path can be reused.
    """
    out = {}
    scored = []

    for canon, info in grouped.items():
        n = canon.upper()
        # Light noise filter (similar to what we did in the grouper)
        if "AMERICAN COLLEGE" in n and "OF" not in n and len(n) < 25:
            continue
        if n in {"TRUSTEES", "COLLEGE", "UNIVERSITY", "ALUMNAE ASSOCIATION"}:
            continue

        size = info.get("count", 0)
        types = info.get("entity_types", {})
        has_satellites = any(k in types for k in (
            "Alumni Association", "Foundation / Scholarship",
            "Faculty / Employee Group", "AAUW Branch"
        ))

        score = (10 if has_satellites else 0) * 10000 + size
        scored.append((score, canon, info))

    scored.sort(reverse=True)

    for score, canon, info in scored[:max_families]:
        names = info.get("names", [])
        eins = info.get("eins", [])
        best_ein = pick_best_ein(eins, names)

        # Build a small set of core patterns for siding / priority
        patterns = [canon]
        # Add a couple of common shortened forms that still uniquely identify the family
        if "UNIVERSITY" in canon.upper():
            short = canon.replace("University", "Univ").replace("UNIVERSITY", "UNIV")
            if short != canon:
                patterns.append(short)

        satellites = {}
        for et, cnt in info.get("entity_types", {}).items():
            if et not in ("Main Institution", "Community College"):
                satellites[et] = cnt

        entry = {
            "ein": best_ein or "99-8888888",   # real BMF EIN when available, synthetic fallback
            "patterns": patterns,
            "family_type": "university_or_college",
            "bmf_family_size": info.get("count", 0),
            "satellite_breakdown": satellites,
            "source": "bmf_university_family_grouped",
            "notes": "Generated by university_family_rules.py from BMF + algorithmic grouping. High-confidence EIN for backfill in address_matcher.",
        }
        out[canon] = entry

    return out


def emit_priority_additions(families_json: Dict[str, Any], out_path: str):
    """Emit a simple text file of additional priority canonicals (one per line) for easy appending."""
    canons = sorted(families_json.keys())
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Additional university/college priority canonicals from BMF family grouping\n")
        f.write("# Append to university_non_state_patterns.txt or load directly in generate_name_rules.py\n")
        for c in canons:
            f.write(c + "\n")
    print(f"Wrote {len(canons):,} priority additions to {out_path}")


def print_stats(families: Dict[str, Any]):
    total_families = len(families)
    total_entities = sum(f.get("bmf_family_size", 0) for f in families.values())
    with_sat = sum(1 for f in families.values() if f.get("satellite_breakdown"))
    real_ein = sum(1 for f in families.values() if f.get("ein", "").startswith(("0","1","2","3","4","5","6","7","8","9")) and len(f["ein"]) >= 9)

    print("\n" + "=" * 70)
    print("UNIVERSITY FAMILY RULES GENERATOR — STATS")
    print("=" * 70)
    print(f"Families emitted:            {total_families:,}")
    print(f"Total BMF entities covered:  {total_entities:,}")
    print(f"Families with satellites:    {with_sat:,} ({with_sat/total_families*100:.1f}%)")
    print(f"Families with real BMF EIN:  {real_ein:,}")
    print("=" * 70)
    print("\nTop 10 families by size:")
    top = sorted(families.items(), key=lambda kv: -kv[1].get("bmf_family_size", 0))[:10]
    for canon, info in top:
        sat = info.get("satellite_breakdown", {})
        sat_str = ", ".join(f"{k}:{v}" for k, v in sat.items()) if sat else "main only"
        print(f"  {canon[:50]:<50}  size={info.get('bmf_family_size',0):>5}  satellites=({sat_str})")


def main():
    parser = argparse.ArgumentParser(
        description="Generate university family siding rules from BMF + algorithmic grouping (repeatable generator step)"
    )
    parser.add_argument("--bmf-subset", default="bmf_university_college_subset.tsv",
                        help="Raw BMF university/college slice (used only if grouped json is missing)")
    parser.add_argument("--grouped-families", default="bmf_university_college_families.json",
                        help="Output of group_bmf_university_entities.py (preferred input)")
    parser.add_argument("--output", default="university_families.json",
                        help="Output siding file (parallel to big_pharma_subsidy.json)")
    parser.add_argument("--emit-priority-list", default="university_priority_additions.txt",
                        help="Simple text file of canonicals for the generator's PRIORITY list")
    parser.add_argument("--max-families", type=int, default=2000,
                        help="Limit number of families written (largest first)")
    args = parser.parse_args()

    print(f"Loading grouped families from {args.grouped_families}...")
    grouped = load_grouped_families(args.grouped_families)
    print(f"Loaded {len(grouped):,} families")

    families_json = build_university_families_json(grouped, max_families=args.max_families)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(families_json, f, indent=2)
    print(f"Wrote {args.output} with {len(families_json):,} university families")

    emit_priority_additions(families_json, args.emit_priority_list)

    print_stats(families_json)

    print("\nNext step (once integrated):")
    print("  Add UNIVERSITY_FAMILIES_JSON loading + siding logic to generate_name_rules.py")
    print("  (symmetric to the existing BIG_PHARMA_JSON / pharma_sided block).")
    print("  Then re-run the generator and coverage_report.py for the updated numbers.")


if __name__ == "__main__":
    main()
