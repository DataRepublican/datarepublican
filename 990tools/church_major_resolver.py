#!/usr/bin/env python3
"""
church_major_resolver.py

Repeatable script to extract and canonicalize major church-related names,
modeled directly on university_ein_resolver.py.

This is the "2" (repeatable script) that leads to "1" (generating the
major_churches.json data set).

Why:
- There are hundreds of "XXX CHURCH" variants in the grant data.
- Treating "CHURCH" as noise (already in DYNAMIC_NOISE_WHITELIST) is not
  enough for the large, high-dollar church networks and denominations.
- We want a curated set of <major name> CHURCH entries, parallel to how
  universities were pulled out into university_ein_mapping.json.

Usage (repeatable):
    python church_major_resolver.py \
        --input distinct_grantee_names_clean.tsv \
        --output major_churches.json \
        --min-grants 5 \
        --min-dollars 50000

The output JSON follows the exact same shape as university_ein_mapping.json
so it can be consumed by the same downstream tools (TUI pre-bless, rule
generators, future EIN resolver, etc.).

After running the script, manually curate major_churches.json down to the
truly major players before checking it in (the script gives you the raw
material reproducibly).
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Set

# Import the normalization logic we already built for the TUI.
# This gives us excellent collapsing of "THE XXX CHURCH OF FOO" vs "XXX CHURCH" etc.
try:
    # When running from inside the 990tools directory
    sys.path.insert(0, str(Path(__file__).parent))
    from review_suggestions_tui import _normalize_for_dedup, clean_proposed_pattern
except Exception:
    # Fallback: define minimal versions so the script remains standalone & repeatable
    import re

    def _normalize_for_dedup(name: str) -> str:
        if not name:
            return ""
        upper = name.upper().strip()
        upper = re.sub(r'^(THE|A|AN)\s+', '', upper)
        geo_suffix_pattern = re.compile(
            r'\s+(OF|IN|FOR|AT|BY|WITH)\s+([A-Z][A-Z\s\-]+)$', re.IGNORECASE
        )
        match = geo_suffix_pattern.search(upper)
        if match:
            upper = upper[:match.start()].strip()
        plural_map = {
            "CLUBS": "CLUB", "CENTERS": "CENTER", "SCHOOLS": "SCHOOL",
            "FOUNDATIONS": "FOUNDATION", "ASSOCIATIONS": "ASSOCIATION",
        }
        words = upper.split()
        normalized_words = [plural_map.get(w, w) for w in words]
        return " ".join(normalized_words)

    def clean_proposed_pattern(pattern: str) -> str:
        if not pattern:
            return ""
        p = str(pattern).strip()
        p = re.sub(r'(?i)^(THE|A|AN)\s+', '', p)
        p = re.sub(r'(?i)\s+(OF|IN|FOR|AT|BY|WITH)\s+[A-Za-z][A-Za-z0-9\s\-\&\.\,\']+$', '', p)
        plural_map = {
            "CLUBS": "CLUB", "CENTERS": "CENTER", "SCHOOLS": "SCHOOL",
            "FOUNDATIONS": "FOUNDATION", "ASSOCIATIONS": "ASSOCIATION",
        }
        words = p.split()
        normalized = []
        for w in words:
            upper_w = w.upper()
            if upper_w in plural_map:
                singular = plural_map[upper_w]
                normalized.append(singular if not w[0].isupper() else singular.capitalize())
            else:
                normalized.append(w)
        return " ".join(normalized).strip().upper()


@dataclass
class ChurchCanonical:
    original: str
    cleaned: str
    ein: str = ""
    variants: Set[str] = field(default_factory=set)
    grant_count: int = 0
    dollars: float = 0.0


def choose_best_name(variants: List[Tuple[str, int, float]]) -> str:
    """
    Choose the best canonical name for a given EIN.
    Same heuristic as the university resolver:
      - Primary: shortest word count (favors "FIRST BAPTIST CHURCH" over
        "FIRST BAPTIST CHURCH OF THE HOLY SPIRIT OF ...")
      - Secondary: highest dollar volume
    """
    if not variants:
        return ""
    variants.sort(key=lambda x: (len(x[0].split()), -x[2]))
    return variants[0][0]


def is_church_name(name: str) -> bool:
    """Simple, fast filter for church-related names."""
    if not name:
        return False
    n = name.upper()
    return "CHURCH" in n


def main():
    parser = argparse.ArgumentParser(
        description="Generate major_churches.json from the clean grantee names TSV"
    )
    parser.add_argument("--input", default="distinct_grantee_names_clean.tsv",
                        help="Clean TSV (grantee_name, grant_count, dollars, ein, ...)")
    parser.add_argument("--output", default="major_churches.json",
                        help="Output JSON in the same format as university_ein_mapping.json")
    parser.add_argument("--church-lines", default="church_lines.tsv",
                        help="Intermediate file with only church rows (for inspection)")
    parser.add_argument("--min-grants", type=int, default=3,
                        help="Minimum grant_count to consider a church 'major'")
    parser.add_argument("--min-dollars", type=float, default=10000.0,
                        help="Minimum total dollars to consider a church 'major'")
    args = parser.parse_args()

    print("Creating focused church subset (repeatable filter)...")
    with open(args.input, 'r', encoding='utf-8') as fin, \
         open(args.church_lines, 'w', encoding='utf-8') as fout:
        header = fin.readline()
        fout.write(header)
        count = 0
        for line in fin:
            if is_church_name(line):
                fout.write(line)
                count += 1
    print(f"Church subset written: {args.church_lines} ({count:,} rows)")

    # Aggregate by EIN (when present) + also track high-value name-only churches
    ein_to_variants: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
    ein_to_grant_count: Dict[str, int] = defaultdict(int)
    ein_to_dollars: Dict[str, float] = defaultdict(float)

    # For churches without reliable EIN, we still want high-impact ones
    name_only: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    print("Reading church lines and aggregating...")
    with open(args.church_lines, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)  # header

        for row in reader:
            if len(row) < 3:
                continue   # support both 3-col clean TSV (name,count,dollars) and fuller files with EIN
            name = row[0].strip()
            if not is_church_name(name):
                continue

            try:
                grant_count = int(row[1])
                dollars = float(row[2])
            except ValueError:
                continue

            ein = row[3].strip() if len(row) > 3 else ""

            if ein:
                ein_to_variants[ein].append((name, grant_count, dollars))
                ein_to_grant_count[ein] += grant_count
                ein_to_dollars[ein] += dollars
            else:
                # Track name-only (we will collapse these with normalization below)
                prev_g, prev_d = name_only[name]
                name_only[name] = (prev_g + grant_count, prev_d + dollars)

    print(f"Found {len(ein_to_variants):,} EINs with church names")
    print(f"Found {len(name_only):,} distinct raw church names (no EIN in this row)")

    canonicals: Dict[str, ChurchCanonical] = {}

    # === Name-only path: the important generalization step ===
    # Many (most) rows in the clean TSV have no EIN. We must collapse variants
    # using the same normalization we use in the TUI, otherwise we get 50k
    # near-duplicate "local church" entries instead of a manageable set of
    # major church families/denominations/networks.
    print("Collapsing name-only church variants using TUI normalization...")

    norm_groups: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
    for raw_name, (g, d) in name_only.items():
        if g < args.min_grants and d < args.min_dollars:
            continue
        norm_key = _normalize_for_dedup(raw_name)
        if norm_key:
            norm_groups[norm_key].append((raw_name, g, d))

    for norm_key, members in norm_groups.items():
        if not members:
            continue

        # Pick best representative + aggregate totals
        total_g = sum(m[1] for m in members)
        total_d = sum(m[2] for m in members)

        if total_g < args.min_grants and total_d < args.min_dollars:
            continue

        # Prefer the shortest sensible name as the canonical (like universities)
        members.sort(key=lambda x: (len(x[0].split()), -x[2]))
        best_raw = members[0][0]

        all_variants = {m[0] for m in members}

        canon = ChurchCanonical(
            original=best_raw,
            cleaned=best_raw.upper(),
            ein="",
            variants=all_variants,
            grant_count=total_g,
            dollars=round(total_d, 2)
        )
        # Use the normalized key as the top-level key in the JSON for stability
        canonicals[norm_key] = canon

    print(f"Built {len(canonicals):,} church canonicals after normalization + thresholding")

    # Write JSON (same shape as university_ein_mapping.json)
    output = {}
    for name, canon in sorted(canonicals.items()):
        output[name] = {
            "ein": canon.ein,
            "variants": sorted(canon.variants),
            "grant_count": canon.grant_count,
            "dollars": canon.dollars
        }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    total_dollars = sum(c.dollars for c in canonicals.values())
    print(f"\nWrote {args.output}")
    print(f"Total church-related dollars covered: ${total_dollars:,.0f}")
    print("Next step: curate the JSON down to true major churches, then wire it into")
    print("  - the TUI (pre-bless)")
    print("  - generate_name_rules.py (PRIORITY_CANONICALS injection)")
    print("  - future church_ein_resolver if desired")


if __name__ == "__main__":
    main()
