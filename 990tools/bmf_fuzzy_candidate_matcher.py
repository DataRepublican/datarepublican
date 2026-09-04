#!/usr/bin/env python3
"""
bmf_fuzzy_candidate_matcher.py

Production-quality fuzzy retrieval + Grok (or Ollama) adjudication pipeline for mapping
no-EIN grantee names from 990 filings to authoritative IRS BMF EINs.

This is a deliberately narrow, high-precision, low-recall COMPLEMENT to the primary
Splink + bucketed TUI workflow and the generate_name_rules.py / ein_name_variants machinery.
It targets the long tail of genuinely ambiguous or low-signal names where fast lexical
methods plus human review are too slow or miss subtle disambiguation.

Core flow:
1. High-recall candidate retrieval: inverted index on significant (non-stopword) tokens
   + RapidFuzz token_set_ratio (primary) blended with token_sort_ratio + light location bonus.
   Designed to surface ALL plausible matches for polysemous names (e.g. every "Bird of Prey"
   variant in the 1.95M-row BMF).
2. Conservative LLM adjudication (Grok preferred; supports --provider grok or ollama).
   Prompt contains strong chain-of-thought instructions + 6 detailed real-data few-shot
   examples derived from the actual 14 BMF "Birds of Prey" entities + dozens of observed
   990 grantee name variants.
3. Strict structured JSON decision (enforced via json_schema where possible) with
   best_match_ein (or null), confidence, reasoning, is_ambiguous, etc.
4. Always-full audit trail written to JSONL (candidates + full decision + model).
5. Optional clean high-confidence export for backfill / seeding.

Key design principles (honed on the "Birds of Prey" stress test):
- Ultra-conservative: "better to return null than a wrong EIN" is repeated and exemplified.
- Retrieval is high-recall by design; adjudication is the filter that protects data quality.
- Explicitly teaches the model about coverage gaps (e.g. orgs whose BMF primary name
  lacks the tokens used for prefiltering, such as the major Florida Audubon Center for
  Birds of Prey under "NATIONAL AUDUBON SOCIETY INC").
- "SOCIETY", bare generics, and names with signals pointing outside the candidate pool
  must produce null + "none" + is_ambiguous=true.

The 14 real BMF entities (verified 2026-05 from bmf_analysis.tsv) + real grantee strings
from distinct_grantee_names_clean.tsv form the gold regression suite:
  - MD Ravens fan club cluster (5+ "BIRDS OF PREY RAVENS NEST ..." entities)
  - Bare "BIRDS OF PREY" (Andrews, TX) — highest overmatch risk
  - Prominent wildlife: ORANGE COUNTY BIRD OF PREY CENTER (Lake Forest CA), 
    ALAMEDA COUNTY..., MASSACHUSETTS..., BIRDS OF PREY CENTER OF UTAH, etc.
  - BIRDS OF PREY NCA PARTNERSHIP (Boise — real BLM conservation area tie-in)
  - BIRD OF PREY HEALTH GROUP, FRIENDS OF..., FOUNDATION (CO)
  - Real 990 variants that must produce null: "BIRD OF PREY SOCIETY", 
    "AUDUBON CENTER FOR BIRDS OF PREY", "THE CENTER FOR BIRDS OF PREY", 
    "BIRDS OF PREY NORTHWEST", truncated names, etc.

See --birds-of-prey-demo (fast, uses embedded exact data, no large file I/O) and
--print-analysis for immediate validation and prompt debugging.

Recommended usage for high-quality first pass on real data:
  python bmf_fuzzy_candidate_matcher.py \
      --no-ein-names pure_no_ein_high_value_1M.tsv \
      --bmf bmf_analysis.tsv \
      --limit 200 \
      --provider grok \
      --grok-model grok-3-mini \
      --output bmf_ai_matches.jsonl \
      --export-mappings high_conf_bmf_llm_mappings.json

The export produces a clean dict ready for:
  - Direct recipient_ein_backfilled UPDATEs in DuckDB
  - Seeding approved_simples.json or category bucket seeds
  - Human audit / comparison against Splink clusters or ein_name_variants.tsv

Requirements: RapidFuzz (in requirements.txt), openai (for Grok). Ollama optional.
XAI_API_KEY / GROK_API_KEY / X_API_KEY required for --provider grok.
"""

import argparse
import json
import os
import re
import sys
import hashlib
import time
import bisect
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("WARNING: rapidfuzz not available (should be in requirements.txt). Falling back to slow Jaccard.")

# Optional name cleaner for attachment-suffix stripping on polluted names
# (e.g. "University of X Foundation - SEE ADDENDUM..." → clean foundation name)
try:
    from name_cleaner import clean_name_for_matching
    HAS_NAME_CLEANER = True
except ImportError:
    HAS_NAME_CLEANER = False
    def clean_name_for_matching(name: str) -> str:
        return name

try:
    import countryCodes
    HAS_COUNTRYCODES = True
except ImportError:
    HAS_COUNTRYCODES = False
    def _detect_foreign(_): return None
    def _get_synth_foreign(_): return None

try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# Stopwords for significant-token prefilter (tuned for nonprofit names)
ORG_STOPWORDS = {
    "the", "of", "and", "inc", "llc", "ltd", "corp", "corporation", "co", "company",
    "foundation", "fund", "center", "centre", "society", "association", "institute",
    "council", "league", "club", "group", "partners", "partnership", "friends",
    "county", "state", "national", "american", "united", "international", "inc",
    "rehabilitation", "reserve", "health", "nca", "nest", "ravens",  # domain-specific but keep some signal
}

# Load central redaction/subsidy patterns from big_pharma_subsidy.json (if present)
# so that is_plausible_org_name stays in sync with the main list of known noise/redactions.
# Patterns are compiled as regex (case-insensitive) per the json's documented usage.
REDACTION_NOISE_PATTERNS = []
try:
    with open("big_pharma_subsidy.json", encoding="utf-8") as f:
        data = json.load(f)
        pats = data.get("BIG PHARMA SUBSIDY", {}).get("patterns", [])
        for p in pats:
            if not p:
                continue
            try:
                REDACTION_NOISE_PATTERNS.append(re.compile(p, re.IGNORECASE))
            except re.error:
                # fallback to escaped literal
                REDACTION_NOISE_PATTERNS.append(re.compile(re.escape(p), re.IGNORECASE))
except Exception:
    pass


