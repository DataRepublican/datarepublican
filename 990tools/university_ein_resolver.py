#!/usr/bin/env python3
"""
university_ein_resolver.py

Creates a high-quality, pre-resolved mapping for University-related names
by aggregating on recipient_ein and choosing the best canonical name per EIN.

Output: university_ein_mapping.json
"""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Set, List, Tuple


@dataclass
class UniversityCanonical:
    original: str
    cleaned: str
    ein: str = ""
    variants: Set[str] = field(default_factory=set)
    grant_count: int = 0
    dollars: float = 0.0


def choose_best_name(variants: List[Tuple[str, int, float]]) -> str:
    """
    Choose the best canonical name for a given EIN.
    Primary sort: shortest word count
    Secondary sort: highest dollar volume
    """
    if not variants:
        return ""

    variants.sort(key=lambda x: (len(x[0].split()), -x[2]))
    return variants[0][0]


def main():
    input_file = "distinct_grantee_names.tsv"
    university_lines_file = "university_lines.tsv"
    output_json = "university_ein_mapping.json"

    print("Creating focused university subset...")
    with open(input_file, 'r', encoding='utf-8') as fin, \
         open(university_lines_file, 'w', encoding='utf-8') as fout:
        header = fin.readline()
        fout.write(header)
        for line in fin:
            if 'university' in line.lower():
                fout.write(line)

    print(f"University subset created: {university_lines_file}")

    # Aggregate by recipient_ein
    ein_to_variants: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
    ein_to_grant_count: Dict[str, int] = defaultdict(int)
    ein_to_dollars: Dict[str, float] = defaultdict(float)

    print("Reading university lines and aggregating by EIN...")
    with open(university_lines_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)  # skip header

        for row in reader:
            if len(row) < 4:
                continue

            name = row[0].strip()
            try:
                grant_count = int(row[1])
                dollars = float(row[2])
            except ValueError:
                continue

            ein = row[3].strip()
            if not ein:
                continue

            ein_to_variants[ein].append((name, grant_count, dollars))
            ein_to_grant_count[ein] += grant_count
            ein_to_dollars[ein] += dollars

    print(f"Found {len(ein_to_variants):,} unique EINs with university names")

    # Build canonical objects
    canonicals: Dict[str, UniversityCanonical] = {}

    for ein, variants in ein_to_variants.items():
        best_name = choose_best_name(variants)
        if not best_name:
            continue

        canon = UniversityCanonical(
            original=best_name,
            cleaned=best_name,
            ein=ein,
            variants={v[0] for v in variants},
            grant_count=ein_to_grant_count[ein],
            dollars=ein_to_dollars[ein]
        )
        canonicals[best_name] = canon

    print(f"Built {len(canonicals):,} university canonicals")

    # Write JSON output
    output = {}
    for name, canon in canonicals.items():
        output[name] = {
            "ein": canon.ein,
            "variants": sorted(canon.variants),
            "grant_count": canon.grant_count,
            "dollars": round(canon.dollars, 2)
        }

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    total_dollars = sum(c.dollars for c in canonicals.values())
    print(f"\nWrote {output_json}")
    print(f"Total university-related dollars covered: ${total_dollars:,.0f}")


if __name__ == "__main__":
    main()
