#!/usr/bin/env python3
"""
review_suggestions_tui.py - Lightweight TUI for reviewing Splink-suggested name rules.

Features:
- Loads suggested_patterns.json
- Queries DuckDB for financial impact ($ total grant_amt per pattern)
- Sorts by descending dollar impact
- Simple Y/N prompt per item (rich table + input)
- Exports approved patterns to approved_patterns.json for merge into name_rule_constants.py

Usage:
  python review_suggestions_tui.py \
      --duckdb /path/to/irs990.duckdb \
      --suggestions suggested_patterns.json \
      --output approved_patterns.json
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

# Name cleaning for attachment suffixes (SEE ADDENDUM etc.) on real org names
try:
    from name_cleaner import clean_name_for_matching
except ImportError:
    def clean_name_for_matching(name: str) -> str:
        return name

try:
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
except ImportError:
    print("rich not installed — falling back to plain text. pip install rich")
    Console = None
    Prompt = None
    Confirm = None


def load_priority_canonicals(path: str):
    """Load priority_canonicals.json and return a set of top-level names for fast pre-bless lookup."""
    p = Path(path)
    if not p.exists():
        return set()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    canonicals = data.get("canonicals", [])
    names = set()
    for item in canonicals:
        if isinstance(item, str):
            names.add(item.upper().strip())
        elif isinstance(item, dict):
            # Use the main name if present
            if "name" in item:
                names.add(item["name"].upper().strip())
            # Also support top-level keys sometimes used
            elif "pattern" in item:
                names.add(item["pattern"].upper().strip())
    return names


def load_clean_names_tsv(path: str):
    """Load the clean names TSV for fast dollar impact + variant sampling."""
    df = pd.read_csv(path, sep="\t")
    # Expect columns like grantee_name, grant_count, dollars
    if "grantee_name" not in df.columns:
        # Try to find a reasonable name column
        for col in df.columns:
            if "name" in col.lower():
                df = df.rename(columns={col: "grantee_name"})
                break
    df["grantee_name_upper"] = df["grantee_name"].astype(str).str.upper()
    return df


def get_variants_with_dollars(clean_df: pd.DataFrame, pattern: str, max_variants: int = 5):
    """Return up to max_variants real names that match the pattern, with their dollar amounts."""
    pat = pattern.upper()
    # Simple contains match (consistent with how the generator works for simple rules)
    mask = clean_df["grantee_name_upper"].str.contains(re.escape(pat), na=False, regex=True)
    matches = clean_df[mask].copy()
    if matches.empty:
        return []
    matches = matches.sort_values("dollars", ascending=False)
    results = []
    seen = set()
    for _, row in matches.iterrows():
        name = str(row["grantee_name"])
        if name in seen:
            continue
        seen.add(name)
        results.append((name, float(row.get("dollars", 0))))
        if len(results) >= max_variants:
            break
    return results


def get_dollar_impact(clean_df: pd.DataFrame, pattern: str) -> float:
    """Fast dollar impact using the in-memory clean TSV."""
    pat = pattern.upper()
    mask = clean_df["grantee_name_upper"].str.contains(re.escape(pat), na=False, regex=True)
    return float(clean_df.loc[mask, "dollars"].sum())


def _get_name_for_sort(item):
    """Extract a string name from either a simple string or a rich canonical object."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("name") or item.get("pattern") or str(item)
    return str(item)


def _get_pattern_regex(item):
    """Return a compiled regex for matching against this canonical item."""
    if isinstance(item, str):
        return re.compile(rf"\b{re.escape(item)}\b", re.IGNORECASE)
    if isinstance(item, dict):
        patterns = item.get("patterns")
        if patterns and isinstance(patterns, list):
            # For rich objects, use the first pattern or combine them
            # For simplicity during dedup we just use the main name as fallback
            name = item.get("name") or item.get("pattern")
            if name:
                return re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        name = item.get("name") or item.get("pattern")
        if name:
            return re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    return re.compile(r"^$", re.IGNORECASE)  # never matches