def normalize(name: str) -> str:
    """Aggressive but lossless normalization for org names."""
    if not name:
        return ""
    n = name.upper()
    n = re.sub(r'[^A-Z0-9 ]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def get_significant_tokens(name: str) -> set:
    """Tokens that carry real distinguishing power after removing generic org words.
    Strips leading THE for better university matching.
    """
    tokens = normalize(name).split()
    if tokens and tokens[0].lower() == "the":
        tokens = tokens[1:]
    return {t for t in tokens if t.lower() not in ORG_STOPWORDS and len(t) > 2}


def get_sig_seq(name: str) -> list[str]:
    """Order-preserving list of significant tokens (after removing ORG_STOPWORDS).
    Used for the sorted-neighborhood core-name matcher (crap at end or beginning).
    Strips leading THE to help university/college matches against BMF names.
    """
    if not name:
        return []
    toks = normalize(name).split()
    if toks and toks[0].lower() == "the":
        toks = toks[1:]
    return [t for t in toks if t.lower() not in ORG_STOPWORDS and len(t) > 2]


def is_plausible_org_name(name: str) -> bool:
    """Heuristic filter to skip obvious non-org / redacted / schedule noise in high-value no-EIN files.
    We want real entities (foundations, clinics, depts, schools, etc) for the AI adjudication track.
    Foreign named orgs (IMPERIAL COLLEGE, STICHTING, foreign ministries, PTY LTD etc.) are forced
    non-plausible here (they get synthetic country-based 99- EINs via countryCodes instead of
    Grok or traditional match attempts). This trusts the 'in hard = sus' + big_pharma-style rollups.
    """
    if not name or len(name) < 5:
        return False
    n = name.upper()
    # Foreign named refs get synthetic country EIN rollup (see countryCodes.get_synthetic_foreign_ein).
    # These will never have a US EIN in BMF; treating as plausible wastes cycles / Grok.
    if HAS_COUNTRYCODES:
        try:
            if countryCodes.detect_foreign_country(name):
                return False
        except Exception:
            pass
    # Obvious noise / individual / attached lists
    noise = ("PATIENT", "PATIENTS", "SEE ATTACH", "SEE STATEMENT", "SEE SCHEDULE", "HIPAA", "HIPPA",
             "VARIOUS NEEDY", "VARIOUS ", "VARIOUS", "INDIVIDUAL ", "LIST OF ", "ATTACHED LIST", "SCHEDULE #",
             "SCHEDULE I ", "ATTACHMENT ", "UNDISCLOSED", "ANONYMOUS", "CONFIDENTIAL",
             "GRANTEE DETAILS", "PER ATTACHED", "AS PER ", "RECIPIENT LIST",
             "DETAILED SUPPORTING", "SUPPORTING SCHEDULE", "SCHEDULE ATTACHED", "ELIGIBLE PATIENT",
             "DETAILED GRANT", "GRANTEE SCHEDULE", "SUPPORTING DETAIL",
             "ATTN", "ATTENTION", "ATTN:", "ATTENTION:",
             "ESTIMATED DISTRIBUTIONS",
             "QUALIFIED DAYCARES", "QUALIFIED DAYCARE",
             "CONTRIBUTIONS (DETAIL STATEMENT)", "CONTRIBUTIONS DETAIL STATEMENT",
             "STATEMENT D", "STATEMENT ATTACHED",
             "DETAILS ATTACHED", "DETAIL UPON REQUEST", "DETAILS OF CONTRIBUTIONS",
             "DETAILED SCHEDULE ATTACHED", "SCHEDULE AVAILABLE UPON REQUEST",
             "DETAILS AVAILABLE UPON REQUEST", "GRANTEES LIST IS AVAILABLE",
             "TAX EXEMPT INST", "INST GRP", "DAY CARE PROVIDERS",
             "(?<!C)ATCH", "FULL SCHEDULE KEPT ON FILE", "SCHEDULE KEPT ON FILE", "KEPT ON FILE",
             "CONTRACT PHARMACAL", "PHARMACAL CORP", "PUBLIC LIBRAR",
             "PARTNERS IN LEAR", "PHILANTHROPH", "Numerous Individuals", "meet .* Requirements", "PAP Requirements", "Individuals that meet", "SEE ATTACHMENT A", "ATTACHMENT A")  # added per review: pharma support/contract (prescriptions etc.) and public libraries as unmappable/aggregate
    if any(x in n for x in noise):
        return False
    # Also filter using the central redaction patterns list (e.g. from big_pharma_subsidy.json)
    for pat in REDACTION_NOISE_PATTERNS:
        if pat.search(name):
            return False
    # Must look like it has some org signal or be long enough with caps
    org_signals = ("INC", "CORP", "LLC", "CENTRE", "ASSOC", "LEAGUE",
                   "UNIVERSITY", "COLLEGE", "CHURCH", "HOSPITAL", "CLINIC",
                   "DEPARTMENT", "OFFICE", "BOARD", "COUNCIL", "DISTRICT", "AUTHORITY", "AGENCY",
                   "PARTNERSHIP", "COALITION", "ALLIANCE", "NETWORK", "SERVICES", "HEALTH",
                   "EDUCATION", "COMMUNITY", "TRUST", "SCHOOL", "ACADEMY", "MINISTRY",
                   "POLICE", "FIRE", "SHERIFF", "TRANSIT", "MUNICIPAL", "CITY OF", "COUNTY OF")
    if any(x in n for x in org_signals):
        return True
    # Fallback: has 2+ significant tokens (likely real multi-word org)
    if len(get_significant_tokens(name)) >= 2:
        return True
    return False


# Noise patterns for big_pharma / redaction (duplicated in a few places for the pass; keep in sync with json + history)
BIG_PHARMA_NOISE = (
    "PATIENT", "PATIENTS", "SEE ATTACH", "SEE STATEMENT", "SEE SCHEDULE", "HIPAA", "HIPPA",
    "VARIOUS NEEDY", "VARIOUS ", "VARIOUS", "INDIVIDUAL ", "LIST OF ", "ATTACHED LIST", "SCHEDULE #",
    "SCHEDULE I ", "ATTACHMENT ", "UNDISCLOSED", "ANONYMOUS", "CONFIDENTIAL",
    "GRANTEE DETAILS", "PER ATTACHED", "AS PER ", "RECIPIENT LIST",
    "DETAILED SUPPORTING", "SUPPORTING SCHEDULE", "SCHEDULE ATTACHED", "ELIGIBLE PATIENT",
    "DETAILED GRANT", "GRANTEE SCHEDULE", "SUPPORTING DETAIL",
    "ATTN", "ATTENTION", "ATTN:", "ATTENTION:",
    "ESTIMATED DISTRIBUTIONS",
    "QUALIFIED DAYCARES", "QUALIFIED DAYCARE",
    "CONTRIBUTIONS (DETAIL STATEMENT)", "CONTRIBUTIONS DETAIL STATEMENT",
    "STATEMENT D", "STATEMENT ATTACHED",
    "DETAILS ATTACHED", "DETAIL UPON REQUEST", "DETAILS OF CONTRIBUTIONS",
    "DETAILED SCHEDULE ATTACHED", "SCHEDULE AVAILABLE UPON REQUEST",
    "DETAILS AVAILABLE UPON REQUEST", "GRANTEES LIST IS AVAILABLE",
    "TAX EXEMPT INST", "INST GRP", "DAY CARE PROVIDERS",
    "(?<!C)ATCH", "FULL SCHEDULE KEPT ON FILE", "SCHEDULE KEPT ON FILE", "KEPT ON FILE",
    "CONTRACT PHARMACAL", "PHARMACAL CORP", "PUBLIC LIBRAR",
    "UNITED NATIONS", "FOOD AND AGRICULTURE ORGANIZATION OF THE UNITED NATIONS",
    "SUBRECIPIENTS",  # added per review
    "PARTNERS IN LEAR", "PHILANTHROPH", "Numerous Individuals", "meet .* Requirements", "PAP Requirements", "Individuals that meet", "SEE ATTACHMENT A", "ATTACHMENT A",
    "PASS THROUGH", "PASS-THROUGH", "AGENCY DISTRIB", "REIMBURSE", "CACFP", "FBO ", "VPK", "DISTRIBUTIONS", "FOOD REIMBURS", "FBO", "(FBO", "FOR THE BENEFIT OF", "SUB RECIPIENT", "PAYMENT TO", "DISTRIBUTION TO", "REIMBURSEMENT", "135 AGENCY", "AGENCY DISTRIBUTION", "PASS THRU", "THRU PMTS",  # pass-through / flow / intermediary accounting lines (user: many remaining after phonebook are NGO A passes to B or flow desc, not direct BMF recipient; post 89% cream review: tie off the einless work + integrate with address/grant_match + generate_name_rules canonicals)
)


def is_big_pharmaish(name: str) -> bool:
    """Return True if the name matches big_pharma redaction/subsidy patterns (from json) or the noise tuple.
    These should be filtered *before* phonebook cream so never-ein redaction names don't get fake matches.
    """
    if not name or len(name) < 5:
        return False
    n = name.upper()
    if any(x in n for x in BIG_PHARMA_NOISE):
        return True
    for pat in REDACTION_NOISE_PATTERNS:
        if pat.search(name):
            return True
    return False


# Hard-coded DAF *sponsor* EINs. Do not scan BMF for "CHARITABLE" — that hits
# family foundations (Fidelity D&D, Elmont-Schwabe, Vanguard Group Foundation).
# Never return 474744275 (not a BMF org). Bare "DONOR ADVISED FUND" stays unmatched.
DAF_SPONSOR_EINS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"FIDELITY.{0,40}(CHARITABLE|GIFT FUND)", re.I), "110303001"),
    (re.compile(r"\bSCHWAB CHARITABLE\b", re.I), "311640316"),
    (re.compile(r"VANGUARD CHARITABLE|\bVANGUARD\b.{0,20}\bDAF\b|\bDAF\b.{0,20}\bVANGUARD\b", re.I), "232888152"),
    (re.compile(r"GOLDMAN SACHS PHILANTHROPY|GS DONOR ADVISED", re.I), "311774905"),
    (re.compile(r"MORGAN STANLEY GLOBAL IMPACT", re.I), "527082731"),
    (re.compile(r"NATIONAL PHILANTHROPIC TR|\bNPT\b", re.I), "237825575"),
    (re.compile(r"BANK OF AMERICA CHARITABLE GIFT", re.I), "046010342"),
    (re.compile(r"AMERICAN ONLINE GIVING", re.I), "810739440"),
]

# Kept in the exact-core key so UNIVERSITY vs FUND vs CENTER do not collide.
PHONEBOOK_LEGAL_TOKENS = {
    "foundation", "fund", "center", "centre", "society", "association",
    "institute", "university", "college", "hospital", "trust", "church",
    "health", "charitable", "endowment", "school", "academy",
}

PHONEBOOK_JUNK_TOKENS = {
    "the", "of", "and", "inc", "llc", "ltd", "corp", "corporation", "co",
    "company", "attn", "attention", "dba", "fka", "aka", "for", "a", "an",
}

GENERIC_GRANTEE_EXACT = {
    "SEE", "SEE ATTACHMENT", "SEE ATTACHED", "SEE SCHEDULE", "SEE STATEMENT",
    "SEE STMT", "SCHEDULE ATTACHED", "SCHEDULE", "ATTACHMENT", "VARIOUS",
    "VARIOUS SEE ATTACHED", "N/A", "NA", "NONE", "UNKNOWN", "REDACTED",
    "DONOR ADVISED FUND", "DAF", "UNITED WAY", "HABITAT FOR HUMANITY",
}

GENERIC_GRANTEE_PREFIXES = (
    "SEE ATTACH", "SEE SCHEDULE", "SEE STATEMENT", "SEE STMT",
    "VARIOUS -", "VARIOUS SEE", "SCHEDULE ATTACH",
)


def is_generic_grantee(name: str) -> bool:
    """True for redacted/aggregate strings that must never receive an EIN."""
    if not name or not str(name).strip():
        return True
    n = re.sub(r"[^A-Z0-9]+", " ", name.upper()).strip()
    if not n or n in GENERIC_GRANTEE_EXACT:
        return True
    if any(n.startswith(p) for p in GENERIC_GRANTEE_PREFIXES):
        return True
    if n in {"FIRST PRESBYTERIAN CHURCH", "FIRST BAPTIST CHURCH"}:
        return True
    return False


def get_phonebook_sig_seq(name: str) -> list[str]:
    """Significant tokens for exact-core cream. Keeps legal suffixes that get_sig_seq strips."""
    if not name:
        return []
    toks = normalize(name).split()
    if toks and toks[0] == "THE":
        toks = toks[1:]
    out = []
    for t in toks:
        low = t.lower()
        if len(t) <= 2 and low not in PHONEBOOK_LEGAL_TOKENS:
            continue
        if low in PHONEBOOK_JUNK_TOKENS:
            continue
        if low in ORG_STOPWORDS and low not in PHONEBOOK_LEGAL_TOKENS:
            continue
        out.append(t)
    return out


def _phonebook_remainder_ok(remainder: list[str]) -> bool:
    """Prefix/suffix leftover must be INC/ATTN-style junk, not FUND/HEALTH/MEMORIAL."""
    if not remainder:
        return True
    for t in remainder:
        low = t.lower()
        if low in PHONEBOOK_LEGAL_TOKENS:
            return False
        if low in PHONEBOOK_JUNK_TOKENS or low in ORG_STOPWORDS:
            continue
        return False
    return True


def _asset_cd(rec: Dict) -> int:
    v = rec.get("asset_cd", rec.get("ASSET_CD"))
    try:
        if v is None or v == "":
            return -1
        return int(v)
    except (TypeError, ValueError):
        return -1


def _pick_dominant_ein(ein_to_asset: Dict[str, int]) -> Optional[str]:
    """One EIN, or the unique namesake with strictly highest asset_cd >= 8."""
    if not ein_to_asset:
        return None
    if len(ein_to_asset) == 1:
        return next(iter(ein_to_asset))
    ranked = sorted(ein_to_asset.items(), key=lambda kv: kv[1], reverse=True)
    best_ein, best_acd = ranked[0]
    second_acd = ranked[1][1]
    if best_acd >= 8 and best_acd > second_acd:
        return best_ein
    return None


def resolve_donor_advised_fund_ein(name: str, bmf: list = None) -> Optional[str]:
    """Map a named DAF / gift-fund string to its sponsor EIN.

    Allowlist only. Does not scan BMF for CHARITABLE (family-foundation collisions).
    Does not default to 474744275. Generic DAF / STABLER-style labels return None.
    `bmf` is ignored; kept so callers do not change.
    """
    if not name or is_generic_grantee(name):
        return None
    upper = name.upper()
    if re.search(r"\bD\s*&\s*D\b", upper) and "FIDELITY" in upper:
        return None
    if "ELMONT" in upper and "SCHWAB" in upper:
        return None
    if re.search(r"VANGUARD GROUP FOUNDATION", upper):
        return None
    for pat, ein in DAF_SPONSOR_EINS:
        if pat.search(name):
            return ein
    return None


