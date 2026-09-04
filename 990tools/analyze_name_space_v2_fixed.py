#!/usr/bin/env python3
"""
analyze_name_space_v2.py

Enhanced version that shows:
- Raw name
- Cleaned name  
- Best canonical it tried to match (if any)
- Similarity score
- Assigned EIN (if found)
- Reason for being uncovered

Now with improved clean_name that protects prebuilt university canonicals.
"""

import json
import gzip
import csv
import re
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

from name_rule_constants import (
    GOOD_SINGLE_WORD_PRIORITIES,
    SIMPLES,
    PROBLEM_SUFFIXES,
    GENERIC_SINGLE_WORDS
)

def clean_name(name: str) -> str:
    """Improved clean_name that protects prebuilt university canonicals ("UNIVERSITY OF FLORIDA")."""
    name = re.sub(r'\s*\([^)]*\)', '', name)
    name = re.sub(r'\s*#\s*\d+\b', '', name)
    name = re.sub(r'^[^A-Za-z0-9]+', '', name)
    name = re.sub(r'^[\s\W]+', '', name)
    name = re.sub(r'\b(TR|TRUSTEE|TRUSTEES)\b', 'TRUST', name, flags=re.IGNORECASE)
    
    words = name.upper().split()
    
    if "UNIVERSITY" in words or "COLLEGE" in words:
        # Protect "UNIVERSITY OF {STATE}" patterns - this is why we prebuild the university canonicals
        filtered = []
        for i, w in enumerate(words):
            if w in {'OF', 'THE'} and i > 0 and words[i-1] in {'UNIVERSITY', 'COLLEGE'}:
                filtered.append(w)  # keep "UNIVERSITY OF FLORIDA"
                continue
            if w not in PROBLEM_SUFFIXES and w not in GENERIC_SINGLE_WORDS and w not in {'OF', 'THE'}:
                filtered.append(w)
    else:
        filtered = [w for w in words if w not in PROBLEM_SUFFIXES and w not in GENERIC_SINGLE_WORDS]
    
    # Only strip leading/trailing OF/THE for non-university names
    if not any(u in words for u in ('UNIVERSITY', 'COLLEGE')):
        while filtered and filtered[0] in {'OF', 'THE'}:
            filtered.pop(0)
        while filtered and filtered[-1] in {'OF', 'THE'}:
            filtered.pop()
    
    cleaned = ' '.join(filtered).strip()
    return cleaned if cleaned else name.upper()

def jaccard_similarity(a: str, b: str) -> float:
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)

def load_rules(rules_file: str = "name_rules_v19.1.json.gz") -> Dict:
    path = Path(rules_file)
    print(f"Loading rules from {path}")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        rules = {}
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                core = item[0]
                rule = item[1] if isinstance(item[1], dict) else {}
                rules[core] = rule
            else:
                rules[str(item)] = {}
        print(f"Converted list format to dict with {len(rules):,} entries")
        return rules
    return data


