#!/usr/bin/env python3
"""
reverse_coverage.py

"Reverse" coverage analysis for the 990 name rules system.

Goes through the generated rules and the distinct grantee names to find
variants that were pulled in but probably shouldn't have been (false positives).

Uses:
- Word set Jaccard similarity (reverse fuzzy matching)
- Checks for excessive PROBLEM_SUFFIXES or GENERIC_SINGLE_WORDS not explained by the canonical
- Flags rules with high "badness" score

This helps detect over-broad rules (e.g. ROTARY pulling in unrelated "Rotary Engine Repair").

Output: report of suspicious variants per canonical, sorted by badness.
"""

import gzip
import json
import re
from collections import defaultdict, Counter
from pathlib import Path
import difflib

from name_rule_constants import (
    GENERIC_SINGLE_WORDS, 
    PROBLEM_SUFFIXES, 
    GOOD_SINGLE_WORD_PRIORITIES,
    SIMPLES
)

def jaccard_similarity(set1, set2):
    """Simple reverse fuzzy matching via word set Jaccard."""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union else 0.0

def get_words(name: str) -> set:
    """Get meaningful words, uppercased, excluding common separators."""
    words = re.findall(r'\b\w+\b', name.upper())
    separators = {'OF', 'THE', 'AND', 'FOR', 'IN', 'ON', 'AT', 'TO'}
    return {w for w in words if w not in separators}

def main():
    rules_path = Path("name_rules_v19.1.json.gz")
    distinct_path = Path("distinct_grantee_names.tsv")
    
    print("Loading rules and data...")
    with gzip.open(rules_path, "rt", encoding="utf-8") as f:
        rules = json.load(f)

    # Handle both old list format and new dict format (v19.3+)
    if isinstance(rules, list):
        pass  # already list
    elif isinstance(rules, dict):
        result = []
        for k, v in rules.items():
            if isinstance(v, dict):
                variants = v.get("variants", [])
            elif isinstance(v, list):
                variants = v
            else:
                variants = []
            variants = [str(v) for v in variants if isinstance(v, (str, int, float))]  # filter to strings to prevent TypeError on set.update with dicts
            result.append({"canonical": k, "variants": variants})
        rules = result

    
    # Assume rules is list of dicts with 'canonical' and 'variants' or similar.
    # Adjust structure based on actual file (from previous runs it appears to be list of objects).
    canonical_to_variants = defaultdict(set)
    for rule in rules:
        if isinstance(rule, dict):
            canon = rule.get("canonical") or rule.get("cleaned") or str(rule)
            variants = rule.get("variants", [])
            if not isinstance(variants, list):
                variants = [variants]
            canonical_to_variants[canon.upper()].update(variants)
        elif isinstance(rule, str):
            canonical_to_variants[rule.upper()].add(rule)
    
    # Load distinct names for cross-check
    distinct_names = []
    with open(distinct_path, "r", encoding="utf-8") as f:
        next(f)  # skip header
        for line in f:
            if line.strip():
                name = line.split("\t")[0].strip()
                distinct_names.append(name)
    
    print(f"Loaded {len(canonical_to_variants)} canonicals and {len(distinct_names)} distinct names")
    print("\n=== REVERSE COVERAGE REPORT (Potential Bad Variants) ===\n")
    
    bad_reports = []
    for canon, variants in canonical_to_variants.items():
        canon_words = get_words(canon)
        is_priority = any(p.upper() in canon for p in SIMPLES) or canon in GOOD_SINGLE_WORD_PRIORITIES
        
        bad_variants = []
        for v in variants:
            if not v or v.upper() == canon:
                continue
            v_words = get_words(v)
            similarity = jaccard_similarity(canon_words, v_words)
            
            # Penalty for generic words not in canonical
            generic_in_v = v_words & GENERIC_SINGLE_WORDS
            unexplained_generic = len(generic_in_v - canon_words)
            problem_suffixes_in_v = len(v_words & PROBLEM_SUFFIXES)
            
            badness = 0.0
            if similarity < 0.4:
                badness += (0.4 - similarity) * 2.5
            badness += unexplained_generic * 1.5
            badness += max(0, problem_suffixes_in_v - 2) * 0.8
            
            if badness > 0.8 and not is_priority:
                bad_variants.append((v, similarity, badness, unexplained_generic))
        
        if bad_variants:
            bad_variants.sort(key=lambda x: x[2], reverse=True)
            bad_reports.append((canon, bad_variants[:5]))  # top 5 worst per canonical
    
    # Sort by worst offenders
    bad_reports.sort(key=lambda x: max((v[2] for v in x[1]), default=0), reverse=True)
    
    for canon, bad_list in bad_reports[:20]:  # top 20 rules with problems
        print(f"CANONICAL: {canon}")
        for v, sim, badness, gen in bad_list:
            print(f"  → {v} | similarity={sim:.3f} | badness={badness:.2f} | unexplained_generic={gen}")
        print("-" * 60)
    
    if not bad_reports:
        print("No significant bad variants detected. Rule set looks clean.")
    else:
        print(f"\nFound {len(bad_reports)} rules with potential over-matching variants.")
    
    print("\nReverse coverage script complete. Saved as reverse_coverage.py")
    print("Run with: .venv/bin/python reverse_coverage.py")

if __name__ == "__main__":
    main()