def token_jaccard(a: str, b: str) -> float:
    """Fallback only."""
    ta = set(normalize(a).split())
    tb = set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def build_inverted_index(bmf: List[Dict]) -> Dict[str, List[int]]:
    """Token -> list of record indices. Enables fast high-recall prefilter."""
    index = defaultdict(list)
    for idx, rec in enumerate(bmf):
        for tok in get_significant_tokens(rec["name"]):
            index[tok].append(idx)
        # Also index on raw norm tokens for rare exact matches
        for tok in normalize(rec["name"]).split():
            if len(tok) > 3:
                index[tok].append(idx)
    return index


def load_bmf(path: str) -> List[Dict]:
    """Load BMF (or charity/ein variant TSV) into list of dicts.
    Robust to header variants: EIN/NAME (bmf), ein/name (variants), filer_name/ein (charity_names.tsv).
    """
    records = []
    with open(path, encoding="utf-8") as f:
        header = next(f).strip().split("\t")
        hupper = [h.upper().replace("_", " ") for h in header]
        # name column candidates
        name_idx = next((i for i, h in enumerate(hupper) if h in ("NAME", "FILER NAME", "FILERNAME", "GRANTEE NAME")), None)
        if name_idx is None:
            name_idx = next((i for i, h in enumerate(header) if h.lower() == "name"), 1)
        # ein column
        ein_idx = next((i for i, h in enumerate(hupper) if h in ("EIN", "EID")), None)
        if ein_idx is None:
            ein_idx = next((i for i, h in enumerate(header) if h.lower() == "ein"), 0)
        # city/state optional
        city_idx = next((i for i, h in enumerate(hupper) if h in ("CITY", "CITY NAME")), None)
        state_idx = next((i for i, h in enumerate(hupper) if h in ("STATE", "STATE NAME")), None)
        asset_idx = next(
            (i for i, h in enumerate(hupper) if h in ("ASSET CD", "ASSETCD", "ASSET_CD")),
            None,
        )

        for line in f:
            parts = line.strip().split("\t")
            if len(parts) <= max(name_idx, ein_idx):
                continue
            rec = {
                "ein": parts[ein_idx].strip() if ein_idx < len(parts) else "",
                "name": parts[name_idx].strip() if name_idx < len(parts) else "",
                "city": parts[city_idx].strip() if city_idx is not None and city_idx < len(parts) else "",
                "state": parts[state_idx].strip() if state_idx is not None and state_idx < len(parts) else "",
            }
            if not rec["ein"] or not rec["name"]:
                continue
            if asset_idx is not None and asset_idx < len(parts):
                rec["asset_cd"] = parts[asset_idx].strip()
            rec["norm_name"] = normalize(rec["name"])
            records.append(rec)
    return records


def build_sorted_neighbor_refs(
    bmf: List[Dict], charity: Optional[List[Dict]] = None
) -> Tuple[List[Tuple], List[Tuple]]:
    """Precompute sorted lists of (sig_seq_tuple, ein, name) for fast neighbor lookup.
    De-dup by EIN (keep longest name). One fwd (for crap-at-end), one rev (for crap-at-front).
    Call once after load (like build_inverted_index). Cheap O(N log N) build.
    """
    ein_to_best: Dict[str, Tuple[str, str]] = {}
    for rec in (bmf or []):
        ein = rec.get("ein", "").strip()
        nm = rec.get("name", "").strip()
        if ein and nm:
            if ein not in ein_to_best or len(nm) > len(ein_to_best[ein][1]):
                ein_to_best[ein] = (nm, "bmf")
    if charity:
        for rec in charity:
            ein = rec.get("ein", "").strip()
            nm = rec.get("name", "").strip()
            if ein and nm:
                if ein not in ein_to_best or len(nm) > len(ein_to_best[ein][1]):
                    ein_to_best[ein] = (nm, "charity")

    fwd: List[Tuple] = []
    rev: List[Tuple] = []
    for ein, (nm, src) in ein_to_best.items():
        seq = get_sig_seq(nm)
        if seq:
            fwd.append((tuple(seq), ein, nm))
            rev.append((tuple(reversed(seq)), ein, nm))
    fwd.sort(key=lambda x: x[0])
    rev.sort(key=lambda x: x[0])
    return fwd, rev