def _normalize_for_dedup(name: str) -> str:
    """
    Normalize a name for deduplication comparison.
    - Strips leading articles (THE, A, AN)
    - Strips common geo suffixes (OF ..., IN ..., etc.)
    - Normalizes common singular/plural forms for organizational words.
    This makes "THE BOYS & GIRLS CLUB" match "BOYS & GIRLS CLUBS OF LOS ANGELES".
    """
    if not name:
        return ""

    upper = name.upper().strip()

    # Strip leading articles
    upper = re.sub(r'^(THE|A|AN)\s+', '', upper)

    # Strip common geo suffixes
    geo_suffix_pattern = re.compile(
        r'\s+(OF|IN|FOR|AT|BY|WITH)\s+([A-Z][A-Z\s\-]+)$', re.IGNORECASE
    )
    match = geo_suffix_pattern.search(upper)
    if match:
        upper = upper[:match.start()].strip()

    # Normalize some common singular/plural organizational words
    plural_map = {
        "CLUBS": "CLUB",
        "CENTERS": "CENTER",
        "HOSPITALS": "HOSPITAL",
        "SCHOOLS": "SCHOOL",
        "CHURCHES": "CHURCH",
        "TEMPLES": "TEMPLE",
        "LIBRARIES": "LIBRARY",
        "FOUNDATIONS": "FOUNDATION",
        "ASSOCIATIONS": "ASSOCIATION",
        "SOCIETIES": "SOCIETY",
        "UNIONS": "UNION",
        "LEAGUES": "LEAGUE",
    }

    words = upper.split()
    normalized_words = []
    for w in words:
        normalized_words.append(plural_map.get(w, w))

    return " ".join(normalized_words)


def _item_matches_any_norm(item, norms):
    """
    Return True if either the main pattern or any of its review_variants
    (after normalization) matches any of the given normalized patterns.
    This is critical for absorption after Y/M/S decisions to prevent repeats.
    """
    if not item or not norms:
        return False

    main_pat = _get_name_for_sort(item)
    main_norm = _normalize_for_dedup(main_pat)
    for sn in norms:
        if sn in main_norm or main_norm in sn or sn == main_norm:
            return True

    for v in item.get("review_variants", []):
        vname = v[0] if isinstance(v, (list, tuple)) else str(v)
        vn = _normalize_for_dedup(vname)
        for sn in norms:
            if sn in vn or vn in sn or sn == vn:
                return True
    return False


def _add_simple_to_file_and_session(core: str, session_norms_set: set, approved_list: list):
    """Add a core simple to approved_simples.json and the current session."""
    core = core.strip()
    if not core:
        return
    simples_path = Path("approved_simples.json")
    data = {"canonicals": []}
    if simples_path.exists():
        try:
            with open(simples_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"canonicals": []}

    cans = data.setdefault("canonicals", [])
    if core not in cans:
        cans.append(core)
        cans.sort()
        with open(simples_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"  → Added '{core}' to approved_simples.json")

    norm = _normalize_for_dedup(core)
    session_norms_set.add(norm)


