import pandas as pd
from collections import defaultdict, Counter

# Load the distinct normalized names
df = pd.read_csv('distinct_grantee_names.tsv', sep='\t', header=None, names=['name'])
all_names = set(n.strip().upper() for n in df['name'].dropna() if n.strip())

print(f"Loaded {len(all_names):,} distinct normalized names\n")

# === Step 1: Discover top 50 prefixes and suffixes by frequency ===
print("Discovering top 50 prefixes and suffixes...")

prefix_counter = Counter()
suffix_counter = Counter()

for name in all_names:
    words = name.split()
    # Prefixes: first 1-5 words
    for i in range(1, min(6, len(words) + 1)):
        prefix = ' '.join(words[:i])
        prefix_counter[prefix] += 1
    # Suffixes: last 1-5 words
    for i in range(1, min(6, len(words) + 1)):
        suffix = ' '.join(words[-i:])
        suffix_counter[suffix] += 1

top_prefixes = [p for p, cnt in prefix_counter.most_common(50)]
top_suffixes = [s for s, cnt in suffix_counter.most_common(50)]

# === Step 2: Measure real collapse power (net reduction) ===
print("\n=== REAL PREFIX COLLAPSE POWER (sorted by merges descending) ===")
prefix_results = []
for prefix in top_prefixes:
    merges = 0
    for name in all_names:
        if name.startswith(prefix):
            stripped = name[len(prefix):].strip()
            if stripped and stripped != name and stripped in all_names:
                merges += 1
    if merges >= 5:
        prefix_results.append((merges, prefix))

for merges, prefix in sorted(prefix_results, reverse=True):
    print(f"{merges:6,} names would merge | prefix: '{prefix}'")

print("\n=== REAL SUFFIX COLLAPSE POWER (sorted by merges descending) ===")
suffix_results = []
for suffix in top_suffixes:
    merges = 0
    for name in all_names:
        if name.endswith(suffix):
            stripped = name[:-len(suffix)].strip()
            if stripped and stripped != name and stripped in all_names:
                merges += 1
    if merges >= 5:
        suffix_results.append((merges, suffix))

for merges, suffix in sorted(suffix_results, reverse=True):
    print(f"{merges:6,} names would merge | suffix: '{suffix}'")