def sorted_neighbor_matches(
    query: str,
    fwd_sorted: List[Tuple],
    rev_sorted: List[Tuple],
    window: int = 25,
    min_jac: float = 0.80,
) -> List[Dict]:
    """For a query name, find best core matches by sig-seq neighbor in the pre-sorted ref lists.
    Returns up to 5 with 'ein', 'name', 'score' (0-100), 'jaccard', 'crap_tokens' (the junk ignored).
    Fast: bisect + small window. Complements the RF token_set; great for ORG <crap> and <crap> ORG.

    Core phone-book intent: the fwd/rev lists are the sorted "good names" (BMF+charity variants).
    We compute where the query's sig-seq would sit, look at nearby entries. If a nearby good
    name's sig-seq is an exact prefix (trailing crap) or suffix in reversed (leading crap) of
    the query's, we treat it as a match for that EIN -- the differing tokens are "crap" to ignore.
    This is *independent* of the has_strong_org_signal heuristic in the name cleaner (which is
    only for pre-stripping *known* patterns before RF/neighbor). The neighbor itself discovers
    novel crap via proximity + core sequence match.
    """
    qseq = get_sig_seq(query)
    if not qseq or not fwd_sorted:
        return []
    qt = tuple(qseq)
    qset = set(qseq)
    results: List[Dict] = []

    for sorted_list, is_rev in ((fwd_sorted, False), (rev_sorted, True)):
        if not sorted_list:
            continue
        key = qt if not is_rev else tuple(reversed(qseq))
        idx = bisect.bisect_left(sorted_list, (key, "", ""))
        for j in range(max(0, idx - window), min(len(sorted_list), idx + window + 1)):
            t, ein, nm = sorted_list[j]
            nseq = list(t)
            nset = set(nseq)
            jac = len(qset & nset) / len(qset | nset) if (qset | nset) else 0.0

            # Pure neighbor "phone book" logic for crap-at-end/front:
            # If the ref's sig seq is an exact prefix of the query's (fwd) or reversed (rev),
            # then the extra tokens are trailing/leading crap. This is the core intent:
            # "next to each other in the sorted list of good names, one is known good,
            # the difference is ignorable crap". Does *not* rely on org signal pre-stripping.
            is_prefix_crap = False
            crap = sorted(qset - nset)
            if not is_rev:
                if len(nseq) > 0 and qseq[:len(nseq)] == nseq:
                    is_prefix_crap = True
                    crap = qseq[len(nseq):]  # preserve order of the crap suffix
            else:
                rev_qseq = list(reversed(qseq))
                if len(nseq) > 0 and rev_qseq[:len(nseq)] == nseq:
                    is_prefix_crap = True
                    crap = list(reversed(rev_qseq[len(nseq):]))  # leading crap in original order

            if is_prefix_crap or jac >= min_jac or (jac >= 0.70 and len(qset & nset) >= 2):
                if is_prefix_crap:
                    # High confidence for core-prefix match (the phone-book neighbor case).
                    # This is the pure "next to each other in sorted good names, difference is crap"
                    # logic. Does not depend on org-signal pre-stripping in the cleaner.
                    core_ratio = len(nseq) / max(1, len(qseq))
                    score = min(100.0, 90 + core_ratio * 10)
                else:
                    score = min(100.0, 72 + jac * 28)
                    if crap and len(nset) >= 2 and len(crap) <= max(3, len(nset) // 2):
                        score = min(100.0, score + 4)
                results.append({
                    "ein": ein,
                    "name": nm,
                    "jaccard": round(jac, 3),
                    "score": round(score, 1),
                    "crap_tokens": crap,
                    "is_reversed": is_rev,
                })

    # best per ein
    best_by_ein: Dict[str, Dict] = {}
    for r in results:
        e = r["ein"]
        if e not in best_by_ein or r["score"] > best_by_ein[e]["score"]:
            best_by_ein[e] = r
    out = sorted(best_by_ein.values(), key=lambda x: -x["score"])[:5]
    return out


def build_exact_core_phonebook(bmf: List[Dict], charity_variants: Optional[List[Dict]] = None) -> Dict[tuple, str]:
    """Sig-seq → EIN for exact-core cream.

    Multiple names per EIN stay (Gates rename). Multiple EINs per sig are skipped
    unless one namesake dominates (asset_cd >= 8, others <= 1). Legal suffixes stay
    in the key so UNIVERSITY vs FUND do not collide.
    """
    sig_to_eins: Dict[tuple, Dict[str, int]] = defaultdict(dict)
    sig_to_charity: Dict[tuple, set] = defaultdict(set)

    def _add(rec: Dict, from_charity: bool) -> None:
        ein = (rec.get("ein") or rec.get("EIN") or "").strip()
        nm = (rec.get("name") or rec.get("NAME") or "").strip()
        if not ein or not nm:
            return
        cleaned = clean_name_for_matching(nm)
        seq = tuple(get_phonebook_sig_seq(cleaned or nm))
        if not seq:
            return
        acd = _asset_cd(rec)
        prev = sig_to_eins[seq].get(ein, -1)
        if acd > prev:
            sig_to_eins[seq][ein] = acd
        if from_charity:
            sig_to_charity[seq].add(ein)

    for rec in bmf or []:
        _add(rec, False)
    for rec in charity_variants or []:
        _add(rec, True)
    sig_to_ein: Dict[tuple, str] = {}
    for seq, ein_to_asset in sig_to_eins.items():
        char = sig_to_charity.get(seq) or set()
        if len(char) == 1:
            sig_to_ein[seq] = next(iter(char))
            continue
        picked = _pick_dominant_ein(ein_to_asset)
        if picked:
            sig_to_ein[seq] = picked
    return sig_to_ein


def find_perfect_core_ein(name: str, sig_to_ein: Dict[tuple, str]) -> Optional[str]:
    """Exact core, or prefix/suffix with only INC/ATTN junk leftover.

    Remainder that is FUND/HEALTH/UNIVERSITY is a different legal entity — no match.
    Single-token cores are ignored (too many FIRST / NATIONAL collisions).
    """
    if not name or not sig_to_ein:
        return None
    if is_generic_grantee(name):
        return None
    cleaned = clean_name_for_matching(name)
    qseq = get_phonebook_sig_seq(cleaned or name)
    if not qseq:
        return None
    key = tuple(qseq)
    if key in sig_to_ein:
        if len(qseq) >= 2 or len(qseq[0]) >= 6:
            return sig_to_ein[key]
        return None
    if len(qseq) < 2:
        return None
    for i in range(len(qseq), 1, -1):
        sub = tuple(qseq[:i])
        if sub in sig_to_ein and _phonebook_remainder_ok(qseq[i:]):
            return sig_to_ein[sub]
    for i in range(0, len(qseq) - 1):
        sub = tuple(qseq[i:])
        if sub in sig_to_ein and _phonebook_remainder_ok(qseq[:i]):
            return sig_to_ein[sub]
    return None


def resolve_phonebook_name(name: str, sig_to_ein: Dict[tuple, str]) -> Optional[str]:
    """DAF allowlist, then exact-core cream. None if generic or ambiguous."""
    if not name or is_generic_grantee(name):
        return None
    daf = resolve_donor_advised_fund_ein(name)
    if daf:
        return daf
    cleaned = clean_name_for_matching(name)
    if cleaned and cleaned != name:
        daf = resolve_donor_advised_fund_ein(cleaned)
        if daf:
            return daf
    return find_perfect_core_ein(name, sig_to_ein)


def candidate_ein_edits(ein: str) -> List[str]:
    """Hamming-1, adjacent transposition, leading-zero pad of an 8-digit-looking EIN."""
    digits = re.sub(r"\D", "", ein or "")
    out: List[str] = []
    seen = set()

    def add(x: str) -> None:
        x = x.zfill(9) if len(x) < 9 else x
        if len(x) == 9 and x.isdigit() and x not in seen:
            seen.add(x)
            out.append(x)

    if not digits:
        return out
    add(digits)
    if len(digits) == 8:
        add("0" + digits)
    if len(digits) == 9 and digits[0] != "0":
        add("0" + digits[:8])
    core = digits.zfill(9) if len(digits) <= 9 else digits[:9]
    if len(core) == 9:
        for i in range(9):
            for d in "0123456789":
                if d != core[i]:
                    add(core[:i] + d + core[i + 1 :])
        for i in range(8):
            if core[i] != core[i + 1]:
                add(core[:i] + core[i + 1] + core[i] + core[i + 2 :])
    return out


def names_token_overlap(ghost: str, official: str) -> int:
    g = set(get_phonebook_sig_seq(ghost))
    o = set(get_phonebook_sig_seq(official))
    return len(g & o)


def repair_ein_typo(ein: str, ghost_name: str, bmf_by_ein: Dict[str, Dict]) -> Optional[str]:
    """If `ein` is missing/wrong, return a 1-edit BMF EIN whose name overlaps the ghost."""
    if not ghost_name or is_generic_grantee(ghost_name):
        return None
    current = re.sub(r"\D", "", ein or "").zfill(9)
    if len(current) == 9 and current in bmf_by_ein:
        return None
    best: Optional[Tuple[int, str]] = None
    for cand in candidate_ein_edits(ein):
        if cand == current and cand in bmf_by_ein:
            continue
        rec = bmf_by_ein.get(cand)
        if not rec:
            continue
        g = set(get_phonebook_sig_seq(ghost_name))
        o = set(get_phonebook_sig_seq(rec.get("name") or ""))
        ov = len(g & o)
        if ov < 1:
            continue
        if ov < 2 and not (g and o and (g <= o or o <= g)):
            continue
        if best is None or ov > best[0]:
            best = (ov, cand)
    if best and (current not in bmf_by_ein or best[1] != current):
        return best[1]
    return None


def retrieve_candidates(
    query: str,
    bmf: List[Dict],
    index: Optional[Dict[str, List[int]]] = None,
    top_k: int = 10,
    min_sig_overlap: int = 1,
    use_rapidfuzz: bool = True,
    charity_variants: Optional[List[Dict]] = None,
    charity_index: Optional[Dict[str, List[int]]] = None,
    neighbor_fwd: Optional[List[Tuple]] = None,
    neighbor_rev: Optional[List[Tuple]] = None,
) -> List[Dict]:
    """
    High-recall fuzzy retriever over BMF primary names + optional charity/ein variant names.

    Strategy (optimized for cases like "BIRD OF PREY SOCIETY" where many BMF records
    share 2-3 rare tokens):
    1. Prefilter via inverted index on significant (non-stopword) tokens (for bmf AND charity if provided).
    2. Score the (usually small) reduced candidate pool(s) with RapidFuzz token_set_ratio
       (best for bag-of-words org names; also blends token_sort_ratio).
    3. Merge, dedup by EIN (keep best score), return top_k with scores attached for the prompt.

    Charity variants (ein_name_variants.tsv or charity_names.tsv) often provide higher-quality
    or additional name forms for the same EINs, improving recall for long-tail 990 names.
    """
    qnorm = normalize(query)
    qsig = get_significant_tokens(query)

    def _prefilter_and_score(pool: List[Dict], src_label: str = "") -> List[Dict]:
        """Run prefilter + rapidfuzz scoring on a given pool (already reduced)."""
        if not pool:
            return []
        scored: List[Tuple[float, Dict]] = []
        if use_rapidfuzz and HAS_RAPIDFUZZ and pool:
            choices = [(rec["name"], rec) for rec in pool]
            results = process.extract(
                query,
                [c[0] for c in choices],
                scorer=fuzz.token_set_ratio,
                limit=min(top_k * 3, len(choices)),
            )
            name_to_rec = {c[0]: c[1] for c in choices}
            for match_name, score, _ in results:
                rec = name_to_rec.get(match_name)
                if not rec:
                    continue
                sort_score = fuzz.token_sort_ratio(query, match_name)
                blended = 0.75 * score + 0.25 * sort_score
                loc_bonus = 0.0
                q_upper = query.upper()
                if rec.get("state") and rec["state"] in q_upper:
                    loc_bonus = 4.0
                if rec.get("city") and rec["city"].upper() in q_upper:
                    loc_bonus = 6.0
                final_score = min(100.0, blended + loc_bonus)
                r = dict(rec)
                r["_score"] = round(final_score, 1)
                r["_source"] = src_label or "bmf"
                scored.append((final_score, r))
        else:
            for rec in pool:
                j = token_jaccard(query, rec["name"])
                r = dict(rec)
                r["_score"] = round(j * 100, 1)
                r["_source"] = src_label or "bmf"
                scored.append((r["_score"], r))
        return scored

    # Stage 1+2 for BMF
    bmf_scored: List[Tuple[float, Dict]] = []
    if bmf:
        candidates_idx = set()
        if index and qsig:
            from collections import Counter
            overlap_counts = Counter()
            for tok in qsig:
                for idx in index.get(tok, []):
                    overlap_counts[idx] += 1
            candidates_idx = {idx for idx, cnt in overlap_counts.items() if cnt >= min_sig_overlap}
        if not candidates_idx:
            candidates_idx = set(range(min(50000, len(bmf))))
        pool = [bmf[i] for i in candidates_idx if i < len(bmf)] or bmf[: min(100000, len(bmf))]
        bmf_scored = _prefilter_and_score(pool, "bmf")

    # Stage for charity variants (separate index/pool for speed + extra recall)
    charity_scored: List[Tuple[float, Dict]] = []
    if charity_variants:
        c_idx = candidates_idx = set()
        if charity_index and qsig:
            from collections import Counter
            overlap_counts = Counter()
            for tok in qsig:
                for idx in charity_index.get(tok, []):
                    overlap_counts[idx] += 1
            c_idx = {idx for idx, cnt in overlap_counts.items() if cnt >= min_sig_overlap}
        if not c_idx:
            c_idx = set(range(min(20000, len(charity_variants))))  # charity often more targeted
        cpool = [charity_variants[i] for i in c_idx if i < len(charity_variants)] or charity_variants[: min(50000, len(charity_variants))]
        charity_scored = _prefilter_and_score(cpool, "charity_variant")

    # Merge + dedup by EIN (keep highest score entry)
    ein_to_best: Dict[str, Tuple[float, Dict]] = {}
    for sc, rec in (bmf_scored + charity_scored):
        ein = rec.get("ein", "")
        if not ein:
            continue
        if ein not in ein_to_best or sc > ein_to_best[ein][0]:
            ein_to_best[ein] = (sc, rec)

    # Neighbor (sorted sig-seq) boost -- integrated *after* RF so it can override/boost top_score
    # and supply the EIN for traditional pruning. This is the "no-brainer before AI" fast path
    # for cases where crap at end/beginning dilutes the fuzz ratio but the core sig token
    # sequence is a near-exact neighbor match in the sorted ref space (the phone-book of good names).
    # See sorted_neighbor_matches for the prefix-crap logic that implements the "adjacent in sorted
    # good names => match, ignore the difference as crap" intent.
    if neighbor_fwd is not None and neighbor_rev is not None:
        try:
            nmatches = sorted_neighbor_matches(
                query, neighbor_fwd, neighbor_rev, window=25, min_jac=0.80
            )
            for nm in nmatches:
                ein = nm.get("ein", "")
                if not ein:
                    continue
                nsc = float(nm.get("score", 0.0))
                if ein not in ein_to_best or nsc > ein_to_best[ein][0]:
                    rec = {
                        "ein": ein,
                        "name": nm.get("name", ""),
                        "city": "",
                        "state": "",
                        "_score": round(nsc, 1),
                        "_source": "neighbor",
                    }
                    ein_to_best[ein] = (nsc, rec)
        except Exception:
            pass  # defensive

    # Final top by score
    merged = sorted(ein_to_best.values(), key=lambda x: x[0], reverse=True)
    top = []
    for score, rec in merged[:top_k]:
        r = dict(rec)
        # ensure _score present
        if "_score" not in r:
            r["_score"] = round(score, 1)
        top.append(r)
    return top


def build_prompt(query_name: str, candidates: List[Dict]) -> str:
    """
    High-quality prompt with chain-of-thought + few-shot examples.
    Tuned specifically on hard "Birds of Prey" polysemy cases + general nonprofit naming patterns.
    """
    cand_lines = []
    for i, c in enumerate(candidates, 1):
        loc = f"{c.get('city','')}, {c.get('state','')}".strip(" ,") or "unknown"
        score = c.get("_score", "?")
        cand_lines.append(
            f"{i}. EIN:{c['ein']} | Score:{score} | \"{c['name']}\" | {loc}"
        )

    candidates_block = "\n".join(cand_lines)

    # Few-shot examples derived directly from the 14 real BMF "Birds of Prey" entities
    # (as of 2026-05 extract from bmf_analysis.tsv) plus observed real 990 grantee name variants.
    # All examples prioritize extreme conservatism: null is the correct answer for most ambiguous/long-tail cases.
    few_shot = """
FEW-SHOT EXAMPLES (follow this reasoning style and conservatism EXACTLY. These are based on real BMF records and real 990 grantee names):

Example 1 — Clear exact geographic + phrase match (high confidence safe):
Query: "ORANGE COUNTY BIRD OF PREY CENTER"
Candidates (excerpt):
1. EIN:330440942 | Score:99.2 | "ORANGE COUNTY BIRD OF PREY CENTER" | LAKE FOREST, CA
2. EIN:994181728 | Score:68.1 | "BIRDS OF PREY CENTER OF UTAH" | PARK CITY, UT
3. EIN:943015664 | Score:61.4 | "ALAMEDA COUNTY BIRDS OF PREY RESERVE FOUNDATION" | EL CERRITO, CA
4. EIN:840967043 | Score:52.0 | "BIRDS OF PREY FOUNDATION" | BROOMFIELD, CO
...
Decision: {"best_match_ein": "330440942", "matched_bmf_name": "ORANGE COUNTY BIRD OF PREY CENTER", "confidence": "high", "reasoning": "Query contains the full exact distinguishing phrase 'ORANGE COUNTY BIRD OF PREY CENTER'. This matches candidate 1 name, city-adjacent county signal, and entity type with near-perfect fidelity. No other candidate contains both 'ORANGE' and 'COUNTY' in this combination. All other axes align. Safe for direct backfill.", "is_ambiguous": false, "notes": "High grant volume observed for this exact grantee string in 990 data."}

Example 2 — Canonical ambiguous "SOCIETY" case (the primary test case — must return null):
Query: "BIRD OF PREY SOCIETY"
Candidates (all 8-14 retrieved):
1. EIN:922574345 | Score:77.3 | "BIRDS OF PREY" | ANDREWS, TX
2. EIN:680216298 | Score:69.6 | "BIRD OF PREY HEALTH GROUP" | ROSEVILLE, CA
3. EIN:330440942 | Score:68.5 | "ORANGE COUNTY BIRD OF PREY CENTER" | LAKE FOREST, CA
4. EIN:994181728 | Score:67.9 | "BIRDS OF PREY CENTER OF UTAH" | PARK CITY, UT
5. EIN:043287450 | Score:67.0 | "MASSACHUSETTS BIRD OF PREY REHABILITATION FACILITY" | CONWAY, MA
6. EIN:475603975 | Score:61.2 | "BIRDS OF PREY NCA PARTNERSHIP" | BOISE, ID
... (plus Ravens Nest MD fan clubs and other CO/CA variants)
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "The query's strongest discriminating signal is the entity type 'SOCIETY', which is absent from every BMF candidate name. Candidates span incompatible categories: bare generic (TX), specific county centers (CA, UT), NCA conservation partnership (ID), health group, Ravens fan clubs (MD), rehabilitation facility (MA). Lexical scores are all moderate/partial; no candidate is superior on two or more axes simultaneously. Per strict rule, return null rather than guess.", "is_ambiguous": true, "notes": "Ground-truth hard negative. Any non-null decision here indicates overconfidence."}

Example 3 — Distinctive modifier / acronym (NCA) — safe high confidence:
Query: "BIRDS OF PREY NCA PARTNERSHIP"
Candidates (excerpt):
1. EIN:475603975 | Score:98.7 | "BIRDS OF PREY NCA PARTNERSHIP" | BOISE, ID
2. EIN:330440942 | Score:54.2 | "ORANGE COUNTY BIRD OF PREY CENTER" | LAKE FOREST, CA
3. EIN:840967043 | Score:51.8 | "BIRDS OF PREY FOUNDATION" | BROOMFIELD, CO
...
Decision: {"best_match_ein": "475603975", "matched_bmf_name": "BIRDS OF PREY NCA PARTNERSHIP", "confidence": "high", "reasoning": "'NCA PARTNERSHIP' is an extremely rare and specific signal present in only one BMF record. It aligns with the Birds of Prey National Conservation Area (real BLM designation in Idaho). No other candidate has 'NCA'. Geographic (Boise) and type alignment perfect. High confidence match.", "is_ambiguous": false, "notes": null}

Example 4 — Fan club vs. wildlife rehab cluster separation (Ravens Nest):
Query: "BIRDS OF PREY RAVENS NEST NO 18"
Candidates (excerpt):
1. EIN:453341232 | Score:94.5 | "BIRDS OF PREY RAVENS NEST NO 18 VENTNOR MARYLAND" | PASADENA, MD
2. EIN:522216594 | Score:81.0 | "BIRDS OF PREY-RAVENS NEST NO 1 OF HARFORD COUNTY MD INC" | BEL AIR, MD
3. EIN:205359816 | Score:72.3 | "BIRDS OF PREY RAVENS NEST NO 36 OFELMWOOD MD INC" | BALTIMORE, MD
4. EIN:330440942 | Score:48.1 | "ORANGE COUNTY BIRD OF PREY CENTER" | LAKE FOREST, CA
5. EIN:994181728 | Score:45.0 | "BIRDS OF PREY CENTER OF UTAH" | PARK CITY, UT
...
Decision: {"best_match_ein": "453341232", "matched_bmf_name": "BIRDS OF PREY RAVENS NEST NO 18 VENTNOR MARYLAND", "confidence": "high", "reasoning": "The query contains the decisive cluster signal 'RAVENS NEST NO 18' + Maryland context. This matches only the group of Baltimore Ravens NFL fan-club entities (the team's nickname is 'Birds of Prey'). All wildlife/rehab/conservation candidates lack 'RAVENS', 'NEST', or the numbering convention and are in Western states. Clear separation on axis (c). Safe high-confidence assignment within the fan-club cluster.", "is_ambiguous": false, "notes": "Important: 'Ravens Nest' terminology is a reliable disambiguator away from legitimate raptor organizations."}

Example 5 — Real-world coverage gap / wrong org not in candidate pool (must return null):
Query: "AUDUBON CENTER FOR BIRDS OF PREY"  (or "THE CENTER FOR BIRDS OF PREY", "FL AUDUBON CENTER FOR BIRDS OF PREY")
Candidates (typical retrieval):
1. EIN:330440942 | "ORANGE COUNTY BIRD OF PREY CENTER" | LAKE FOREST, CA
2. EIN:994181728 | "BIRDS OF PREY CENTER OF UTAH" | PARK CITY, UT
3. EIN:043287450 | "MASSACHUSETTS BIRD OF PREY REHABILITATION FACILITY" | CONWAY, MA
4. EIN:840967043 | "BIRDS OF PREY FOUNDATION" | BROOMFIELD, CO
5. EIN:922574345 | "BIRDS OF PREY" | ANDREWS, TX
... (no exact "Audubon Center" or Florida entity surfaced)
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "Multiple center/foundation candidates exist, but none match the specific 'AUDUBON' branding or Florida signals common in 990 data for this phrase. Critically, the well-known real entity behind most 'CENTER FOR BIRDS OF PREY' / 'AUDUBON CENTER FOR BIRDS OF PREY' grants is EIN 131624102 'NATIONAL AUDUBON SOCIETY INC' (primary BMF name lacks any 'BIRD'/'PREY' tokens, so it never enters the candidate pool via token prefilter). Assigning to any of the listed raptor centers would be factually wrong. Conservative rule requires null; route to charity_names variants or human review instead.", "is_ambiguous": true, "notes": "Classic retrieval limitation case. Documents why this pipeline is complementary, not complete."}

Example 6 — Bare generic name with one exact lexical hit (still null/low):
Query: "BIRDS OF PREY"
Candidates: includes 922574345 "BIRDS OF PREY" Andrews TX at high score + 13 other partials (centers, foundations, MD fan clubs, etc.)
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "Although an exact BMF name match exists (TX), 'BIRDS OF PREY' is an extremely common generic descriptor and tagline used by dozens of unrelated raptor rehab, conservation, education, and even fan organizations. No location, 'NCA', 'RAVENS', county, or other unique modifier is present in the query to disambiguate. High false-positive risk for even medium-dollar grants. Default to null.", "is_ambiguous": true, "notes": "Seen with $60k+ in aggregate grants; still too risky for automated assignment without extra context.", "suggested_big_pharma_patterns": null}

Example 7 — Redaction placeholder (return none + suggest filter patterns):
Query: "ELIGIBLE PATIENTS (SEE SCHEDULE #2)"
Candidates: several hospital/patient-assistance orgs + ones with "see schedule" variants.
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "This is a classic privacy/aggregate redaction pattern used when the filer does not want to list individual patients. No candidate is a specific named org matching the full signal; the 'ELIGIBLE PATIENTS SEE SCHEDULE' phrasing is subsidy-style noise. Return null and suggest patterns to catch similar cases earlier.", "is_ambiguous": true, "notes": "Large dollar aggregate; belongs in BIG PHARMA SUBSIDY rollup.", "suggested_big_pharma_patterns": ["ELIGIBLE.*PATIENTS.*SEE.*SCHEDULE", "PATIENTS.*\\(SEE SCHEDULE"]}

Example 8 — Foreign university / stiftung (coverage gap, return none):
Query: "KATHOLIEKE UNIVERSITEIT LEUVEN" or "UNIVERSITAET WIEN" or "STIFTELSEN FLYKTNINGHJELPEN"
Candidates: US universities/foundations with weak "UNIVERSITY"/"FOUNDATION" overlap only.
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "Full foreign university/foundation name with no US geo or entity modifiers. All candidates are unrelated US entities; lexical overlap only on generic tokens like 'UNIVERSITY'. True org absent from BMF pool (foreign coverage gap). Return null.", "is_ambiguous": true, "notes": "Common for European grantees of US foundations; use synthetic foreign EIN if needed."}

Example 9 — Bare US 'INC' or commodity council (real entity but not BMF charity; none):
Query: "VITRIVAX INC" or "AGBIOME INC" or "US HIGHBUSH BLUEBERRY COUNCIL"
Candidates: unrelated 'INC' or 'COUNCIL' US orgs (agape, youth councils, etc.) with no distinctive token overlap.
Decision: {"best_match_ein": null, "matched_bmf_name": null, "confidence": "none", "reasoning": "Distinct brand or 'US ... COUNCIL' for commodity (blueberry) with no BMF candidates sharing the key signals. These are often for-profit agtech or federal checkoff programs, not 501c3 charities in BMF. No superior candidate; coverage gap or non-BMF entity. Return null.", "is_ambiguous": true, "notes": "Real org receiving grants (e.g. Gates), but outside traditional BMF scope."}

Example 10 — Foreign grantee of US foundation (use grantor/filer EIN from 990 context):
Query: "CORPORACION AGENCIA AFROCOLOMBIANA HILEROS"
Candidates: irrelevant US "HOUSING CORPORATION", "FIRE ALARM CORPORATION", etc. (fuzzy on "CORPORACION" ~ "CORPORATION"; no real overlap).
(If web search allowed: this is a real Afro-Colombian org in Bogota that received grants from the Ford Foundation, listed by name+address in Ford's Form 990-PF.)
Decision: {"best_match_ein": "131684331", "matched_bmf_name": "FORD FOUNDATION", "confidence": "medium", "reasoning": "No BMF candidate matches the distinctive foreign/Afro-Colombian signals. Web/990 evidence shows this exact name as a foreign grantee in Ford Foundation 990-PF filings (e.g. grants of hundreds of thousands). In the source 990 data, the recipient EIN for this foreign name was not supplied or was the filer's context. For Sankey/attribution, use the grantor foundation's EIN (Ford 131684331).", "is_ambiguous": true, "notes": "Foreign recipient reported in US private foundation 990 (expenditure responsibility); grantor EIN is the reliable one here."}
"""

    prompt = f"""You are a senior data steward specializing in IRS 990 grantee name canonicalization and EIN backfilling for the Data Republican project.

Your #1 rule — NON-NEGOTIABLE: EXTREMELY CONSERVATIVE. It is far, far better to return no match (best_match_ein=null + confidence "none" or "low") than to incorrectly attribute even a single grant to the wrong legal entity. Wrong EINs corrupt longitudinal analysis, grantor-grantee graphs, fraud signals, and public transparency. When in any doubt whatsoever, choose null.

Important context on retrieval limitations:
- Candidates come ONLY from bmf_analysis.tsv primary names via token-overlap prefilter + RapidFuzz scoring.
- Many legitimate nonprofits use "doing business as", "aka", or secondary names. If the BMF primary name lacks the query's significant tokens (e.g. "NATIONAL AUDUBON SOCIETY INC" for many "Audubon Center for Birds of Prey" grants), the true entity will never appear in the candidate list.
- 990 grantee names are noisy: truncated ("REHABILITATION FOUNDA"), abbreviated ("OC BIRDS...", "FL AUD..."), or generic. Do not over-interpret.
- Foreign entities (European universities "Universitaet Wien", "Katholieke Universiteit Leuven", "Stiftelsen", Polish "Stowarzyszenie", African "Tigray Regional Health Bureau", Latin "Corporacion ... Afrocolombiana", Norwegian foundations, etc.) frequently receive US foundation grants but have no presence in US BMF. Strong non-US words, diacritics, or city/region names are signals to default to null (coverage gap).
- When a foreign org name appears as a grantee in a US private foundation's 990-PF (Ford, Gates, etc.), the reliable EIN for the grant record is often the US foundation (filer/grantor)'s BMF EIN, not a US EIN for the foreign recipient (which usually doesn't exist). If candidates are bad and search/990 context points to the grantor, use the foundation's EIN for attribution/Sankey (per project rules for supplied/wrong EIN cases).

Current query (raw grantee name from 990 filings, currently lacking a reliable EIN):
"{query_name}"

Top fuzzy-retrieved candidates from the official IRS Business Master File (BMF) — each with official EIN, location, and retrieval score (higher = stronger lexical match). All candidates shown (usually 5-12):

{candidates_block}

{few_shot}

STEP-BY-STEP REASONING YOU MUST PERFORM (include the numbered analysis in the "reasoning" field value):
1. Extract the query's CORE DISCRIMINATING SIGNALS: geographic (ORANGE COUNTY, specific city, STATE abbr, NCA, etc.), entity type (CENTER, FOUNDATION, SOCIETY, PARTNERSHIP, REHABILITATION, HEALTH GROUP, NEST, RAVENS, etc.), unique modifiers or numbers.
2. For every candidate evaluate three axes independently:
   (a) lexical overlap (beyond the generic "BIRD(S) OF PREY" tokens that triggered retrieval)
   (b) geographic + type alignment with signals from step 1
   (c) cluster (fan-club Ravens Nest MD entities vs. legitimate wildlife/rehab/conservation entities)
3. ONLY propose a non-null best_match_ein if exactly ONE candidate is clearly superior on at least TWO axes AND the full BMF primary name would be a defensible canonicalization in a human audit or IRS context. If the true org is likely one whose BMF primary name is absent from the list, or if signals are weak/generic, return null.
4. Assign confidence using the exact scale below. "none" is the appropriate answer for the majority of long-tail ambiguous names.

Confidence scale (use precisely):
- high: near-exact or exact name match + strong supporting geo/type signals + zero plausible alternative candidates
- medium: good alignment (e.g. strong lexical + one missing geo word) with no strong competing candidates
- low: only partial overlap or one axis strong
- none: generic/short query, multiple equally plausible candidates, or retrieval coverage gap (the default and safest for "BIRD OF PREY SOCIETY", bare "BIRDS OF PREY", most "CENTER FOR BIRDS OF PREY" without further qualifiers)

5. Redaction / aggregate / privacy pattern suggestions (IMPORTANT for evolving the filter):
   - If you return "none" or "low" *because the query name itself looks like a redaction, aggregate, privacy, or subsidy-style placeholder* (e.g. "VARIOUS NEEDY PATIENTS", "SEE ATTACHED LIST OF DISTRIBUTIONS", "ELIGIBLE PATIENTS (SEE SCHEDULE #2)", "ESTIMATED DISTRIBUTIONS", "APPROXIMATELY 449 PATIENTS", "QUALIFIED DAYCARES", "CONTRIBUTIONS (DETAIL STATEMENT)", "SEE LIST ATTACHED", "PATIENTS SEE SCHEDULE", etc.), populate "suggested_big_pharma_patterns" with 1-3 new patterns.
   - Patterns should be in the exact style used in big_pharma_subsidy.json (regex-friendly strings like "ELIGIBLE.*PATIENTS.*SEE", "APPROXIMATELY \\d+ PATIENTS", "SEE .* DETAIL STATEMENT", "\\bPATIENTS?\\b.*\\bSEE\\b", "ESTIMATED.*DISTRIB", etc.).
   - The goal is to improve is_plausible_org_name() and the BIG PHARMA SUBSIDY rollup list for future runs, so we hard-fail or roll up these noisy cases earlier.
   - If the name is a real org (even if generic), or you are confident in a match, leave suggested_big_pharma_patterns as null.

RESPONSE FORMAT — return ONLY a single line of valid minified JSON. No prose, no ```json fences, no explanations outside the object.

{{
  "best_match_ein": "9-digit EIN string or null",
  "matched_bmf_name": "exact BMF primary name of chosen candidate or null",
  "confidence": "high" | "medium" | "low" | "none",
  "reasoning": "Concise 1-3 sentence step-by-step analysis covering signals, axis evaluation, and why null or this EIN",
  "is_ambiguous": true or false,
  "notes": "short human-reviewer context (e.g. 'seen in $X grants', 'possible coverage gap', 'abbreviation of Orange County') or null",
  "suggested_big_pharma_patterns": ["ELIGIBLE.*PATIENTS.*SEE SCHEDULE", "APPROXIMATELY \\d+ PATIENTS"] or null
}}
"""
    return prompt


# Strict JSON schema for Grok (used with response_format json_schema for guaranteed structure)
GROK_DECISION_SCHEMA = {
    "name": "bmf_adjudication_decision",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "best_match_ein": {"type": ["string", "null"], "description": "Exactly 9 digits or null"},
            "matched_bmf_name": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]},
            "reasoning": {"type": "string", "minLength": 10},
            "is_ambiguous": {"type": "boolean"},
            "notes": {"type": ["string", "null"]},
            "suggested_big_pharma_patterns": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "1-3 suggested new regex patterns or phrases (in the style of big_pharma_subsidy.json) to add to the redaction filter / subsidy rollup list. Only include when the query is a clear redaction/aggregate/privacy placeholder (VARIOUS, SEE ATTACHED, ELIGIBLE PATIENTS SEE SCHEDULE, ESTIMATED DISTRIBUTIONS, APPROXIMATELY N PATIENTS, QUALIFIED DAYCARES, etc.) and you are returning none/low. Goal: improve is_plausible_org_name and future filtering."
            }
        },
        "required": ["best_match_ein", "matched_bmf_name", "confidence", "reasoning", "is_ambiguous", "notes", "suggested_big_pharma_patterns"],
        "additionalProperties": False
    }
}


