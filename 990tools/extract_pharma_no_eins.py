#!/usr/bin/env python3
"""
extract_pharma_no_eins.py

Takes the full (unfiltered) distinct_grantee_names.tsv and produces
a pharma_no_eins.tsv containing only rows where the grantee_name:
  - NEVER has a recipient_ein anywhere in the entire file (pure no-EIN singletons)
  - Matches the big pharma subsidy/privacy patterns from big_pharma_subsidy.json

The "never has an EIN anywhere" rule means:
  - If a name appears once with a real EIN and once without → it is excluded.
  - Only names that are always missing recipient_ein (true "will never have an EIN"
    cases like "SEE ATTACHED", "VARIOUS NEEDY PATIENTS", "HIPPA REGULATIONS...", etc.)
    are kept, then further filtered to the pharma subsidy patterns.

This is the correct input for reviewing/curating the subsidy noise that should roll
up under the synthetic "BIG PHARMA SUBSIDY" EIN, and for Splink runs that want to
stay inside the no-EIN subsidy bucket without contamination from names that sometimes
resolve to real organizations.

Usage:
    python extract_pharma_no_eins.py --input distinct_grantee_names.tsv \
        --output pharma_no_eins.tsv
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = "distinct_grantee_names.tsv"
DEFAULT_OUTPUT = "pharma_no_eins.tsv"
BIG_PHARMA_JSON = "big_pharma_subsidy.json"


def load_pharma_patterns(path: str = BIG_PHARMA_JSON):
    """Load the patterns from big_pharma_subsidy.json and compile them as regex.
    These patterns are used as real regex in the generator, so we treat them
    consistently as regex everywhere for correctness.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} not found")

    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    raw_patterns: list[str] = []
    if isinstance(data, dict):
        for _canon, info in data.items():
            if isinstance(info, dict):
                raw_patterns.extend(info.get("patterns", []))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                raw_patterns.extend(item.get("patterns", []))
            elif isinstance(item, str):
                raw_patterns.append(item)

    # Compile as regex (case-insensitive), matching how the generator uses them
    compiled = []
    for pat in raw_patterns:
        if pat:
            try:
                compiled.append(re.compile(pat, re.IGNORECASE))
            except re.error:
                # Fall back to simple substring if someone put an invalid regex
                compiled.append(pat)  # will be handled specially below

    print(f"Loaded {len(compiled)} pharma patterns from {path} (compiled as regex)")
    return compiled


def name_matches_pharma(name: str, patterns: list) -> bool:
    if not isinstance(name, str):
        return False
    for p in patterns:
        if isinstance(p, re.Pattern):
            if p.search(name):
                return True
        else:
            # fallback for any non-compiled patterns
            if p in name.upper():
                return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Extract no-EIN pharma/subsidy rows from the full distinct names TSV"
    )
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="Path to the full (unfiltered) distinct_grantee_names.tsv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="Output TSV for Splink --use-clean-tsv")
    parser.add_argument("--pharma-json", default=BIG_PHARMA_JSON)
    parser.add_argument("--include-ein-column", action="store_true",
                        help="Keep recipient_ein column in the output (default: drop it)")
    args = parser.parse_args()

    print(f"Loading full distinct names: {args.input}")
    # Let pandas follow the symlink
    df = pd.read_csv(args.input, sep="\t")
    print(f"Loaded {len(df):,} rows")

    # Identify the EIN column (we saw "recipient_ein" in the full TSV)
    ein_col = None
    for candidate in ["recipient_ein", "ein", "grant_ein", "filer_ein"]:
        if candidate in df.columns:
            ein_col = candidate
            break
    if ein_col is None:
        raise ValueError("Could not find an EIN column in the input TSV")

    print(f"Using EIN column: {ein_col}")

    # === CORRECT LOGIC: pure no-EIN singletons (name never has recipient_ein anywhere) ===
    # A name only qualifies if it has NO recipient_ein in ANY row in the entire file.
    # Names that appear once with a real EIN and once without are excluded — they are not
    # true "will never have an EIN" cases (e.g. "SEE ATTACHED" or "VARIOUS NEEDY PATIENTS").
    print("Identifying grantee_names that NEVER have a recipient_ein anywhere in the file...")
    has_ein_mask = df[ein_col].notna() & (df[ein_col].astype(str).str.strip() != "")
    names_with_any_ein = set(df.loc[has_ein_mask, "grantee_name"].astype(str).unique())
    all_names = set(df["grantee_name"].astype(str).unique())
    pure_no_ein_names = all_names - names_with_any_ein

    print(f"  Total unique grantee_names: {len(all_names):,}")
    print(f"  Names that have EIN at least once: {len(names_with_any_ein):,}")
    print(f"  Pure no-EIN names (never appear with any EIN): {len(pure_no_ein_names):,}")

    # Load patterns
    patterns = load_pharma_patterns(args.pharma_json)

    # Filter to pure no-EIN rows first, then apply pharma pattern match
    pure_df = df[df["grantee_name"].isin(pure_no_ein_names)].copy()
    pharma_mask = pure_df["grantee_name"].apply(lambda n: name_matches_pharma(n, patterns))
    result = pure_df[pharma_mask].copy()
    print(f"Final pure no-EIN + pharma matches: {len(result):,} rows ({result['grantee_name'].nunique():,} unique names)")

    # Prepare output columns
    # The Splink clean loader mainly needs grantee_name, grant_count, dollars
    # We keep the original columns by default for maximum flexibility
    cols_to_drop = [] if args.include_ein_column else [ein_col]
    out_df = result.drop(columns=cols_to_drop, errors="ignore")

    # Make sure we have a clean "grantee_name" column for the miner
    if "grantee_name" not in out_df.columns and "name" in out_df.columns:
        out_df = out_df.rename(columns={"name": "grantee_name"})

    out_path = Path(args.output)
    out_df.to_csv(out_path, sep="\t", index=False)
    print(f"\nWrote {out_path} with {len(out_df):,} rows")

    # Also emit a tiny "three-column" version that is guaranteed to work with the miner
    three_col = out_df[["grantee_name", "grant_count", "dollars"]].copy() \
        if {"grantee_name", "grant_count", "dollars"}.issubset(out_df.columns) else None
    if three_col is not None:
        three_path = out_path.with_name(out_path.stem + "_3col.tsv")
        three_col.to_csv(three_path, sep="\t", index=False)
        print(f"Also wrote minimal version for the miner: {three_path}")

    print("\nNext (dive into Splink):")
    print(f"  python splink_pattern_miner.py --use-clean-tsv {out_path} \\")
    print("      --output suggestions_pharma_no_ein.json --max-suggestions 300")


if __name__ == "__main__":
    main()
