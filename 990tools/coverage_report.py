#!/usr/bin/env python3
"""
coverage_report.py - Quantify the value of the name canonicalization rules

Reports:
- Total unique EINs covered by rules
- Total grant dollars covered
- Top 20 rules by grant $ covered
- Percentage of total EINs/grants covered
"""

import json
import gzip
import sys
from collections import defaultdict
from typing import Dict, Set

import glob

def get_latest_rules_file():
    files = glob.glob("name_rules_v*.json.gz")
    if not files:
        print("No rules file found!")
        exit(1)
    latest = max(files, key=lambda x: int(x.split('_v')[1].split('.')[0]))
    return latest

RULES_FILE = get_latest_rules_file()
GRANTS_TSV = 'distinct_grantee_names.tsv'

def load_rules():
    with gzip.open(RULES_FILE, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle both old list format and new dict format (v19.1+)
    if isinstance(data, list):
        return data  # old format: list of {"canonical": ..., "variants": [...]}
    elif isinstance(data, dict):
        # new format: {canonical: {"variants": [...], "sources": [...]}, ...}
        # Also handle edge case where some values are lists instead of dicts
        result = []
        for k, v in data.items():
            if isinstance(v, dict):
                variants = v.get("variants", [])
            elif isinstance(v, list):
                variants = v  # old-style value was already the variants list
            else:
                variants = []
            result.append({"canonical": k, "variants": variants})
        return result
    else:
        print(f"Unexpected rules format: {type(data)}")
        exit(1)

def load_grant_totals() -> Dict[str, Dict[str, float]]:
    """
    Load grant totals from distinct_grantee_names.tsv
    Returns: {grantee_name: {'grant_count': X, 'dollars': Y}}
    """
    grant_totals: Dict[str, Dict[str, float]] = {}
    with open(GRANTS_TSV, 'r', encoding='utf-8') as f:
        header = next(f).strip().split('\t')
        print(f"Header columns: {header}")
        
        # Find columns
        name_col = header.index('grantee_name') if 'grantee_name' in header else 0
        count_col = header.index('grant_count') if 'grant_count' in header else 1
        dollars_col = header.index('dollars') if 'dollars' in header else 2
        
        print(f"Using columns: name={name_col}, grant_count={count_col}, dollars={dollars_col}")
        
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) > max(name_col, count_col, dollars_col):
                name = parts[name_col].strip().upper()
                try:
                    grant_count = float(parts[count_col])
                    dollars = float(parts[dollars_col])
                    grant_totals[name] = {'grant_count': grant_count, 'dollars': dollars}
                except (ValueError, IndexError):
                    pass
    return grant_totals

def main():
    print("Loading rules...")
    rules = load_rules()
    print(f"Loaded {len(rules):,} rules")
    
    print("Loading grant totals from distinct_grantee_names.tsv...")
    grant_totals = load_grant_totals()
    total_names = len(grant_totals)
    total_grant_count = sum(v['grant_count'] for v in grant_totals.values())
    total_dollars = sum(v['dollars'] for v in grant_totals.values())
    print(f"Loaded {total_names:,} grantee names with {total_grant_count:,.0f} grants (${total_dollars:,.0f})")
    
    # Track coverage
    rule_coverage: Dict[str, Dict] = {}
    covered_names: Set[str] = set()
    covered_grant_count = 0.0
    covered_dollars = 0.0
    
    def _variant_to_str(v) -> str:
        """Safely convert a variant (string or dict) to uppercase string."""
        if isinstance(v, str):
            return v.upper()
        if isinstance(v, dict):
            # Common keys: 'name', 'canonical', or the value itself
            for key in ('name', 'canonical', 'value'):
                if key in v:
                    return str(v[key]).upper()
            # Fallback: first string value in the dict
            for val in v.values():
                if isinstance(val, str):
                    return val.upper()
            return str(v).upper()
        return str(v).upper()

    print("\nAnalyzing coverage (matching variants to grantee names)...")
    for rule in rules:
        canonical = rule['canonical']
        variants = [_variant_to_str(v) for v in rule['variants']]
        
        rule_grant_count = 0.0
        rule_dollars = 0.0
        matched = 0
        
        for variant in variants:
            if variant in grant_totals:
                rule_grant_count += grant_totals[variant]['grant_count']
                rule_dollars += grant_totals[variant]['dollars']
                covered_names.add(variant)
                matched += 1
        
        rule_coverage[canonical] = {
            'variants': len(variants),
            'matched': matched,
            'grant_count': rule_grant_count,
            'dollars': rule_dollars
        }
    
    covered_grant_count = sum(grant_totals[name]['grant_count'] for name in covered_names)
    covered_dollars = sum(grant_totals[name]['dollars'] for name in covered_names)
    
    # Load EIN mapping to distinguish names with/without EIN
    print("Loading EIN mapping from ein_name_variants.tsv...")
    ein_map = {}
    with open('ein_name_variants.tsv', 'r', encoding='utf-8') as f:
        next(f)
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                ein = parts[0].strip()
                name = parts[1].strip().upper()
                ein_map[name] = ein
    
    covered_with_ein = sum(1 for name in covered_names if name in ein_map)
    covered_without_ein = len(covered_names) - covered_with_ein
    
    print(f"\n{'='*70}")
    print(f"COVERAGE REPORT - Name Canonicalization Rules")
    print(f"{'='*70}")
    print(f"Total grantee names:         {total_names:,}")
    print(f"Names covered by rules:      {len(covered_names):,}")
    print(f"  - With EIN:                {covered_with_ein:,}")
    print(f"  - Without EIN:             {covered_without_ein:,}")
    print(f"Coverage:                    {len(covered_names)/total_names*100:.1f}%")
    print()
    print(f"Total grants:                {total_grant_count:,.0f}")
    print(f"Grants covered:              {covered_grant_count:,.0f}")
    print(f"Grant coverage:              {covered_grant_count/total_grant_count*100:.1f}%")
    print()
    print(f"Total dollars:               ${total_dollars:,.0f}")
    print(f"Dollars covered:             ${covered_dollars:,.0f}")
    print(f"Dollar coverage:             {covered_dollars/total_dollars*100:.1f}%")
    print(f"{'='*70}")
    
    # Top 20 rules by dollars covered
    print("\nTop 20 rules by dollars covered:")
    sorted_rules = sorted(rule_coverage.items(), key=lambda x: -x[1]['dollars'])[:20]
    for i, (canonical, data) in enumerate(sorted_rules, 1):
        print(f"{i:2}. {canonical:35} | {data['matched']:>5,}/{data['variants']:<5,} | ${data['dollars']:>12,.0f}")
        # matched = how many variants actually appear in grants
        # variants = total variants found for this canonical
    
    # Top 20 covered names WITHOUT EIN (by dollars)
    print("\nTop 20 covered names WITHOUT EIN (by dollars):")
    names_without_ein = [(name, grant_totals[name]) for name in covered_names if name not in ein_map]
    names_without_ein.sort(key=lambda x: -x[1]['dollars'])
    for i, (name, data) in enumerate(names_without_ein[:20], 1):
        print(f"{i:2}. {name[:55]:55} | ${data['dollars']:>15,.0f} | {data['grant_count']:>8,.0f} grants")

if __name__ == "__main__":
    main()