def _extract_json_from_text(text: str) -> Optional[Dict]:
    """Robust extraction even if model wraps in ```json or adds prose."""
    if not text:
        return None
    text = text.strip()
    # Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # Code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Last { ... }
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def call_ollama(prompt: str, model: str = "qwen2.5:14b", max_retries: int = 2) -> Optional[Dict]:
    if not HAS_OLLAMA:
        print("ollama package not installed. pip install ollama")
        return None

    for attempt in range(max_retries + 1):
        try:
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.0, "num_predict": 800}
            )
            content = response["message"]["content"]
            parsed = _extract_json_from_text(content) or json.loads(content)
            # Light validation
            if isinstance(parsed, dict) and "confidence" in parsed:
                return parsed
        except Exception as e:
            if attempt == max_retries:
                print(f"Ollama failed after {max_retries+1} attempts: {e}")
                return None
            time.sleep(0.5 * (attempt + 1))
    return None


def call_grok(
    prompt: str,
    model: str = "grok-3-mini",
    max_retries: int = 2,
    use_strict_schema: bool = True,
) -> Optional[Dict]:
    """Call Grok via OpenAI client. Prefers strict json_schema (like the geocoding code in this repo)."""
    if not HAS_OPENAI:
        print("openai package not installed. pip install openai")
        return None

    api_key = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or os.environ.get("X_API_KEY")
    if not api_key:
        print("Set XAI_API_KEY (or GROK_API_KEY / X_API_KEY) environment variable to use Grok.")
        return None

    for attempt in range(max_retries + 1):
        try:
            client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 900,
            }
            if use_strict_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": GROK_DECISION_SCHEMA,
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            parsed = _extract_json_from_text(content)
            if parsed and isinstance(parsed, dict) and "confidence" in parsed:
                return parsed
            # fallback parse
            return json.loads(content) if content else None
        except Exception as e:
            if attempt == max_retries:
                print(f"Grok call failed after retries: {e}")
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