def _collect_entries(prompt: str, console=None, default: str = "") -> list[str]:
    """
    Collect one or more entries for M or S.
    Primary intended way: comma-separated on a single line (what used to work).
    Bonus: one per line, blank line to finish.
    """
    print(f"{prompt}")
    if default:
        print(f"  (default: {default})")
    print("  Comma-separated on one line (recommended), or one per line + blank to finish.")

    entries = []
    first = True
    while True:
        try:
            if console:
                line = console.input("> " if not first else f"{prompt}: ").strip()
            else:
                line = input("> " if not first else f"{prompt}: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        first = False
        if not line:
            break
        for part in line.split(","):
            p = part.strip()
            if p:
                entries.append(p)
    if not entries and default:
        entries = [default]
    return entries


def clean_proposed_pattern(pattern: str) -> str:
    """
    Early smart cleanup pass run on *all* Splink-proposed rules before dedup/review.

    Strips:
      - Leading articles (THE, A, AN)
      - Common trailing geo/qualifier phrases (OF ..., IN ..., FOR ..., etc.)

    Also normalizes common organizational plurals (CLUBS -> CLUB, etc.).

    The result becomes the new "pattern" for:
      - Grouping / global dedup
      - What is shown in the TUI tables
      - What gets written into approved_patterns.json

    This directly attacks the "<name> and THE <name>" problem the user reported
    by making the proposed canonical forms the short clean versions the project wants
    (e.g. "SALVATION ARMY" instead of "THE SALVATION ARMY OF NEW YORK").
    """
    if not pattern:
        return ""

    p = str(pattern).strip()

    # Strip leading articles (case-insensitive, preserve rest of casing)
    p = re.sub(r'(?i)^(THE|A|AN)\s+', '', p)

    # Strip common trailing geo / qualifier suffixes (case-insensitive)
    # Matches things like " OF FOO", " IN BAR", " OF THE BAZ REGION" at end
    p = re.sub(
        r'(?i)\s+(OF|IN|FOR|AT|BY|WITH)\s+[A-Za-z][A-Za-z0-9\s\-\&\.\,\']+$',
        '',
        p
    )

    # Normalize plurals (case-insensitive match, keep reasonable casing on output)
    plural_map = {
        "CLUBS": "CLUB",
        "CENTERS": "CENTER",
        "HOSPITALS": "HOSPITAL",
        "SCHOOLS": "SCHOOL",
        "CHURCHES": "CHURCH",
        "TEMPLES": "TEMPLE",
        "LIBRARIES": "LIBRARY",
        "FOUNDATIONS": "FOUNDATION",
        "ASSOCIATIONS": "ASSOCIATION",
        "SOCIETIES": "SOCIETY",
        "UNIONS": "UNION",
        "LEAGUES": "LEAGUE",
    }

    words = p.split()
    normalized_words = []
    for w in words:
        upper_w = w.upper()
        if upper_w in plural_map:
            singular = plural_map[upper_w]
            # Try to preserve title-like casing
            if w and w[0].isupper():
                normalized_words.append(singular[0].upper() + singular[1:].lower() if len(singular) > 1 else singular)
            else:
                normalized_words.append(singular.lower())
        else:
            normalized_words.append(w)

    cleaned = " ".join(normalized_words).strip()

    # Final safety: if we stripped everything, fall back to original (rare)
    if not cleaned:
        return str(pattern).strip().upper()

    # User request: force all cleaned patterns to UPPER for consistency
    # in review display, dedup keys, and approved_patterns.json output.
    return cleaned.upper()


def dedup_canonicals(canonicals):
    """
    GLOBAL deduplication pass (no longer relies on sort adjacency).

    1. Groups every item by its normalized key (_normalize_for_dedup).
       This key strips leading THE/A/AN, trailing geo (OF/IN/...), and normalizes
       common plurals.  As a result "SALVATION ARMY", "THE SALVATION ARMY OF FOO",
       "SALVATION ARMY OF BAR", and "SALVATION ARMIES" all collapse to the same bucket.

    2. Within each bucket, selects the single best representative:
       - Highest dollar_impact (when present on enriched suggestion items)
       - Then richest dict object (most keys / most data)
       - Then shortest raw name as tie-breaker
       Extra data from siblings is merged into the winner when possible.

    3. Optional lightweight pairwise cleanup on the already-reduced list
       (containment checks) — cheap even at 1000 items ("1000x1000 isn't too bad").

    This is called both:
      - Early on the enriched Splink suggestions (to shrink the review queue)
      - At the very end when writing the final approved_patterns.json (to keep
        the merged output clean)

    Combined with the early clean_proposed_pattern() pass, this eliminates the
    "<name> and then THE <name>" problem the user reported.
    """
    if not canonicals:
        return []

    # --- Phase 1: group by normalized key (the real global step) ---
    from collections import defaultdict
    groups = defaultdict(list)

    for item in canonicals:
        raw_name = _get_name_for_sort(item)
        norm_key = _normalize_for_dedup(raw_name)
        if norm_key:
            groups[norm_key].append(item)
        else:
            # Keep un-normalizable items as-is (very rare)
            groups[f"__RAW__{raw_name}"].append(item)

    deduped = []

    for norm_key, group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Choose the best representative from the group
        best = None
        best_score = -1.0

        for it in group:
            score = 0.0
            raw = _get_name_for_sort(it)

            if isinstance(it, dict):
                score += 100.0
                # Dollar impact is the strongest signal for "most important" canonical
                if "dollar_impact" in it:
                    score += min(float(it.get("dollar_impact", 0)) / 5000.0, 80.0)
                # Richer objects win
                score += len(it) * 3.0
            else:
                score += 10.0

            # Slight preference for shorter names (project philosophy)
            score -= len(raw) * 0.05

            if score > best_score:
                best_score = score
                best = it

        # Merge any extra data from the other members into the winner (when dict)
        if isinstance(best, dict):
            for other in group:
                if other is best:
                    continue
                if isinstance(other, dict):
                    for k, v in other.items():
                        if k not in best or not best.get(k):
                            best[k] = v
                # If other is a bare string pattern, we already have the pattern field

        deduped.append(best)

    # --- Phase 2: lightweight global pairwise containment pass on the reduced set ---
    # This catches any cross-bucket cases the strict normalize key missed
    # (e.g. two norms where one is a clear substring of the other).
    # With the early clean_proposed_pattern + grouping, this pass is usually tiny.
    final = []
    used = [False] * len(deduped)

    for i, a in enumerate(deduped):
        if used[i]:
            continue
        name_a = _get_name_for_sort(a)
        norm_a = _normalize_for_dedup(name_a)

        merged_into_a = a
        for j in range(i + 1, len(deduped)):
            if used[j]:
                continue
            b = deduped[j]
            name_b = _get_name_for_sort(b)
            norm_b = _normalize_for_dedup(name_b)

            if (norm_a == norm_b or
                norm_a in norm_b or
                norm_b in norm_a or
                norm_a in name_b.upper() or
                norm_b in name_a.upper()):
                # Merge b into a
                if isinstance(merged_into_a, dict) and isinstance(b, dict):
                    for k, v in b.items():
                        if k not in merged_into_a or not merged_into_a.get(k):
                            merged_into_a[k] = v
                elif isinstance(b, dict) and not isinstance(merged_into_a, dict):
                    merged_into_a = b
                used[j] = True

        final.append(merged_into_a)
        used[i] = True

    # Re-sort the final list by dollar impact (desc) when available, otherwise by name
    final.sort(
        key=lambda x: (
            -float(x.get("dollar_impact", 0)) if isinstance(x, dict) else 0.0,
            _get_name_for_sort(x).upper()
        )
    )

    return final


def run_interactive_near_dupe(items, console=None):
    """
    Lightweight interactive Near Dupe pass.
    Runs after automatic dedup, before main review.

    Focuses on remaining very close pairs (especially singular/plural and
    minor "OF ..." variations that the auto dedup left behind).

    Presents them simply as over/under with cluster size / variant count.
    Defaults to merging into the shorter name.
    Does not write any file — only applies merges in memory and prints a summary.
    """
    if not items or len(items) < 2:
        return items

    working = list(items)
    working.sort(key=lambda x: _get_name_for_sort(x).upper())

    i = 0
    merges_performed = 0

    while i < len(working) - 1:
        a = working[i]
        b = working[i + 1]

        name_a = _get_name_for_sort(a)
        name_b = _get_name_for_sort(b)
        norm_a = _normalize_for_dedup(name_a)
        norm_b = _normalize_for_dedup(name_b)

        if norm_a == norm_b or norm_a in norm_b or norm_b in norm_a:
            size_a = a.get("cluster_size", 0) if isinstance(a, dict) else 0
            size_b = b.get("cluster_size", 0) if isinstance(b, dict) else 0

            print(f"\n--- Near Dupe Candidate ---")
            print(f"  A: {name_a}  (variants: {size_a})")
            print(f"  B: {name_b}  (variants: {size_b})")

            shorter = name_a if len(name_a) <= len(name_b) else name_b
            print(f"  Default: Merge into shorter → {shorter}")

            if console and Prompt is not None:
                choice = Prompt.ask(
                    "Merge? [Y]es / [N]o / [S]wap / [M]odify / [Q]uit",
                    default="y",
                    choices=["y", "n", "s", "m", "q"],
                    show_choices=False
                ).lower()
            else:
                choice = input("Merge? [Y/n/s/m/q] ").strip().lower() or "y"

            if choice == "q":
                break
            elif choice in ("y", ""):
                if len(name_a) <= len(name_b):
                    working[i] = _merge_two_items(a, b)
                    del working[i + 1]
                else:
                    working[i] = _merge_two_items(b, a)
                    del working[i + 1]
                merges_performed += 1
            elif choice == "n":
                i += 1
            elif choice == "s":
                if len(name_a) <= len(name_b):
                    working[i] = _merge_two_items(b, a)
                    del working[i + 1]
                else:
                    working[i] = _merge_two_items(a, b)
                    del working[i + 1]
                merges_performed += 1
            elif choice == "m":
                new_name = Prompt.ask("Desired canonical name", default=shorter) if (console and Prompt) else input(f"Desired name [{shorter}]: ").strip() or shorter
                if isinstance(a, dict):
                    a = dict(a)
                    a["pattern"] = new_name
                working[i] = a
                del working[i + 1]
                merges_performed += 1
            else:
                i += 1
        else:
            i += 1

    if merges_performed > 0:
        print(f"\nNear Dupe pass: Merged {merges_performed} close pairs in memory.")
    else:
        print("\nNear Dupe pass: No additional merges.")

    return working


def _merge_two_items(keep, drop):
    if isinstance(keep, dict) and isinstance(drop, dict):
        for k, v in drop.items():
            if k not in keep or not keep.get(k):
                keep[k] = v
        return keep
    elif isinstance(keep, dict):
        return keep
    elif isinstance(drop, dict):
        return drop
    else:
        return keep if len(str(keep)) <= len(str(drop)) else drop


def get_impact(con: duckdb.DuckDBPyConnection, pattern: str, grants_table: str = "Grants") -> float:
    """Return total grant_amt for names matching the pattern (case-insensitive contains)."""
    sql = f"""
        SELECT COALESCE(SUM(grant_amt), 0)
        FROM {grants_table}
        WHERE UPPER(grantee_name) LIKE ?
    """
    like = f"%{pattern.upper()}%"
    return float(con.execute(sql, [like]).fetchone()[0])

def main():
    parser = argparse.ArgumentParser(description="Review Splink name canonicalization suggestions")
    parser.add_argument("--suggestions", default="suggested_patterns.json",
                        help="JSON file produced by splink_pattern_miner.py")
    parser.add_argument("--priority-canonicals", default="priority_canonicals.json",
                        help="Existing priority_canonicals.json for pre-blessing during this review (still useful per-bucket)")
    parser.add_argument("--clean-names-tsv", default="distinct_grantee_names_clean.tsv",
                        help="Clean names TSV for fast variant + dollar lookups")
    parser.add_argument("--output", default="approved_from_review.json",
                        help="Output file for items approved in *this* session. Use a bucket-specific name (e.g. approved_pure_no_ein_high_value.json) to keep buckets separate.")
    parser.add_argument("--merge-existing-priority", action="store_true",
                        help="Legacy behavior: load --priority-canonicals, append this session's approvals, dedup, and write the merged result. Off by default so buckets stay separate.")
    parser.add_argument("--redaction-patterns", default=None,
                        help="Path to big_pharma_subsidy.json (or similar patterns file). Any suggestion whose 'pattern' matches one of the loaded patterns (case-insensitive contains) will be dropped before review. Useful for no-EIN subsidy/redaction buckets.")
    parser.add_argument("--exclude-approved", "--exclude-patterns", default=None,
                        help="Path to approved_*.json from a previous review of this bucket. Suggestions matching these canonicals will be dropped before review. Enables clean second-pass iteration.")
    parser.add_argument("--auto-approve", action="append", default=None,
                        help="Auto-approve any suggestions whose pattern matches this regex (case-insensitive). Can be given multiple times.")
    parser.add_argument("--max-review", type=int, default=None,
                        help="Only review the first N suggestions (for batching)")
    args = parser.parse_args()

    console = Console() if Console else None

    # Load suggestions
    with open(args.suggestions, "r", encoding="utf-8") as f:
        report = json.load(f)
    suggestions = report.get("suggestions", [])
    if not suggestions:
        print("No suggestions found.")
        return

    # Clean attachment suffixes on suggestion patterns (e.g. "Foundation - SEE ADDENDUM...")
    # so the reviewer sees and works with the real core name.
    for s in suggestions:
        if "pattern" in s and isinstance(s["pattern"], str):
            s["pattern"] = clean_name_for_matching(s["pattern"])
        if "name" in s and isinstance(s["name"], str):
            s["name"] = clean_name_for_matching(s["name"])

    if args.max_review:
        suggestions = suggestions[:args.max_review]

    # === Redaction pattern filtering (if requested) ===
    if args.redaction_patterns:
        redaction_patterns = []
        try:
            with open(args.redaction_patterns, encoding="utf-8") as f:
                rdata = json.load(f)
            for v in rdata.values():
                if isinstance(v, dict):
                    for pat in v.get("patterns", []):
                        if pat:
                            try:
                                redaction_patterns.append(re.compile(pat, re.IGNORECASE))
                            except re.error:
                                redaction_patterns.append(pat)
        except Exception as e:
            print(f"Warning: Could not load redaction patterns from {args.redaction_patterns}: {e}")

        if redaction_patterns:
            before = len(suggestions)
            kept = []
            for s in suggestions:
                pat = s.get("pattern", "")
                matched = False
                for rp in redaction_patterns:
                    if isinstance(rp, re.Pattern):
                        if rp.search(pat):
                            matched = True
                            break
                    else:
                        if rp in pat.upper():
                            matched = True
                            break
                if not matched:
                    kept.append(s)
            suggestions = kept
            dropped = before - len(suggestions)
            print(f"Redaction filter: dropped {dropped:,} items matching known subsidy patterns from {args.redaction_patterns}. {len(suggestions):,} left for review.")

    # === Bucket approved exclusion (for iterative second-pass reviews) ===
    if args.exclude_approved:
        try:
            with open(args.exclude_approved, encoding="utf-8") as f:
                edata = json.load(f)
            if isinstance(edata, dict) and "canonicals" in edata:
                exclusions = [str(x).upper() for x in edata["canonicals"] if x]
            else:
                exclusions = []
                for v in (edata.values() if isinstance(edata, dict) else []):
                    if isinstance(v, dict):
                        exclusions.extend([str(x).upper() for x in v.get("patterns", []) if x])
                    elif isinstance(v, str):
                        exclusions.append(v.upper())
        except Exception as e:
            print(f"Warning: Could not load exclude-approved from {args.exclude_approved}: {e}")
            exclusions = []

        if exclusions:
            before = len(suggestions)
            kept = []
            for s in suggestions:
                pat = s.get("pattern", "").upper()
                if not any(ex in pat for ex in exclusions):
                    kept.append(s)
            suggestions = kept
            dropped = before - len(suggestions)
            print(f"Bucket exclusion: dropped {dropped:,} items already approved in previous pass from {args.exclude_approved}. {len(suggestions):,} left for review.")

    # Auto-approve (applied after other filters)
    auto_approve_patterns = []
    if args.auto_approve:
        for pat in args.auto_approve:
            if pat:
                try:
                    auto_approve_patterns.append(re.compile(pat, re.IGNORECASE))
                except re.error:
                    auto_approve_patterns.append(pat)

    # Apply auto-approve early so they don't clutter the manual review queue
    if auto_approve_patterns:
        before = len(suggestions)
        kept = []
        auto_approved = []
        for s in suggestions:
            pat = s.get("pattern", "")
            matched = False
            for ap in auto_approve_patterns:
                if isinstance(ap, re.Pattern):
                    if ap.search(pat):
                        matched = True
                        break
                else:
                    if ap in pat.upper():
                        matched = True
                        break
            if matched:
                auto_approved.append(s)
            else:
                kept.append(s)
        suggestions = kept
        if auto_approved:
            print(f"Auto-approve: automatically blessed {len(auto_approved):,} items matching --auto-approve patterns.")
            # We'll add them to approved at the end or treat them specially; for simplicity we still show them lightly or skip manual review
            # For now we just drop them from the manual queue (they are still valuable)
            # In a fuller restoration we would mark them approved without showing.

    # Load priority canonicals for pre-blessing
    raw_priority_names = load_priority_canonicals(args.priority_canonicals)
    # Normalize them for better matching (strip leading THE/A/AN, geo suffixes, etc.)
    priority_names = {_normalize_for_dedup(name) for name in raw_priority_names if _normalize_for_dedup(name)}
    print(f"Loaded {len(priority_names):,} normalized names from priority_canonicals for pre-blessing.")

    # Load clean names TSV for fast lookups
    clean_df = load_clean_names_tsv(args.clean_names_tsv)
    print(f"Loaded {len(clean_df):,} clean names for variant/dollar lookups.")

    # Enrich suggestions with dollar impact + sample variants
    print("Enriching suggestions with dollar impact and variants (using clean TSV)...")
    enriched = []
    for s in suggestions:
        impact = get_dollar_impact(clean_df, s["pattern"])
        variants = get_variants_with_dollars(clean_df, s["pattern"], max_variants=5)
        s["dollar_impact"] = impact
        s["review_variants"] = variants
        enriched.append(s)

    # Sort by dollar impact (computed on the original rich Splink proposals — best signal)
    enriched.sort(key=lambda x: x.get("dollar_impact", 0), reverse=True)

    # === Smart early cleanup pass on ALL proposed rules (user request) ===
    # Strips leading THE/A/AN + trailing OF/IN/... + normalizes plurals on the
    # "pattern" field itself.  This is what the reviewer sees and what ends up in
    # approved_patterns.json.  Combined with the global dedup below, it kills the
    # "<name> and then THE <name>" duplication the user reported.
    print("Applying smart cleanup pass to proposed patterns (strip leading THE, trailing OF/..., plurals)...")
    cleaned_count = 0
    for s in enriched:
        orig = s.get("pattern", "")
        cleaned = clean_proposed_pattern(orig)
        if cleaned and cleaned.upper() != orig.upper():
            s["_original_pattern"] = orig  # lightweight audit trail (not written to final JSON)
            s["pattern"] = cleaned
            cleaned_count += 1
    print(f"  Cleaned {cleaned_count:,} patterns — short canonical forms now used for review & output.")

    # Run automatic dedup first (now GLOBAL + sees already-cleaned short patterns)
    print(f"\nRunning automatic dedup on {len(enriched):,} suggestions...")
    enriched = dedup_canonicals(enriched)
    print(f"After automatic dedup: {len(enriched):,} items.")

    # Run interactive Near Dupe pass (before main review)
    enriched = run_interactive_near_dupe(enriched, console)

    # === Post-dedup + post-near-dupe pre-bless filter ===
    # Anything that normalizes to something already in priority_canonicals is removed
    # from the queue entirely.  The user asked for aggressive automatic handling so they
    # stop seeing "<name> and then THE <name>" of things they've already blessed.
    # (The per-item is_preblessed logic in the loop remains as a belt-and-suspenders.)
    before_filter = len(enriched)

    def _is_already_blessed(item):
        p = _get_name_for_sort(item) if not isinstance(item, str) else item
        np = _normalize_for_dedup(p)
        return any(
            norm_p in np or re.search(rf'\b{re.escape(norm_p)}\b', np, re.IGNORECASE)
            for norm_p in priority_names
        )

    enriched = [s for s in enriched if not _is_already_blessed(s)]
    skipped = before_filter - len(enriched)
    if skipped > 0:
        print(f"Pre-bless filter: removed {skipped:,} items already in priority_canonicals "
              f"(via normalized match). {len(enriched):,} left for human review.")
    else:
        print(f"Pre-bless filter: no additional items matched existing priority_canonicals.")

    approved = []
    modified_items = []
    session_norms = set()  # normalized forms approved or introduced during this review session

    print(f"\nReviewing {len(enriched):,} suggestions (sorted by $ impact).")
    print("Controls: [Y]es  [N]o  [M]odify  [S]imple  [Q]uit & save")
    print("  M/S support multiple: one per line (blank line to finish) or comma-separated.\n")

    for i, s in enumerate(enriched, 1):
        pattern = s["pattern"]
        impact = s.get("dollar_impact", 0)

        # Pre-bless check using the same normalization as Near Dupe (strips leading THE/A/AN, geo suffixes, etc.)
        norm_pattern = _normalize_for_dedup(pattern)
        is_preblessed = any(
            norm_p in norm_pattern or 
            re.search(rf'\b{re.escape(norm_p)}\b', norm_pattern, re.IGNORECASE)
            for norm_p in priority_names
        )

        title = f"Suggestion {i}/{len(enriched)} — ${impact:,.0f}"
        if is_preblessed:
            title += "  [ALREADY IN PRIORITY_CANONICALS]"

        table = Table(title=title)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Type", s.get("type", ""))
        table.add_row("Pattern", pattern)
        table.add_row("Cluster Size", str(s.get("cluster_size", "")))
        if s.get("review_variants"):
            var_str = "  |  ".join(f"{name} ({int(dol):,})" for name, dol in s["review_variants"])
            table.add_row("Top Variants ($)", var_str)

        if console:
            console.print(table)
        else:
            print(f"\n[{i}/{len(enriched)}] ${impact:,.0f} | {pattern}")
            if s.get("review_variants"):
                print("  Variants: " + " | ".join(f"{name} ({int(dol):,})" for name, dol in s["review_variants"]))

        # Prompt - Y/N/M/Q
        if is_preblessed:
            default_choice = "y"
            prompt_text = "Already in priority_canonicals — [Y]es / [N]o / [M]odify / [S]imple / [Q]uit? "
        else:
            default_choice = "n"
            prompt_text = "[Y]es / [N]o / [M]odify / [S]imple / [Q]uit? "

        choice = None
        if console and Prompt is not None:
            try:
                choice = Prompt.ask(
                    prompt_text,
                    default=default_choice,
                    choices=["y", "n", "m", "s", "q"],
                    show_choices=False
                ).strip().lower()
            except Exception:
                choice = None
        else:
            choice = input(prompt_text).strip().lower()

        if choice == "q":
            break
        elif choice == "y" or (choice == "" and default_choice == "y"):
            approved.append(s)
            session_norms.add(norm_pattern)
        elif choice == "m":
            # Multi-entry support for Modify
            entries = _collect_entries("Modified pattern(s) — first applies here, extras as additional simples", console, default=pattern)

            if not entries:
                entries = [pattern]

            new_pattern = entries[0]
            s["pattern"] = new_pattern
            approved.append(s)

            # Re-test remaining against the new primary pattern
            norm_new = _normalize_for_dedup(new_pattern)
            absorbed = []
            for j in range(len(enriched) - 1, i, -1):
                other = enriched[j]
                other_pat = _get_name_for_sort(other)
                norm_other = _normalize_for_dedup(other_pat)
                if norm_new == norm_other or norm_new in norm_other or norm_other in norm_new:
                    absorbed.append(other)
                    del enriched[j]

            if absorbed:
                print(f"  → Also absorbed {len(absorbed)} remaining suggestion(s) under the new pattern '{new_pattern}'")
                approved.extend(absorbed)

            session_norms.add(norm_new)

            # Register any extra entries as additional simples + immediate absorption
            if len(entries) > 1:
                extras = entries[1:]
                print(f"  → Registering {len(extras)} additional simple(s): {', '.join(extras)}")
                for extra in extras:
                    _add_simple_to_file_and_session(extra, session_norms, approved)

                # Also absorb against the new simples right now
                extra_absorbed = []
                for j in range(len(enriched) - 1, i, -1):
                    other = enriched[j]
                    if _item_matches_any_norm(other, session_norms):
                        extra_absorbed.append(other)
                        del enriched[j]
                if extra_absorbed:
                    print(f"  → Also absorbed {len(extra_absorbed)} item(s) matching the additional simples")
                    approved.extend(extra_absorbed)

            # Final safety rescan
            safety_absorbed = []
            for j in range(len(enriched) - 1, i, -1):
                other = enriched[j]
                other_pat = _get_name_for_sort(other)
                other_norm = _normalize_for_dedup(other_pat)
                if any(sn in other_norm or other_norm in sn or sn == other_norm for sn in session_norms):
                    safety_absorbed.append(other)
                    del enriched[j]

            if safety_absorbed:
                print(f"  → Safety rescan absorbed {len(safety_absorbed)} additional item(s).")
                approved.extend(safety_absorbed)

        elif choice == "s":
            # Multi-entry support for Simple
            cores = _collect_entries("Core simple name(s) to add to approved_simples.json", console, default=pattern)

            if cores:
                print(f"  → Registering {len(cores)} simple(s): {', '.join(cores)}")
                for core in cores:
                    _add_simple_to_file_and_session(core, session_norms, approved)

                approved.append(s)
                norm_new = _normalize_for_dedup(cores[0]) if cores else norm_pattern
                session_norms.add(norm_new)

                # Absorb matches for the new simples
                absorbed = []
                for j in range(len(enriched) - 1, i, -1):
                    other = enriched[j]
                    if _item_matches_any_norm(other, session_norms):
                        absorbed.append(other)
                        del enriched[j]

                if absorbed:
                    print(f"  → Absorbed {len(absorbed)} item(s) matching the new simple(s)")
                    approved.extend(absorbed)

                # Safety rescan
                safety_absorbed = []
                for j in range(len(enriched) - 1, i, -1):
                    other = enriched[j]
                    other_norm = _normalize_for_dedup(_get_name_for_sort(other))
                    if any(sn in other_norm or other_norm in sn or sn == other_norm for sn in session_norms):
                        safety_absorbed.append(other)
                        del enriched[j]

                if safety_absorbed:
                    print(f"  → Safety rescan absorbed {len(safety_absorbed)} additional item(s).")
                    approved.extend(safety_absorbed)

        # else: 'n' or anything else → skip

    # Build merged output in the same format as priority_canonicals.json
    # Load existing priority_canonicals to preserve richness
    merged_canonicals = []
    priority_path = Path(args.priority_canonicals)
    if priority_path.exists():
        with open(priority_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        merged_canonicals.extend(existing.get("canonicals", []))

    # Add newly approved items
    for item in approved:
        pat = item.get("pattern")
        if pat:
            merged_canonicals.append(pat)

    # Run deduplication (same strategy as generate_name_rules.py)
    print(f"\nRunning dedup pass on {len(merged_canonicals):,} canonicals...")
    deduped = dedup_canonicals(merged_canonicals)
    print(f"Deduped down to {len(deduped):,} canonicals.")

    output_data = {
        "comment": f"Merged from Splink suggestions + existing priority_canonicals. Deduplicated. Generated by review_suggestions_tui.py",
        "canonicals": deduped
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nSaved merged + deduplicated file with {len(deduped):,} canonicals to {args.output}")
    print("You can now copy this over priority_canonicals.json when ready, or load it directly in generate_name_rules.py.")


if __name__ == "__main__":
    main()
