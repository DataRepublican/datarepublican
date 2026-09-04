#!/usr/bin/env python3
"""
analyze_rule.py - Analyze a canonical rule for breadth and quality

Usage:
    python analyze_rule.py "HIGH SCHOOL"
    python analyze_rule.py "A NONPROFIT"
    python analyze_rule.py --top 20
"""

import json
import gzip
import sys
import argparse
import re
from collections import Counter

import glob
import os

def find_latest_rules_file():
    """Auto-detect the most recent name_rules_*.json.gz"""
    files = glob.glob('name_rules_*.json.gz')
    if not files:
        print("ERROR: No name_rules_*.json.gz files found in current directory.")
        sys.exit(1)
    
    # Sort by version number (extract vXX_YY from filename)
    def get_version(f):
        match = re.search(r'v(\d+)_(\d+)', f)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (0, 0)
    
    latest = max(files, key=get_version)
    print(f"Using latest rules file: {latest}")
    return latest

RULES_FILE = find_latest_rules_file()

def load_rules():
    with gzip.open(RULES_FILE, 'rt', encoding='utf-8') as f:
        return json.load(f)

# Known charities/abbreviations (same as in generate_name_rules)
KNOWN_CHARITIES = {
    'MADD': 'MOTHERS AGAINST DRUNK DRIVING',
    'M.A.D.D.': 'MOTHERS AGAINST DRUNK DRIVING',
    'BPOE': 'BENEVOLENT AND PROTECTIVE ORDER OF ELKS',
    'B.P.O.E.': 'BENEVOLENT AND PROTECTIVE ORDER OF ELKS',
    'ELKS': 'BENEVOLENT AND PROTECTIVE ORDER OF ELKS',
    'VFW': 'VETERANS OF FOREIGN WARS',
    'V.F.W.': 'VETERANS OF FOREIGN WARS',
    'AARP': 'AMERICAN ASSOCIATION OF RETIRED PERSONS',
    'NAACP': 'NATIONAL ASSOCIATION FOR THE ADVANCEMENT OF COLORED PEOPLE',
    'PTA': 'PARENT TEACHER ASSOCIATION',
    'P.T.A.': 'PARENT TEACHER ASSOCIATION',
    'BSA': 'BOY SCOUTS OF AMERICA',
    'B&GC': 'BOYS AND GIRLS CLUB',
    'IBT': 'INTERNATIONAL BROTHERHOOD OF TEAMSTERS',
    'YMCA': 'YOUNG MENS CHRISTIAN ASSOCIATION',
    'YWCA': 'YOUNG WOMENS CHRISTIAN ASSOCIATION',
}

def check_abbreviations(canonical: str, variants: list):
    """Check if this canonical came from abbreviation expansion"""
    expanded = []
    for abbr, full in KNOWN_CHARITIES.items():
        if full in canonical.upper() or full in ' '.join(variants).upper():
            expanded.append(f"{abbr} → {full}")
    
    if expanded:
        print(f"\nAbbreviation expansions detected:")
        for e in set(expanded):
            print(f"  ✓ {e}")

def analyze(canonical: str, rules: list):
    # Find the rule
    rule = None
    for r in rules:
        if r['canonical'] == canonical:
            rule = r
            break
    
    if not rule:
        print(f"Rule '{canonical}' not found.")
        return
    
    variants = rule['variants']
    source_count = rule.get('source_count', len(variants))
    
    print(f"\n=== {canonical} ===")
    print(f"EIN: {rule['ein']}")
    print(f"Variants: {len(variants):,} (source: {source_count:,})")
    
    # Check for abbreviation expansions
    check_abbreviations(canonical, variants)
    
    # Sample variants
    print(f"\nFirst 10 variants:")
    for v in variants[:10]:
        print(f"  - {v}")
    
    if len(variants) > 10:
        print(f"\nLast 10 variants:")
        for v in variants[-10:]:
            print(f"  - {v}")
    
    # Unique words
    all_words = []
    for v in variants:
        all_words.extend(v.split())
    word_counts = Counter(all_words)
    unique_words = len(word_counts)
    
    print(f"\nUnique words across variants: {unique_words:,}")
    print(f"Top 10 most common words in variants:")
    for word, count in word_counts.most_common(10):
        print(f"  {word}: {count:,}")
    
    # Better breadth score: log(variants) / len(canonical content words)
    # Higher = broader (many variants, few words in canonical itself)
    import math
    canonical_words = [w for w in canonical.split() if w not in {'OF', 'THE', 'AND', 'A', 'FOR', 'IN', 'TO', 'BY'}]
    breadth = math.log(max(len(variants), 1)) / max(len(canonical_words), 1)
    print(f"\nBreadth score (log(variants) / content words): {breadth:.2f}")
    if breadth > 4.0:
        print("  → VERY BROAD - strongly consider blacklisting")
    elif breadth > 3.0:
        print("  → BROAD - review carefully")
    else:
        print("  → REASONABLE")
    
    # Check for exact match vs substring match
    exact_matches = sum(1 for v in variants if canonical in v.split())
    print(f"\nExact word matches: {exact_matches:,} / {len(variants):,}")

