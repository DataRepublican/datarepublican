#!/usr/bin/env python3
"""
group_bmf_university_entities.py

Algorithmic family grouping for BMF university/college slices.

Implements Option A: treat community colleges, 4-year universities, and their
satellites (foundations, alumni associations, faculty/classified/employee groups,
bookstores, ROTC units, etc.) as coherent families under a core canonical name.

Designed in the same spirit as category_splitter.py "generator" detectors:
- Keyword-driven entity typing
- Staged, regex-assisted core name extraction (strip satellites, not just blind word deletion)
- Special cases for AAUW (simple), "UNIVERSITY OF <STATE>" forms, "XXX COMMUNITY COLLEGE" forms
- Preserves proper institutional casing for seeds / canonicals

Usage (Oregon lab):
    python group_bmf_university_entities.py \
        --input bmf_OR_universities_colleges.tsv \
        --output oregon_universities_grouped_algorithmic_v2.tsv

Later:
    --input bmf_CA_universities_colleges.tsv --state CA
    (will also work on the full bmf_university_college_subset.tsv with STATE column)
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# =============================================================================
# Entity type detection (keyword sets, like category_splitter)
# =============================================================================

AAUW_KEYWORDS = [
    "AMERICAN ASSOCIATION OF UNIVERSITY WOMEN",
    "AAUW",
]

FOUNDATION_KEYWORDS = [
    "FOUNDATION",
    "SCHOLARSHIP FUND",
    "EDUCATION FUND",
    "MEMORIAL EDUCATION FUND",
]

ALUMNI_KEYWORDS = [
    "ALUMNI ASSOCIATION",
    "ALUMNI ASSOC",
    "ALUMNAE ASSOCIATION",
    "ALUMNI CHAPTER",
    "ALUMNI FREE SPEECH",
]

FACULTY_EMPLOYEE_KEYWORDS = [
    "FACULTY ASSOCIATION",
    "FACULTY ASSOC",
    "CLASSIFIED ASSOCIATION",
    "CLASSIFIED EMPLOYEES",
    "CLASSIFIED EMPLOYEE",
    "EDUCATION ASSOCIATION",
    "EMPLOYEE ASSOCIATION",
    "EMPLOYEE FEDERATION",
    "STAFF ASSOCIATION",
    "PART TIME FACULTY",
]

BOOKSTORE_KEYWORDS = ["BOOKSTORE", "BOOK STORE"]

ROTC_KEYWORDS = ["NROTC", "ROTC AT", "RESERVE OFFICERS"]

COMMUNITY_COLLEGE_MAIN_HINTS = [
    "COMMUNITY COLLEGE",
]

FOUR_YEAR_MAIN_HINTS = [
    "UNIVERSITY",
    "UNIVERSITIES",
]


def classify_entity_type(name: str) -> str:
    """Return a human-readable entity role for the row."""
    if not isinstance(name, str):
        return "Other / Unclear"

    n = name.upper()

    # AAUW is special and simple (user flagged)
    if any(kw in n for kw in AAUW_KEYWORDS):
        return "AAUW Branch"

    # Satellites (order matters: alumni before generic foundation in some edge cases)
    if any(kw in n for kw in ALUMNI_KEYWORDS):
        return "Alumni Association"

    if any(kw in n for kw in FACULTY_EMPLOYEE_KEYWORDS):
        return "Faculty / Employee Group"

    if any(kw in n for kw in FOUNDATION_KEYWORDS):
        return "Foundation / Scholarship"

    if any(kw in n for kw in BOOKSTORE_KEYWORDS):
        return "Main Institution"   # bookstore is usually operated by the institution itself

    if any(kw in n for kw in ROTC_KEYWORDS):
        return "Main Institution"

    # Main institutions
    if "UNIVERSITY" in n or "UNIVERSITIES" in n:
        # But not if it's clearly a satellite we missed above
        if not any(kw in n for kw in (FOUNDATION_KEYWORDS + ALUMNI_KEYWORDS + FACULTY_EMPLOYEE_KEYWORDS)):
            return "Main Institution"

    if "COMMUNITY COLLEGE" in n:
        # If it survived the satellite keywords, treat as main (or the CC itself)
        if not any(kw in n for kw in (FOUNDATION_KEYWORDS + ALUMNI_KEYWORDS + FACULTY_EMPLOYEE_KEYWORDS)):
            return "Community College"

    # Everything else that looked like higher-ed but didn't fit
    if any(kw in n for kw in ["COLLEGE", "INSTITUTE"]):
        return "College / Prep School"

    return "Other / Association / Misc"


# =============================================================================
# Core name extraction (the heart of the "generator-like" algorithm)
# =============================================================================

# Common trailing corporate junk to strip (case-insensitive at end)
TRAILING_JUNK_RE = re.compile(
    r'\s+(INC|LLC|CORP|CORPORATION|CO|COMPANY|INCORPORATED|LIMITED|LTD)\.?$',
    re.IGNORECASE
)

# Leading articles
LEADING_ARTICLE_RE = re.compile(r'^(THE|A|AN)\s+', re.IGNORECASE)

# Trailing pure numeric ids (e.g. "MEMORIAL EDUCATION FUND 301012")
TRAILING_NUMBER_ID_RE = re.compile(r'\s+\d{4,}$')

# Specific satellite patterns we can reliably strip to recover the core institution.
# Capture group 1 is the desired core.
SATELLITE_STRIP_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # "NROTC AT OREGON STATE UNIVERSITY" -> Oregon State University
    (re.compile(r'^(?:NROTC|ROTC)\s+(?:AT|OF)\s+(.*)$', re.IGNORECASE), 1),

    # "ALUMNI ASSOCIATION OF THE UNIVERSITY OF OREGON" or "SIGMA NU ALUMNI ... OF THE ..."
    (re.compile(r'^.*?\bALUMNI\s+(?:ASSOCIATION|ASSOC|CHAPTER).*?(?:OF|AT)\s+(THE\s+)?(.+?)(?:\s+(?:FOUNDATION|INC|LLC))?$', re.IGNORECASE), 2),

    # "XXX COMMUNITY COLLEGE FOUNDATION INC", "XXX COMMUNITY COLLEGE CLASSIFIED ASSOCIATION"
    (re.compile(r'^(.+?\bCOMMUNITY COLLEGE\b).*?(?:FOUNDATION|FACULTY|CLASSIFIED|EDUCATION|EMPLOYEE|ALUMNI|BOOKSTORE).*$', re.IGNORECASE), 1),

    # "XXX UNIVERSITY FOUNDATION", "XXX UNIVERSITY ALUMNI ASSOCIATION INC O S U"
    (re.compile(r'^(.+?\bUNIVERSITY\b).*?(?:FOUNDATION|ALUMNI|BOOKSTORE|NROTC).*$', re.IGNORECASE), 1),

    # "CLASSIFIED ASSOCIATION OF CENTRAL OREGON COMMUNITY COLLEGE" (reverse order)
    (re.compile(r'^(?:CLASSIFIED|FACULTY|EDUCATION|EMPLOYEE)\s+(?:ASSOCIATION|ASSOC|EMPLOYEES?).*?(?:OF|AT)\s+(.+?)(?:\s+(?:INC|LLC))?$', re.IGNORECASE), 1),

    # "UNIVERSITY OF OREGON FOUNDATION" etc. (the "OF <geo>" form)
    (re.compile(r'^(UNIVERSITY OF [A-Z][A-Z\s]+?)(?:\s+(?:FOUNDATION|ALUMNI|BOOKSTORE|ASSOCIATION)).*$', re.IGNORECASE), 1),

    # Generic "XXX FOUNDATION" at end for a university/college that is otherwise the whole name
    (re.compile(r'^(.+?(?:UNIVERSITY|COMMUNITY COLLEGE|COLLEGE))\s+(?:FOUNDATION|ALUMNI|BOOKSTORE).*$', re.IGNORECASE), 1),
]


def _title_case_preserve(name: str) -> str:
    """Reasonable title casing that keeps 'of', 'the', small words lower except first."""
    if not name:
        return ""
    # Simple but effective: title() then fix small words
    words = name.lower().split()
    small = {"of", "the", "and", "for", "in", "at", "on", "to", "a", "an", "by"}
    out = []
    for i, w in enumerate(words):
        if i == 0 or w not in small:
            out.append(w.capitalize())
        else:
            out.append(w)
    return " ".join(out)


def extract_core_name(raw_name: str, state: str = "OR") -> str:
    """
    Return the best core institutional name for grouping.

    This is deliberately more surgical than blind word-stripping (see oregon_grouped_algorithmic_v1.tsv).
    It mirrors the careful detectors in category_splitter.py.
    """
    if not isinstance(raw_name, str) or not raw_name.strip():
        return "Unknown"

    name = raw_name.strip()

    # 1. AAUW special case (user called this one "simple")
    upper = name.upper()
    if "AMERICAN ASSOCIATION OF UNIVERSITY WOMEN" in upper or upper.startswith("AAUW"):
        return "American Association of University Women"

    # 2. Strip easy leading / trailing noise first
    name = LEADING_ARTICLE_RE.sub("", name)
    name = TRAILING_JUNK_RE.sub("", name)
    name = TRAILING_NUMBER_ID_RE.sub("", name).strip()

    # 3. Try satellite-stripping patterns (most specific first)
    for pat, group in SATELLITE_STRIP_PATTERNS:
        m = pat.search(name)
        if m:
            candidate = m.group(group).strip()
            # Clean the captured core a bit more
            candidate = LEADING_ARTICLE_RE.sub("", candidate)
            candidate = TRAILING_JUNK_RE.sub("", candidate).strip()
            if len(candidate) >= 4:  # sanity
                return _title_case_preserve(candidate)

    # 4. Fallback: if the name itself looks like a clean main institution, keep most of it
    #    but still drop pure trailing "FOUNDATION" etc. that weren't caught.
    if re.search(r'\b(UNIVERSITY|COMMUNITY COLLEGE)\b', name, re.IGNORECASE):
        # Drop a trailing satellite word if present and nothing else was caught
        for kw in [" FOUNDATION", " ALUMNI ASSOCIATION", " BOOKSTORE INC", " BOOKSTORE"]:
            if name.upper().endswith(kw):
                name = name[: -len(kw)].strip()
                break
        return _title_case_preserve(name)

    # 5. Last resort: aggressive but safer stripping of very common trailing qualifiers
    name = re.sub(r'\s+(OF|IN|FOR|AT)\s+[A-Z][A-Za-z\s]+$', '', name, flags=re.IGNORECASE)
    return _title_case_preserve(name) or raw_name.strip().upper()


def normalize_for_grouping(name: str) -> str:
    """Uppercase key used for actual grouping / dedup of families."""
    core = extract_core_name(name)
    return core.upper()


# =============================================================================
# Main grouping logic
# =============================================================================

def group_university_entities(
    df: pd.DataFrame,
    state: str = "OR",
) -> pd.DataFrame:
    """
    Add Categorized_Institution and Entity_Type columns (and a grouping key).
    Returns a new DataFrame sorted for easy review.
    """
    df = df.copy()

    # Ensure we have the columns we expect from BMF slices
    # Raw slice often has: EIN, NAME, CITY, STATE (or 0,1,2,3 if no header)
    if "NAME" not in df.columns:
        # Try to recover from integer columns produced by read_csv without header
        if 1 in df.columns:
            df = df.rename(columns={0: "EIN", 1: "NAME", 2: "CITY", 3: "STATE"})
        elif "name" in df.columns:
            df = df.rename(columns=str.upper)

    df["NAME"] = df["NAME"].astype(str).str.strip()

    # Classify every row
    df["Entity_Type"] = df["NAME"].apply(classify_entity_type)

    # Extract core family name
    df["_core_key"] = df["NAME"].apply(lambda n: normalize_for_grouping(n))
    df["Categorized_Institution"] = df["NAME"].apply(lambda n: extract_core_name(n, state))

    # For AAUW and a few other "simple" families we can force a single canonical spelling
    aauw_mask = df["Entity_Type"] == "AAUW Branch"
    df.loc[aauw_mask, "Categorized_Institution"] = "American Association of University Women"

    # Some manual overrides / cleanups that the heuristics still miss on Oregon
    # (kept tiny and explicit so they are easy to promote to general rules)
    overrides = {
        "WARNER PACIFIC UNIVERSITY": "Warner Pacific University",
        "PACIFIC UNIVERSITY": "Pacific University",
    }
    for raw, canon in overrides.items():
        df.loc[df["NAME"].str.upper() == raw.upper(), "Categorized_Institution"] = canon

    # Compute family sizes for later filtering / display
    family_sizes = df.groupby("_core_key").size().to_dict()
    df["cluster_size"] = df["_core_key"].map(family_sizes)

    # Order output nicely: biggest families first, then by core name, then original name
    df = df.sort_values(
        ["cluster_size", "Categorized_Institution", "Entity_Type", "NAME"],
        ascending=[False, True, True, True]
    )

    # Final column order (matching the manual grouped file + extras)
    # Keep the internal _core_key for summarize_families (it is dropped for the final TSV the user sees)
    cols = ["NAME", "Categorized_Institution", "Entity_Type", "CITY", "STATE", "EIN", "cluster_size", "_core_key"]
    existing = [c for c in cols if c in df.columns]
    return df[existing].reset_index(drop=True)


def summarize_families(df: pd.DataFrame, min_size: int = 2) -> None:
    """Pretty print the families that actually grouped multiple rows (the payoff)."""
    print("\n" + "=" * 72)
    print("FAMILIES WITH 2+ MEMBERS (algorithmic grouping results)")
    print("=" * 72)

    grouped = df.groupby(["Categorized_Institution", "_core_key"], sort=False)
    families = []
    for (canon, key), g in grouped:
        size = len(g)
        if size >= min_size:
            types = g["Entity_Type"].value_counts().to_dict()
            families.append((size, canon, types, g["NAME"].tolist()[:6]))

    families.sort(reverse=True)  # biggest first

    for size, canon, type_counts, examples in families:
        print(f"\n{canon}  (family size: {size})")
        print(f"   Roles: {type_counts}")
        for ex in examples:
            print(f"     - {ex[:70]}")
        if len(examples) < size:
            print(f"     ... +{size - len(examples)} more")


def build_clean_seeds_from_families(clusters: dict, max_seeds: int = 300) -> list:
    """
    Turn the BMF family clusters into a clean list of canonicals suitable for
    --priority-canonicals in the TUI or category_splitter seeds.

    Preference order:
    - Families that actually captured satellites (alumni/foundation/faculty) in BMF
    - Then largest families overall
    - Skip obvious noise ("American College", pure "Trustees", "College" catch-alls, etc.)
    """
    scored = []
    for canon, info in clusters.items():
        n = canon.upper()
        # Skip noisy catch-alls we know about
        if "AMERICAN COLLEGE" in n and "OF" not in n and len(n) < 20:
            continue
        if n in ("TRUSTEES", "COLLEGE", "ALUMNAE ASSOCIATION", "UNIVERSITY"):
            continue
        if "YORK RITE" in n or "FEDERATION OF TEXAS A&M UNIVERSITY MOTHERS" in n:
            continue

        size = info["count"]
        types = info.get("entity_types", {})
        has_satellites = any(k in types for k in ("Alumni Association", "Foundation / Scholarship",
                                                  "Faculty / Employee Group", "AAUW Branch"))

        # Score: satellites are gold; then raw size
        score = (1 if has_satellites else 0) * 100000 + size
        scored.append((score, canon, has_satellites, size))

    scored.sort(reverse=True)
    selected = [c for _, c, _, _ in scored[:max_seeds]]

    # Always include the AAUW one if present (user specifically called it out as simple)
    if "American Association of University Women" not in selected:
        if any("AMERICAN ASSOCIATION OF UNIVERSITY WOMEN" in k.upper() for k in clusters):
            selected.insert(0, "American Association of University Women")

    # Dedup while preserving order
    seen = set()
    out = []
    for s in selected:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main():
    parser = argparse.ArgumentParser(description="Algorithmic university/college family grouping (Option A style)")
    parser.add_argument("--input", default="bmf_OR_universities_colleges.tsv",
                        help="Per-state (or full) university/college BMF slice TSV")
    parser.add_argument("--output", default="oregon_universities_grouped_algorithmic_v2.tsv",
                        help="Output grouped TSV")
    parser.add_argument("--state", default="OR", help="Two-letter state for any state-specific tweaks")
    parser.add_argument("--min-family-size", type=int, default=2,
                        help="Only show families of this size+ in the summary")
    parser.add_argument("--verify-against", default="oregon_universities_grouped.tsv",
                        help="Optional: path to the human-curated grouped file for agreement stats")
    parser.add_argument("--emit-clusters-json", default="oregon_university_families.json",
                        help="Write a clusters.json for downstream use / seeds")
    parser.add_argument("--emit-seeds", default=None,
                        help="Write a clean university_college_seeds.json in the format expected by review_suggestions_tui.py and category_splitter ({\"canonicals\": [...]})")
    parser.add_argument("--apply-to-distinct", default=None,
                        help="Path to distinct_grantee_names_clean.tsv (or similar). Will scan it using the discovered families and emit focused seeds + a filtered TSV of university-related names from the real 990 data.")
    parser.add_argument("--distinct-seeds-out", default="university_seeds_from_bmf.json",
                        help="Where to write the seeds JSON when using --apply-to-distinct")
    parser.add_argument("--distinct-filtered-out", default="distinct_grantee_university_related.tsv",
                        help="Where to write the filtered subset of distinct_grantee_names that matched the BMF university families")
    parser.add_argument("--max-seeds", type=int, default=300,
                        help="When emitting seeds from BMF families, limit to the top N largest families (plus all that have real satellites)")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    df = pd.read_csv(args.input, sep="\t")
    print(f"Loaded {len(df):,} rows")

    # If the file had no header row in the pandas sense, fix columns
    if list(df.columns)[:4] == [0, 1, 2, 3] or "EIN" not in str(df.columns[0]).upper():
        # re-read without assuming header
        df = pd.read_csv(args.input, sep="\t", header=None)
        df.columns = ["EIN", "NAME", "CITY", "STATE"]

    grouped = group_university_entities(df, state=args.state)

    # Write main output (drop internal key so the TSV matches the shape of the human-curated file)
    out_path = Path(args.output)
    public = grouped.drop(columns=["_core_key"], errors="ignore")
    public.to_csv(out_path, sep="\t", index=False)
    print(f"Wrote grouped TSV: {out_path} ({len(public)} rows)")

    # Summary of the interesting families
    summarize_families(grouped, min_size=args.min_family_size)

    # Emit machine-readable clusters (useful for seeds or Splink blocking experiments)
    clusters = {}
    if args.emit_clusters_json or args.emit_seeds or args.apply_to_distinct:
        for canon, g in grouped.groupby("Categorized_Institution"):
            clusters[canon] = {
                "count": int(len(g)),
                "entity_types": g["Entity_Type"].value_counts().to_dict(),
                "eins": g["EIN"].astype(str).tolist() if "EIN" in g.columns else [],
                "names": g["NAME"].tolist(),
            }
        if args.emit_clusters_json:
            with open(args.emit_clusters_json, "w") as f:
                json.dump({"clusters": clusters, "state": args.state}, f, indent=2)
            print(f"\nWrote clusters JSON: {args.emit_clusters_json} ({len(clusters)} unique families)")

    # Emit clean seeds in the exact format the rest of the tooling expects
    if args.emit_seeds:
        seeds = build_clean_seeds_from_families(clusters, max_seeds=args.max_seeds)
        seeds_path = Path(args.emit_seeds)
        with open(seeds_path, "w") as f:
            json.dump({"canonicals": seeds}, f, indent=2)
        print(f"Wrote clean seeds for TUI / pipeline: {seeds_path} ({len(seeds)} canonicals)")

    # The key request: take the BMF-derived families and apply them as seeds
    # against the real 990 distinct_grantee_names_clean list.
    if args.apply_to_distinct:
        print(f"\n{'='*72}")
        print(f"APPLYING BMF UNIVERSITY FAMILIES AS SEEDS TO: {args.apply_to_distinct}")
        print(f"{'='*72}")

        seeds = build_clean_seeds_from_families(clusters, max_seeds=args.max_seeds)
        print(f"Using {len(seeds)} strong BMF-derived canonicals as seeds...")

        print("Scanning distinct_grantee_names_clean (vectorized contains on top cores)...")
        distinct = pd.read_csv(args.apply_to_distinct, sep="\t")
        name_col = "grantee_name" if "grantee_name" in distinct.columns else distinct.columns[0]

        # Use the top ~200 largest/most valuable cores for matching (fast & high signal)
        top_cores = seeds[:200]
        mask = pd.Series(False, index=distinct.index)
        matched_cores = set()

        for core in top_cores:
            # Simple case-insensitive substring is fast enough and matches the spirit of the generator
            this_mask = distinct[name_col].str.contains(re.escape(core), case=False, na=False, regex=True)
            if this_mask.any():
                mask |= this_mask
                matched_cores.add(core)

        matched_df = distinct.loc[mask].copy()
        if len(matched_df) > 0:
            filtered_path = Path(args.distinct_filtered_out)
            matched_df.to_csv(filtered_path, sep="\t", index=False)
            print(f"Wrote filtered university-related names from 990 data: {filtered_path} ({len(matched_df)} rows)")

            # Emit a seeds file tuned to what actually exists in the real 990 grants
            # Include the cores + the satellite forms the BMF families proved are common
            enriched = []
            for c in sorted(matched_cores):
                enriched.append(c)
                if any(kw in c.upper() for kw in ("UNIVERSITY", "COLLEGE", "INSTITUTE")):
                    enriched.append(f"{c} FOUNDATION")
                    enriched.append(f"{c} ALUMNI ASSOCIATION")
                    enriched.append(f"ALUMNI ASSOCIATION OF {c}")
                    enriched.append(f"TRUSTEES OF {c}")
            # Preserve order + dedup
            seen = set()
            final_seeds = []
            for s in enriched:
                if s not in seen:
                    seen.add(s)
                    final_seeds.append(s)

            seeds_out = Path(args.distinct_seeds_out)
            with open(seeds_out, "w") as f:
                json.dump({"canonicals": final_seeds}, f, indent=2)
            print(f"Wrote real-990-tuned seeds: {seeds_out} ({len(final_seeds)} entries)")
            print(f"  Ready for: python review_suggestions_tui.py --priority-canonicals {seeds_out} ...")
            print(f"  Or: python splink_pattern_miner.py --use-clean-tsv {filtered_path} --priority-canonicals {seeds_out}")
        else:
            print("No matches found in the distinct file (unexpected).")

    # Optional verification against the manual curation
    verify_path = Path(args.verify_against)
    if verify_path.exists():
        print("\n" + "=" * 72)
        print("VERIFICATION vs human-curated oregon_universities_grouped.tsv")
        print("=" * 72)
        manual = pd.read_csv(verify_path, sep="\t")
        # Join on NAME
        merged = grouped[["NAME", "Categorized_Institution", "Entity_Type"]].merge(
            manual[["NAME", "Categorized_Institution", "Entity_Type"]],
            on="NAME", suffixes=("_algo", "_manual")
        )
        same_canon = (merged["Categorized_Institution_algo"] == merged["Categorized_Institution_manual"]).sum()
        same_type = (merged["Entity_Type_algo"] == merged["Entity_Type_manual"]).sum()
        total = len(merged)
        print(f"Canonical name match: {same_canon}/{total} ({100*same_canon/total:.1f}%)")
        print(f"Entity type match:    {same_type}/{total} ({100*same_type/total:.1f}%)")

        # Show the disagreements (most educational)
        disagree = merged[merged["Categorized_Institution_algo"] != merged["Categorized_Institution_manual"]]
        if len(disagree) > 0:
            print(f"\nDisagreements on canonical (showing first 8):")
            for _, r in disagree.head(8).iterrows():
                print(f"  {r.NAME[:50]:<50}")
                print(f"    algo:  {r.Categorized_Institution_algo}")
                print(f"    human: {r.Categorized_Institution_manual}")


if __name__ == "__main__":
    main()