def load_high_value_names(tsv_file: str = "distinct_grantee_names.tsv", top_n: int = 500) -> List[Tuple]:
    names = []
    with open(tsv_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                try:
                    name = row[0].strip()
                    count = int(row[1])
                    dollars = float(row[2])
                    names.append((name, count, dollars))
                except:
                    continue
    names.sort(key=lambda x: -x[2])
    return names[:top_n]

def analyze_name(name: str, rules: Dict, all_variants: set, priority_canonicals: List[str], pharma_patterns=None) -> Dict:
    cleaned = clean_name(name)
    if cleaned in all_variants or name.upper() in all_variants or cleaned.replace(' ', '') in [v.replace(' ', '') for v in all_variants]:
        return {
            "raw": name,
            "cleaned": cleaned,
            "best_canonical": "EXACT_MATCH_IN_RULES",
            "similarity": 1.0,
            "ein": "N/A",
            "reason": "Covered by existing rule/variant (raw or cleaned matched)"
        }
    
    # Know about the siding (per user: HIPPA/PATIENT/SEE should be handled by big_pharma_subsidy patterns without special cases)
    # This fixes the bug where full phrases still showed as uncovered.
    pharma_patterns = []
    try:
        with open("big_pharma_subsidy.json", "r", encoding="utf-8") as f:
            subsidy_data = json.load(f)
        if "BIG PHARMA SUBSIDY" in subsidy_data and "patterns" in subsidy_data["BIG PHARMA SUBSIDY"]:
            pharma_patterns = [re.compile(p, re.IGNORECASE) for p in subsidy_data["BIG PHARMA SUBSIDY"]["patterns"]]
    except:
        pass
    for pattern in pharma_patterns:
        if pattern.search(name) or pattern.search(cleaned):
            return {
                "raw": name,
                "cleaned": cleaned,
                "best_canonical": "BIG PHARMA SUBSIDY",
                "similarity": 1.0,
                "ein": "99-7777777",
                "reason": "Covered by BIG PHARMA SUBSIDY (synthetic EIN for patient subsidy/tax deduction after $1B first-pill cost - no real EIN expected)"
            }
    
    best_match = "NONE"
    best_score = 0.0
    best_ein = ""
    reason = "No good canonical match"
    
    for canon in priority_canonicals:
        canon_clean = clean_name(canon)
        score = jaccard_similarity(cleaned, canon_clean)
        if score > best_score:
            best_score = score
            best_match = canon
            if isinstance(rules.get(canon), dict):
                best_ein = rules[canon].get("ein", "")
    
    if best_score > 0.5:
        reason = f"Strong match to '{best_match}' (score {best_score:.3f})"
        if best_ein:
            reason += f" → EIN {best_ein}"
    elif best_score > 0.25:
        reason = f"Weak/partial match to '{best_match}' (score {best_score:.3f}) - likely suffix/geo issue"
    else:
        reason = f"No good match (best score {best_score:.3f}). Consider adding to SIMPLES or improving clean_name for universities."
    
    return {
        "raw": name,
        "cleaned": cleaned,
        "best_canonical": best_match,
        "similarity": round(best_score, 3),
        "ein": best_ein,
        "reason": reason
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--rules", default="name_rules_v19.1.json.gz")
    args = parser.parse_args()
    
    print("Loading rules...")
    rules = load_rules(args.rules)
    
    all_variants = set()
    priority_canonicals = list(SIMPLES) + [p for p in GOOD_SINGLE_WORD_PRIORITIES if isinstance(p, str)]
    # Load pharma patterns for siding awareness in analysis
    pharma_patterns = []
    try:
        with open("big_pharma_subsidy.json", "r", encoding="utf-8") as f:
            subsidy_data = json.load(f)
        if "BIG PHARMA SUBSIDY" in subsidy_data and "patterns" in subsidy_data["BIG PHARMA SUBSIDY"]:
            pharma_patterns = [re.compile(p, re.IGNORECASE) for p in subsidy_data["BIG PHARMA SUBSIDY"]["patterns"]]
        priority_canonicals.append("BIG PHARMA SUBSIDY")
    except Exception as e:
        print(f"Warning loading pharma patterns: {e}")
    for k in rules.keys():
        all_variants.add(str(k).upper())
        if isinstance(rules.get(k), dict) and "variants" in rules[k]:
            for v in rules[k]["variants"]:
                all_variants.add(str(v).upper())
        elif isinstance(rules.get(k), list):
            for v in rules[k]:
                all_variants.add(str(v).upper())
    
    print(f"Loaded {len(rules):,} rules. Fast lookup set size: {len(all_variants):,}")
    
    print(f"\nLoading top {args.top*3} high-value names...")
    names = load_high_value_names(top_n=args.top * 3)
    
    print(f"\n=== ANALYZE NAME SPACE v2 - Top {args.top} UNCOVERED WITH EXPLANATION ===\n")
    print(f"{'Rank':<4} {'Raw Name':<55} {'Cleaned':<30} {'Best Canonical':<30} {'Sim':<6} Reason")
    print("-" * 140)
    
    report = []
    for i, (name, count, dollars) in enumerate(names, 1):
        analysis = analyze_name(name, rules, all_variants, priority_canonicals, pharma_patterns)
        if "Covered by existing rule" not in analysis["reason"] and "Strong match" not in analysis["reason"]:
            report.append(analysis)
            print(f"{len(report):<4} {name[:53]:<55} {analysis['cleaned'][:28]:<30} {analysis['best_canonical'][:28]:<30} {analysis['similarity']:<6} {analysis['reason']}")
            if len(report) >= args.top:
                break
    
    output_file = "uncovered_high_value_detailed.tsv"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("raw_name\tcleaned_name\tbest_canonical\tsimilarity\tein\treason\tgrant_count\tdollars\n")
        for analysis in report:
            f.write(f"{analysis['raw']}\t{analysis['cleaned']}\t{analysis['best_canonical']}\t{analysis['similarity']}\t{analysis['ein']}\t{analysis['reason']}\tN/A\tN/A\n")
    
    print(f"\nWrote detailed analysis to {output_file}")
    print("This version shows *exactly* why each name is still uncovered (best canonical, similarity, reason).")
    print("Use this to guide precise SIMPLES additions or clean_name improvements.")

if __name__ == "__main__":
    main()