# =============================================================================
# BIRDS OF PREY GOLD / STRESS TEST DATA (embedded — no external files required)
# =============================================================================

BIRDS_OF_PREY_BMF = [
    {"ein": "043287450", "name": "MASSACHUSETTS BIRD OF PREY REHABILITATION FACILITY", "city": "CONWAY", "state": "MA"},
    {"ein": "473887155", "name": "BIRDS OF PREY RAVENS NO 20 QUEEN ANNES COUNTY", "city": "CENTREVILLE", "state": "MD"},
    {"ein": "205359816", "name": "BIRDS OF PREY RAVENS NEST NO 36 OFELMWOOD MD INC", "city": "BALTIMORE", "state": "MD"},
    {"ein": "522216593", "name": "BIRDS OF PREY-CHAMBER OF BALTIMORE RAVENS NESTS INC", "city": "BALTIMORE", "state": "MD"},
    {"ein": "522216594", "name": "BIRDS OF PREY-RAVENS NEST NO 1 OF HARFORD COUNTY MD INC", "city": "BEL AIR", "state": "MD"},
    {"ein": "453341232", "name": "BIRDS OF PREY RAVENS NEST NO 18 VENTNOR MARYLAND", "city": "PASADENA", "state": "MD"},
    {"ein": "922574345", "name": "BIRDS OF PREY", "city": "ANDREWS", "state": "TX"},
    {"ein": "680216298", "name": "BIRD OF PREY HEALTH GROUP", "city": "ROSEVILLE", "state": "CA"},
    {"ein": "943015664", "name": "ALAMEDA COUNTY BIRDS OF PREY RESERVE FOUNDATION", "city": "EL CERRITO", "state": "CA"},
    {"ein": "330440942", "name": "ORANGE COUNTY BIRD OF PREY CENTER", "city": "LAKE FOREST", "state": "CA"},
    {"ein": "332519575", "name": "FRIENDS OF THE BIRDS OF PREY BOP", "city": "AURORA", "state": "CO"},
    {"ein": "475603975", "name": "BIRDS OF PREY NCA PARTNERSHIP", "city": "BOISE", "state": "ID"},
    {"ein": "840967043", "name": "BIRDS OF PREY FOUNDATION", "city": "BROOMFIELD", "state": "CO"},
    {"ein": "994181728", "name": "BIRDS OF PREY CENTER OF UTAH", "city": "PARK CITY", "state": "UT"},
]