def show_top(rules: list, n: int = 20):
    print(f"\n=== Top {n} Rules by Variant Count ===\n")
    for i, r in enumerate(rules[:n], 1):
        print(f"{i:2}. {r['canonical']}: {len(r['variants']):,} variants (source: {r.get('source_count', len(r['variants'])):,})")

def list_broad(rules: list, threshold: float = 3.0):
    import math
    broad = []
    for r in rules:
        canonical = r['canonical']
        variants = len(r['variants'])
        canonical_words = [w for w in canonical.split() if w not in {'OF', 'THE', 'AND', 'A', 'FOR', 'IN', 'TO', 'BY'}]
        breadth = math.log(max(variants, 1)) / max(len(canonical_words), 1)
        if breadth > threshold:
            broad.append((canonical, variants, breadth))
    
    broad.sort(key=lambda x: -x[2])  # Sort by breadth descending
    print(f"\n=== Rules with breadth > {threshold} ({len(broad):,} total) ===\n")
    for canonical, variants, breadth in broad[:50]:
        print(f"{breadth:.2f} | {variants:>6,} | {canonical}")

def show_abbreviations(rules: list):
    """Report on all abbreviations and their variant counts"""
    print("\n=== Abbreviation Expansions ===\n")
    
    abbrev_stats = {}
    for abbr, full in KNOWN_CHARITIES.items():
        variants = []
        for r in rules:
            if full in r['canonical'].upper():
                variants.extend(r['variants'])
        if variants:
            abbrev_stats[abbr] = {
                'full': full,
                'canonical': full,
                'variant_count': len(set(variants))
            }
    
    if not abbrev_stats:
        print("No abbreviation expansions found.")
        return
    
    # Sort by variant count
    sorted_abbrevs = sorted(abbrev_stats.items(), key=lambda x: -x[1]['variant_count'])
    
    for abbr, data in sorted_abbrevs:
        print(f"{abbr:15} → {data['full']:40} | {data['variant_count']:>6,} variants")

# Priority canonicals (longer, more specific phrases)
PRIORITY_CANONICALS = [
    'BOYS AND GIRLS CLUB',
    'CHAMBER OF COMMERCE',
    'PARENT TEACHER ASSOCIATION',
    'PARENT TEACHER ORGANIZATION',
    'VOLUNTEER FIRE DEPARTMENT',
    'FIRE DEPARTMENT',
    'SCHOOL DISTRICT',
    'HIGH SCHOOL',
    'MIDDLE SCHOOL',
    'PUBLIC LIBRARY',
    'COMMUNITY DEVELOPMENT',
    'ECONOMIC DEVELOPMENT',
    'MENTAL HEALTH',
    'HEALTH CARE',
    'FOOD BANK',
    'PERFORMING ARTS',
    'AMERICAN LEGION',
    'HABITAT FOR HUMANITY',
    'UNITED WAY',
    'SALVATION ARMY',
    'RED CROSS',
    'BOY SCOUTS OF AMERICA',
    'GIRL SCOUTS OF AMERICA',
    'VETERANS OF FOREIGN WARS',
    'MOTHERS AGAINST DRUNK DRIVING',
]

def show_priority(rules: list):
    """Report on priority canonicals (longer, more specific phrases)"""
    print("\n=== Priority Canonicals ===\n")
    
    found = []
    for priority in PRIORITY_CANONICALS:
        for r in rules:
            if r['canonical'].upper() == priority:
                found.append({
                    'canonical': r['canonical'],
                    'variants': len(r['variants']),
                    'source_count': r.get('source_count', len(r['variants']))
                })
                break
    
    if not found:
        print("No priority canonicals found.")
        return
    
    # Sort by variant count
    found.sort(key=lambda x: -x['variants'])
    
    for item in found:
        print(f"{item['canonical']:40} | {item['variants']:>6,} variants (source: {item['source_count']:,})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("canonical", nargs="?", help="Canonical name to analyze")
    parser.add_argument("--top", type=int, default=0, help="Show top N rules")
    parser.add_argument("--list-broad", type=float, default=0, help="List rules above breadth threshold (default 3.0)")
    parser.add_argument("--abbrev", action="store_true", help="Show all abbreviation expansions")
    parser.add_argument("--priority", action="store_true", help="Show priority canonicals (longer, more specific phrases)")
    args = parser.parse_args()
    
    rules = load_rules()
    
    if args.abbrev:
        show_abbreviations(rules)
    elif args.priority:
        show_priority(rules)
    elif args.list_broad > 0:
        list_broad(rules, args.list_broad)
    elif args.top > 0:
        show_top(rules, args.top)
    elif args.canonical:
        analyze(args.canonical, rules)
    else:
        print("Usage: python analyze_rule.py 'HIGH SCHOOL'")
        print("       python analyze_rule.py --top 20")
        print("       python analyze_rule.py --list-broad 3.5")
        print("       python analyze_rule.py --abbrev")
        print("       python analyze_rule.py --priority")