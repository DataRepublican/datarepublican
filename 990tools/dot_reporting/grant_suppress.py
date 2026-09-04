#!/usr/bin/env python3
"""Name-suppressed / privacy / rollup grantee filter (big_pharma_subsidy.json).

These are not real payees — SEE ATTACHED, VARIOUS, HIPPA, patient rollups, etc.
Grant $ ranking and detail lists should exclude them so real grantees surface.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "big_pharma_subsidy.json"


@lru_cache(maxsize=2)
def load_suppressed_patterns(path: str | None = None) -> tuple[re.Pattern[str], ...]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return ()
    data = json.loads(p.read_text(encoding="utf-8"))
    raw = data.get("BIG PHARMA SUBSIDY", data)
    patterns = raw.get("patterns") if isinstance(raw, dict) else None
    if not patterns:
        return ()
    compiled: list[re.Pattern[str]] = []
    for pat in patterns:
        try:
            compiled.append(re.compile(str(pat), re.IGNORECASE))
        except re.error:
            # Fall back to literal substring match
            compiled.append(re.compile(re.escape(str(pat)), re.IGNORECASE))
    return tuple(compiled)


def is_suppressed_grantee(name: str | None, path: str | None = None) -> bool:
    if not name or not str(name).strip():
        return False
    text = str(name)
    for rx in load_suppressed_patterns(path):
        if rx.search(text):
            return True
    return False


def filter_grants(
    grants: list[dict],
    *,
    name_key: str = "grantee_name",
    path: str | None = None,
) -> list[dict]:
    """Drop name-suppressed rows; preserve order."""
    return [g for g in grants if not is_suppressed_grantee(g.get(name_key), path)]


def _duckdb_safe_pattern(pat: str) -> str | None:
    """Return a pattern safe for DuckDB regexp_matches, or None to skip.

    DuckDB uses RE2-ish semantics and rejects lookbehind/lookahead and many
    Perl extensions. Python-side ``is_suppressed_grantee`` still applies the
    full pattern set on detail lists.
    """
    if not pat or not pat.strip():
        return None
    # Drop lookaround groups (DuckDB/RE2); keep the rest so (?<!C)ATCH → ATCH
    pat = re.sub(r"\(\?<[=!][^)]*\)", "", pat)
    pat = re.sub(r"\(\?[=!][^)]*\)", "", pat)
    # Reject remaining inline flags other than non-capturing groups
    if re.search(r"\(\?(?![:])", pat):
        return None
    if "(?P" in pat or "(?>" in pat:
        return None
    # Must be valid Python regex and balanced parens (proxy for DuckDB)
    try:
        re.compile(pat)
    except re.error:
        return None
    # Balance check on unescaped ()
    depth = 0
    esc = False
    for ch in pat:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0:
        return None
    return pat


def suppressed_sql_predicate(column_sql: str = "g.grantee_name") -> str:
    """DuckDB SQL: TRUE when name is *not* suppressed (keep row).

    Single case-insensitive alternation of DuckDB-safe patterns (faster than
    100+ AND clauses). Lookaround / invalid patterns are skipped; Python still
    filters detail lists with the full set.
    """
    p = DEFAULT_PATH
    if not p.exists():
        return "TRUE"
    data = json.loads(p.read_text(encoding="utf-8"))
    raw = data.get("BIG PHARMA SUBSIDY", data)
    patterns = [str(x) for x in (raw.get("patterns") or [])]
    alts: list[str] = []
    for pat in patterns:
        safe = _duckdb_safe_pattern(pat)
        if not safe:
            continue
        esc = safe.replace("'", "''")
        alts.append(f"(?:{esc})")
    if not alts:
        return "TRUE"
    joined = "|".join(alts)
    return f"NOT regexp_matches(COALESCE({column_sql}, ''), '{joined}', 'i')"


def is_suppressed_sql(column_sql: str = "g.grantee_name") -> str:
    """DuckDB SQL: TRUE when the name matches a subsidy / privacy pattern."""
    keep = suppressed_sql_predicate(column_sql)
    if keep.strip() == "TRUE":
        return "FALSE"
    return f"NOT ({keep})"


def subsidy_graph_key(path: str | None = None) -> str:
    """Browse leftover-style key for the shared Patient Subsidies node."""
    p = Path(path) if path else DEFAULT_PATH
    digits = "997777777"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("BIG PHARMA SUBSIDY", data)
        if isinstance(raw, dict) and raw.get("synthetic_ein"):
            digits = re.sub(r"\D", "", str(raw["synthetic_ein"])) or digits
    return f"etc{digits.zfill(9)}"