# Representative hard test queries (mix of real variants observed in distinct_grantee_names_clean.tsv + the canonical ambiguous example).
# These exercise both success paths and the important "return null on coverage gap or ambiguity" paths.
BIRDS_OF_PREY_TEST_QUERIES = [
    "BIRD OF PREY SOCIETY",                    # the user's canonical ambiguous example — MUST -> null/none
    "BIRDS OF PREY",
    "BIRD OF PREY CENTER",
    "ORANGE COUNTY BIRD OF PREY CENTER",
    "ORANGE COUNTY BIRDS OF PREY",
    "BIRDS OF PREY FOUNDATION",
    "BIRDS OF PREY NCA PARTNERSHIP",
    "BIRDS OF PREY RAVENS NEST",
    "BIRDS OF PREY RAVENS NEST NO 18",
    "BIRD OF PREY HEALTH GROUP",
    "BIRDS OF PREY CENTER OF UTAH",
    "ALAMEDA COUNTY BIRDS OF PREY",
    "FRIENDS OF THE BIRDS OF PREY",
    "MASSACHUSETTS BIRD OF PREY REHABILITATION",
    "BIRD OF PREY CONSERVANCY",                # real variant
    # Additional real 990 grantee strings that stress coverage gaps and polysemy:
    "THE CENTER FOR BIRDS OF PREY",
    "AUDUBON CENTER FOR BIRDS OF PREY",
    "OC BIRDS OF PREY CENTER",                 # abbreviation
    "LAST CHANCE FOREVER-THE BIRD OF PREY CONSERVANCY",
    "BIRDS OF PREY NORTHWEST",
    "BIRDS OF PREY REHABILITATION FOUNDA",     # as truncated in some distinct name records
    "FL Audubon Center for Birds of Prey",
    "CENTER FOR THE BIRDS OF PREY",
]


def get_birds_of_prey_demo_data() -> Tuple[List[Dict], List[str]]:
    """Returns (bmf_subset, test_queries) for immediate prompt/LLM testing."""
    return list(BIRDS_OF_PREY_BMF), list(BIRDS_OF_PREY_TEST_QUERIES)


def analyze_birds_of_prey_hard_cases() -> str:
    """Returns a textual deep analysis suitable for printing or logging."""
    lines = [
        "=== DEEP ANALYSIS: 'BIRDS OF PREY' DISAMBIGUATION HARD CASES (14 real BMF entities) ===",
        "",
        "The 14 BMF records fall into several clusters:",
        "  1. MD Ravens fan-club cluster (5+ entities): 'BIRDS OF PREY RAVENS NEST ...' + chamber variants in Baltimore metro (CENTREVILLE, BALTIMORE, BEL AIR, PASADENA MD). These are themed around the Baltimore Ravens NFL team ('Birds of Prey' nickname). Extremely easy to confuse with wildlife orgs on pure name match.",
        "  2. Bare/generic: 'BIRDS OF PREY' (Andrews, TX) — highest risk of over-matching.",
        "  3. Prominent wildlife/rehab: ORANGE COUNTY BIRD OF PREY CENTER (Lake Forest CA — very well known), ALAMEDA COUNTY..., MASSACHUSETTS..., BIRDS OF PREY CENTER OF UTAH.",
        "  4. Conservation partnerships/foundations: BIRDS OF PREY NCA PARTNERSHIP (Boise ID — tied to real BLM Birds of Prey National Conservation Area + Peregrine Fund activity), BIRDS OF PREY FOUNDATION (CO), FRIENDS OF...",
        "  5. Outlier: BIRD OF PREY HEALTH GROUP (Roseville CA).",
        "",
        "HARDEST CASES FOR LLM ADJUDICATOR (updated from real data inspection of bmf_analysis.tsv + distinct_grantee_names_clean.tsv):",
        "  A. 'BIRD OF PREY SOCIETY' (your example): Zero candidates contain SOCIETY. Retrieval surfaces all 14. Correct = null + none + is_ambiguous=true. Gold standard test for overconfidence.",
        "  B. Bare 'BIRDS OF PREY' or generic 'BIRD OF PREY CENTER' / 'THE CENTER FOR BIRDS OF PREY' without geo or unique modifiers: Multiple partial matches. Should be null. Real usage frequently refers to the famous Florida Audubon entity (EIN 131624102, BMF primary 'NATIONAL AUDUBON SOCIETY INC' — note: this name contains ZERO 'BIRD'/'PREY' tokens, so it is invisible to this retriever).",
        "  C. 'BIRDS OF PREY RAVENS NEST ...' queries: Must strongly prefer the MD Ravens fan-club cluster (5+ entities) and ignore all wildlife centers. 'RAVENS NEST' + number + MD signals are decisive.",
        "  D. County-specific (ORANGE COUNTY BIRD OF PREY CENTER, ALAMEDA...) vs generic center: The county words + full phrase in query provide the only reliable disambiguation. High success rate here.",
        "  E. 'BIRDS OF PREY NCA PARTNERSHIP': Extremely distinctive; one of the easiest high-confidence wins.",
        "  F. 'AUDUBON CENTER FOR BIRDS OF PREY', 'LAST CHANCE FOREVER...', 'BIRDS OF PREY NORTHWEST', 'BIRDS OF PREY REHABILITATION FOUNDA' (truncated): Often coverage gaps or partials. Expect null + notes about possible external resolution via ein_name_variants.tsv or charity_names.",
        "  G. 'BIRDS OF PREY FOUNDATION' (CO), 'BIRD OF PREY HEALTH GROUP' (CA), 'MASSACHUSETTS BIRD OF PREY REHABILITATION FACILITY': Usually safe when the full distinctive phrase is present.",
        "",
        "This set (14 real BMF entities + 20+ real 990 variants) is the best unit/regression test for the pipeline. It forces correct high-recall retrieval, teaches the model the difference between fan clubs and wildlife orgs, and — most importantly — trains it to confidently say 'I do not have enough information / this org is not representable in the BMF primary name candidates' by returning null.",
        "Key architectural lesson: this Grok adjudication tool is deliberately narrow and conservative; it is a long-tail complement to Splink, exact BMF matching in generate_name_rules.py, and the full ein_name_variants + charity_names machinery.",
    ]
    return "\n".join(lines)


# =============================================================================
# CACHING + OUTPUT HELPERS (production essentials)
# =============================================================================

def make_cache_key(query: str, top_eins: List[str]) -> str:
    h = hashlib.sha256((normalize(query) + "|" + ",".join(sorted(top_eins))).encode()).hexdigest()
    return h[:16]


def load_existing_results(output_path: str) -> Dict[str, Any]:
    """Resume support: map normalized query -> previous decision."""
    done = {}
    p = Path(output_path)
    if not p.exists():
        return done
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                q = normalize(obj.get("query_name", ""))
                if q:
                    done[q] = obj.get("decision")
            except Exception:
                continue
    return done


def export_high_confidence_mappings(results: List[Dict], out_path: str, min_conf: str = "high") -> int:
    """Write a clean file ready for integration into address_matcher / grant backfill."""
    mappings = {}
    conf_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
    min_rank = conf_order.get(min_conf, 2)

    for r in results:
        dec = r.get("decision") or {}
        conf = (dec.get("confidence") or "none").lower()
        ein = dec.get("best_match_ein")
        if not ein or conf_order.get(conf, 0) < min_rank:
            continue
        key = normalize(r["query_name"])
        mappings[key] = {
            "ein": ein,
            "bmf_name": dec.get("matched_bmf_name"),
            "confidence": conf,
            "reasoning": dec.get("reasoning"),
            "source": "bmf_fuzzy_llm",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(mappings)} high-confidence mappings to {out_path}")
    return len(mappings)


def print_integration_recipe(mappings_path: str):
    """Actionable DuckDB / Python snippet the user can copy-paste to consume results."""
    print("\n" + "=" * 70)
    print("INTEGRATION RECIPE (copy-paste into your environment)")
    print("=" * 70)
    print(f"""
-- 1. Quick DuckDB one-off backfill for high-confidence LLM mappings
-- (run against your working irs990.duckdb copy)
LOAD 'mappings' AS llm_map FROM '{mappings_path}';   -- or use read_json_auto

-- Assuming you have a table or CTE of the mappings
CREATE OR REPLACE TEMP TABLE llm_ein_assignments AS
SELECT key AS grantee_name_upper, value.ein AS assigned_ein
FROM read_json_auto('{mappings_path}') t, UNNEST(t) u(key, value);

UPDATE Grants g
SET recipient_ein_backfilled = l.assigned_ein,
    grantee_name_bmf = (SELECT name FROM bmf_analysis WHERE ein = l.assigned_ein LIMIT 1)
FROM llm_ein_assignments l
WHERE UPPER(COALESCE(g.grantee_name, '')) = l.grantee_name_upper
  AND (g.recipient_ein IS NULL OR g.recipient_ein = '');

-- 2. Or in Python (address_matcher style) — add early in match_grants()
# with open("{mappings_path}") as f:
#     llm_map = json.load(f)
# for grant in ...:
#     key = normalize(grant.grantee_name)
#     if key in llm_map and llm_map[key]["confidence"] == "high":
#         grant.recipient_ein_backfilled = llm_map[key]["ein"]
""")
    print("=" * 70 + "\n")


