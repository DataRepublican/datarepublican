import re
import json
from collections import defaultdict

RULES_JSON = 'name_rules.json'
INPUT_TSV = 'distinct_grantee_names.tsv'

print("Loading rules...")
with open(RULES_JSON, 'r', encoding='utf-8') as f:
    rules = json.load(f)  # core -> list of variants

print(f"Loaded {len(rules):,} rules from {RULES_JSON}")

print("Loading full name list from TSV (pure Python)...")
name_to_grant_count = {}
name_to_dollars = {}

with open(INPUT_TSV, 'r', encoding='utf-8') as f:
    header = f.readline().strip().split('\t')
    try:
        name_idx = header.index('grantee_name')
        count_idx = header.index('grant_count')
        dollars_idx = header.index('dollars') if 'dollars' in header else None
    except ValueError:
        print("Error: TSV must have columns 'grantee_name' and 'grant_count'")
        exit(1)

    for line_num, line in enumerate(f, 2):
        fields = line.strip().split('\t')
        if len(fields) <= name_idx:
            continue
        name = fields[name_idx].strip().upper()
        if not name:
            continue
        try:
            grant_count = int(fields[count_idx])
            dollars = float(fields[dollars_idx]) if dollars_idx is not None and fields[dollars_idx] else 0.0
        except (ValueError, IndexError):
            grant_count = 1
            dollars = 0.0
        
        name_to_grant_count[name] = grant_count
        name_to_dollars[name] = dollars

print(f"Loaded {len(name_to_grant_count):,} rows from TSV")

# Build reverse lookup for fast matching: variant -> canonical
variant_to_canonical = {}
for canonical, variants in rules.items():
    for v in variants:
        variant_to_canonical[v.upper()] = canonical

# Stats
total_names_collapsed = 0
total_grants_collapsed = 0
total_dollars_collapsed = 0.0
rule_stats = defaultdict(lambda: {'names': 0, 'grants': 0, 'dollars': 0.0})

for name, grant_count in name_to_grant_count.items():
    canonical = variant_to_canonical.get(name)
    if canonical:
        total_names_collapsed += 1
        total_grants_collapsed += grant_count
        total_dollars_collapsed += name_to_dollars.get(name, 0.0)
        
        rule_stats[canonical]['names'] += 1
        rule_stats[canonical]['grants'] += grant_count
        rule_stats[canonical]['dollars'] += name_to_dollars.get(name, 0.0)

print(f"\nTotal names that would be collapsed: {total_names_collapsed:,}")
print(f"Total grants collapsed: {total_grants_collapsed:,}")
print(f"Total dollars collapsed: ${total_dollars_collapsed:,.0f}\n")

# Top 15 rules by grant_count
print("Top 15 rules by total grant_count (most impactful):")
sorted_rules = sorted(rule_stats.items(), key=lambda x: x[1]['grants'], reverse=True)
for i, (canonical, stats) in enumerate(sorted_rules[:15], 1):
    print(f"{stats['grants']:>8,} grants | ${stats['dollars']:>14,.0f} | {stats['names']:>6,} names | '{canonical}'")

print("\nDone.")