# =============================================================================
# PRODUCTION MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="BMF Fuzzy Retrieval + LLM Adjudication for no-EIN grantee names (long-tail complement to Splink/TUI)"
    )
    parser.add_argument("--no-ein-names", default="distinct_grantee_names_clean.tsv",
                        help="TSV (or 3-col) of names needing EINs. Header skipped.")
    parser.add_argument("--bmf", default="bmf_analysis.tsv", help="BMF dump (EIN\tNAME\tCITY\tSTATE)")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N (0 = all)")
    parser.add_argument("--top-k", type=int, default=8, help="Max candidates to send to LLM")
    parser.add_argument("--min-sig-overlap", type=int, default=1)
    parser.add_argument("--provider", choices=["ollama", "grok"], default="grok")
    parser.add_argument("--ollama-model", default="qwen2.5:14b")
    parser.add_argument("--grok-model", default="grok-3-mini")
    parser.add_argument("--output", default="bmf_ai_matches.jsonl")
    parser.add_argument("--charity-variants", default="ein_name_variants.tsv",
                        help="Optional higher-quality name→EIN variants file (charity file) to use as additional retrieval source.")
    parser.add_argument("--generate-prompts", action="store_true",
                        help="Instead of calling the LLM, generate ready-to-use prompt files (or a batch JSON) for the given names + candidates. These can be fed to a subagent running in the user's authenticated Grok Build CLI for bulk Grok adjudication.")
    parser.add_argument("--export-mappings", default="", help="If set, also write high-conf JSON mappings here")
    parser.add_argument("--no-rapidfuzz", action="store_true", help="Force pure-Python Jaccard (slow)")
    parser.add_argument("--birds-of-prey-demo", action="store_true",
                        help="Run ONLY on the 14 real BMF Birds of Prey entities + hard test queries (no large file load). Ideal for prompt validation and Grok prompt iteration.")
    parser.add_argument("--print-analysis", action="store_true", help="Print deep hard-case analysis then exit")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess queries even if they already exist in the --output file (ignore resume cache). Useful after prompt changes.")
    args = parser.parse_args()

    if args.print_analysis:
        print(analyze_birds_of_prey_hard_cases())
        return

    if args.birds_of_prey_demo:
        print("=== BIRDS OF PREY DEMO MODE (embedded gold data) ===")
        bmf, test_names = get_birds_of_prey_demo_data()
        print(f"Using {len(bmf)} hardcoded BMF records + {len(test_names)} test queries")
        print(analyze_birds_of_prey_hard_cases()[:800] + "...\n")
        index = build_inverted_index(bmf)
        charity = []
        charity_index = None
        neighbor_fwd = None
        neighbor_rev = None
    else:
        print("Loading BMF...")
        bmf = load_bmf(args.bmf)
        print(f"Loaded {len(bmf):,} BMF records")
        index = build_inverted_index(bmf)
        print(f"Built inverted index with {len(index):,} significant tokens")

        charity = []
        if os.path.exists(args.charity_variants):
            print("Loading charity name variants (often higher quality for variant names)...")
            charity = load_bmf(args.charity_variants)
            print(f"Loaded {len(charity):,} charity variant records")

        charity_index = None
        if charity:
            print("Building charity variant inverted index for fast retrieval...")
            charity_index = build_inverted_index(charity)
            print(f"  Built with {len(charity_index):,} significant tokens")

        print("Building sorted neighbor refs (integrated for traditional crap rescue before AI)...")
        neighbor_fwd, neighbor_rev = build_sorted_neighbor_refs(bmf, charity)
        print(f"  Built fwd+rev neighbor indices")

        print("Loading names without EINs...")
        test_names = []
        with open(args.no_ein_names, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    test_names.append(parts[0].strip())
                if args.limit and len(test_names) >= args.limit:
                    break
        print(f"Loaded {len(test_names):,} names (limit={args.limit or 'none'})")

    # === GENERATE PROMPTS MODE (for subagent / bulk Grok execution in user's authenticated CLI) ===
    if args.generate_prompts:
        print("\n=== GENERATE PROMPTS MODE ===")
        print("Using BMF primary names + charity/ein variant names for high-recall candidate retrieval.")
        print("Only emitting prompts for plausible organization names (skipping patient lists, 'see attached', HIPAA noise, etc).")
        out_dir = Path("generated_bmf_prompts")
        out_dir.mkdir(exist_ok=True)
        count = 0
        skipped_non_org = 0
        target = 1000
        for name in test_names:
            if not is_plausible_org_name(name):
                skipped_non_org += 1
                continue

            # Clean attachment suffixes (e.g. "Foundation - SEE ADDENDUM...") when a strong org signal is present
            cleaned_name = clean_name_for_matching(name)

            cands = retrieve_candidates(cleaned_name, bmf, charity_variants=charity, index=index, charity_index=charity_index, top_k=args.top_k, neighbor_fwd=neighbor_fwd, neighbor_rev=neighbor_rev)
            if not cands:
                continue
            prompt_text = build_prompt(cleaned_name, cands)
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', cleaned_name)[:80]
            (out_dir / f"{count:05d}_{safe_name}.md").write_text(prompt_text, encoding="utf-8")
            count += 1
            if count % 100 == 0:
                print(f"  Generated {count} prompts...")
            if count >= target:
                break
        print(f"Generated {count} ready-to-use prompt .md files in {out_dir}/ (skipped {skipped_non_org} non-org/noisy names)")
        print("These use the full conservative few-shot prompt with BMF + charity candidates.")
        print("Feed a batch of them (e.g. 100) to a subagent via bmf_subagent_prompt_executor.md (or a custom batch task .md).")
        print("The subagent runs in your authenticated Grok Build CLI Premium+ session (OAuth, no raw key needed).")
        # Also write a simple manifest for easy batching / subagent consumption
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_no_ein_file": args.no_ein_names,
            "bmf_file": args.bmf,
            "charity_variants_file": args.charity_variants,
            "count": count,
            "prompt_dir": str(out_dir),
            "notes": "Each .md is a self-contained prompt. Subagent should read N of them, call Grok with the content, return JSON decisions."
        }
        (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return

    done = {} if args.force else load_existing_results(args.output)
    if args.force:
        print("FORCE mode: reprocessing all queries (resume cache ignored). Good for prompt iteration.")
    else:
        print(f"Resume: {len(done)} previously completed queries found in {args.output}")

    use_rf = not args.no_rapidfuzz and HAS_RAPIDFUZZ

    results = []
    processed = 0
    skipped = 0
    for i, name in enumerate(test_names, 1):
        qnorm = normalize(name)
        if not args.force and qnorm in done:
            skipped += 1
            continue

        if i % 25 == 0 or args.birds_of_prey_demo:
            print(f"Processing {i}/{len(test_names)}: {name[:60]}...")

        # Clean attachment suffixes (e.g. "Foundation - SEE ADDENDUM...") when a strong org signal is present
        cleaned_name = clean_name_for_matching(name)

        candidates = retrieve_candidates(
            cleaned_name, bmf, charity_variants=charity, index=index, charity_index=charity_index, top_k=args.top_k,
            min_sig_overlap=args.min_sig_overlap, use_rapidfuzz=use_rf,
            neighbor_fwd=neighbor_fwd, neighbor_rev=neighbor_rev
        )
        if not candidates:
            continue

        prompt = build_prompt(cleaned_name, candidates)

        # Demo mode: surface the actual prompt (including the rich few-shot block) for the first query
        # so the user can audit / iterate on the Grok prompt without reading source.
        if args.birds_of_prey_demo and i == 1:
            print("\n--- PROMPT SENT FOR FIRST DEMO QUERY (inspect few-shots + instructions) ---")
            print(prompt[:2400] + "\n... [truncated for console] ...\n")
            print("--- END PROMPT PREVIEW ---\n")

        decision = None
        if args.provider == "grok":
            decision = call_grok(prompt, model=args.grok_model)
        else:
            decision = call_ollama(prompt, model=args.ollama_model)

        result = {
            "query_name": name,
            "cleaned_query_name": cleaned_name,
            "query_norm": qnorm,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidates": [
                {"ein": c["ein"], "name": c["name"], "city": c.get("city"), "state": c.get("state"), "score": c.get("_score")}
                for c in candidates
            ],
            "decision": decision,
            "provider": args.provider,
            "model": args.grok_model if args.provider == "grok" else args.ollama_model,
        }
        results.append(result)

        with open(args.output, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        processed += 1
        if args.birds_of_prey_demo and i <= 3:
            print(f"  → decision: {decision}")

    print(f"\nCompleted {processed} new adjudications (skipped {skipped} via resume). Total decisions written to {args.output}")

    if args.export_mappings and results:
        n = export_high_confidence_mappings(results, args.export_mappings, min_conf="high")
        if n > 0:
            print_integration_recipe(args.export_mappings)

    if args.birds_of_prey_demo:
        # Post-run summary of confidence distribution for quick quality signal
        conf_counts = {"high": 0, "medium": 0, "low": 0, "none": 0, "other": 0}
        null_count = 0
        for r in results:
            dec = (r.get("decision") or {})
            c = (dec.get("confidence") or "other").lower()
            conf_counts[c] = conf_counts.get(c, 0) + 1
            if not dec.get("best_match_ein"):
                null_count += 1
        print("\n=== BIRDS-OF-PREY DEMO SUMMARY ===")
        print(f"  New decisions this run: {len(results)}")
        print(f"  Returned null (no match): {null_count}")
        print(f"  Confidence breakdown: high={conf_counts['high']}, medium={conf_counts['medium']}, low={conf_counts['low']}, none={conf_counts['none']}")
        print("Demo complete. Review the JSONL (especially 'reasoning' and 'notes') for prompt tuning.")
        print("Recommended next: python bmf_fuzzy_candidate_matcher.py --birds-of-prey-demo --provider grok --force --output /tmp/bop_test.jsonl")
        print("Then inspect a few real high-value cases from pure_no_ein_high_value_1M.tsv with human review of medium/low outputs.")


if __name__ == "__main__":
    main()
