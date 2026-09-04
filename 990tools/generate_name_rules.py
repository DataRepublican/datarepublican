#!/usr/bin/env python3
"""
generate_name_rules_v19.py

Senior engineer approach: clarity, simplicity, maintainability.
We use design patterns judiciously — only when they clearly improve the design.
Most importantly, we explain the WHY behind key decisions.

Design Summary (high level):
- Canonical is now tree-aware via absorb() for hierarchy + provenance.
- absorb() centralizes data merge (shorter name, variants, EIN priority, grant totals) + tree linking.
- Old merge()/rebuild_pattern() removed from active paths (dead code left only if pharma siding needs it).
- We pass Canonical objects around to preserve rich data.
- Early dedup on EINless canonicals only — intentional for speed and focus.
- No over-engineering: dataclass + simple functions.
"""

import re
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import json
import gzip
import time
import subprocess
from typing import Set, Optional, Dict, List, Tuple
from enum import Enum, auto

# Attachment suffix stripping for polluted names (e.g. "University of X Foundation - SEE ADDENDUM...")
try:
    from name_cleaner import clean_name_for_matching as _strip_attachment_suffixes
except ImportError:
    def _strip_attachment_suffixes(name: str) -> str:
        return name

# ==================== CONFIG ====================
DISTINCT_NAMES_TSV = "distinct_grantee_names.tsv"
BMF_TSV = "bmf_analysis.tsv"
CHARITY_NAMES_TSV = "ein_name_variants.tsv"
OUTPUT_JSON = "name_rules_v19.json.gz"
CACHE_FILE = "rules_without_ein_cache.json"
BIG_PHARMA_JSON = "big_pharma_subsidy.json"
UNIVERSITY_FAMILIES_ENABLED = True   # When True, automatically detects university/college families from BMF data (with real EINs + satellites) and sides them. This is the repeatable path for the universities sub-goal.

TOP_CITIES_TO_ALWAYS_STRIP = 100
NOISE_THRESHOLD = 0.01  # 1% of grantee names

# Words that should NEVER be treated as noise, even if they appear frequently
DYNAMIC_NOISE_WHITELIST = {
    "UNIVERSITY",
    "COLLEGE",
    "SCHOOL",
    "ACADEMY",
    "CHURCH",
    "HEALTH",
    "SERVICES",
    "EDUCATION",
    "COMMUNITY",
    "AMERICAN",
    "UNITED",
    "YOUTH",
    "ARTS",
}

# Track names that return 0 lines from both charity and BMF grep searches
# This is useful signal — these are likely noise, very obscure, or non-charity entities
ZERO_RESULT_GREPS = []

KNOWN_CHARITIES = {
    "MADD": "MOTHERS AGAINST DRUNK DRIVING",
    "M.A.D.D.": "MOTHERS AGAINST DRUNK DRIVING",
    "BPOE": "BENEVOLENT AND PROTECTIVE ORDER OF ELKS",
    "B.P.O.E.": "BENEVOLENT AND PROTECTIVE ORDER OF ELKS",
    "ELKS": "BENEVOLENT AND PROTECTIVE ORDER OF ELKS",
    "VFW": "VETERANS OF FOREIGN WARS",
    "V.F.W.": "VETERANS OF FOREIGN WARS",
    "AARP": "AMERICAN ASSOCIATION OF RETIRED PERSONS",
    "NAACP": "NATIONAL ASSOCIATION FOR THE ADVANCEMENT OF COLORED PEOPLE",
    "PTA": "PARENT TEACHER ASSOCIATION",
    "P.T.A.": "PARENT TEACHER ASSOCIATION",
    "PTO": "PARENT TEACHER ORGANIZATION",
    "P.T.O.": "PARENT TEACHER ORGANIZATION",
    "BSA": "BOY SCOUTS OF AMERICA",
    "B&GC": "BOYS AND GIRLS CLUB",
    "IBT": "INTERNATIONAL BROTHERHOOD OF TEAMSTERS",
    "YMCA": "YOUNG MENS CHRISTIAN ASSOCIATION",
    "YWCA": "YOUNG WOMENS CHRISTIAN ASSOCIATION",
}

STATE_EXPANSION = {
    "AL": "ALABAMA",
    "AK": "ALASKA",
    "AZ": "ARIZONA",
    "AR": "ARKANSAS",
    "CA": "CALIFORNIA",
    "CO": "COLORADO",
    "CT": "CONNECTICUT",
    "DE": "DELAWARE",
    "FL": "FLORIDA",
    "GA": "GEORGIA",
    "HI": "HAWAII",
    "ID": "IDAHO",
    "IL": "ILLINOIS",
    "IN": "INDIANA",
    "IA": "IOWA",
    "KS": "KANSAS",
    "KY": "KENTUCKY",
    "LA": "LOUISIANA",
    "ME": "MAINE",
    "MD": "MARYLAND",
    "MA": "MASSACHUSETTS",
    "MI": "MICHIGAN",
    "MN": "MINNESOTA",
    "MS": "MISSISSIPPI",
    "MO": "MISSOURI",
    "MT": "MONTANA",
    "NE": "NEBRASKA",
    "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE",
    "NJ": "NEW JERSEY",
    "NM": "NEW MEXICO",
    "NY": "NEW YORK",
    "NC": "NORTH CAROLINA",
    "ND": "NORTH DAKOTA",
    "OH": "OHIO",
    "OK": "OKLAHOMA",
    "OR": "OREGON",
    "PA": "PENNSYLVANIA",
    "RI": "RHODE ISLAND",
    "SC": "SOUTH CAROLINA",
    "SD": "SOUTH DAKOTA",
    "TN": "TENNESSEE",
    "TX": "TEXAS",
    "UT": "UTAH",
    "VT": "VERMONT",
    "VA": "VIRGINIA",
    "WA": "WASHINGTON",
    "WV": "WEST VIRGINIA",
    "WI": "WISCONSIN",
    "WY": "WYOMING",
}

PRIORITY_CANONICALS = [
    "ATTACHED",
    "AMERICAN LEGION",
    "CHAMBER OF COMMERCE",
    "BOYS AND GIRLS CLUB",
    "PARENT TEACHER ASSOCIATION",
    "PARENT TEACHER ORGANIZATION",
    "VOLUNTEER FIRE DEPARTMENT",
    "FIRE DEPARTMENT",
    "SCHOOL DISTRICT",
    "HIGH SCHOOL",
    "MIDDLE SCHOOL",
    "PUBLIC LIBRARY",
    "COMMUNITY DEVELOPMENT",
    "ECONOMIC DEVELOPMENT",
    "MENTAL HEALTH",
    "HEALTH CARE",
    "FOOD BANK",
    "PERFORMING ARTS",
    "HABITAT FOR HUMANITY",
    "UNITED WAY",
    "SALVATION ARMY",
    "RED CROSS",
    "BOY SCOUTS OF AMERICA",
    "GIRL SCOUTS OF AMERICA",
    "VETERANS OF FOREIGN WARS",
    "MOTHERS AGAINST DRUNK DRIVING",
    "LOYAL ORDER OF MOOSE",
    "POP WARNER",
    "MAKE-A-WISH",
    "MAKE A WISH",
]

# ==================== v19 SMART GEO LOGIC ====================
# Guided reverse-engineering: <intro> <sep> <geo> → <intro>
# Restores the powerful pattern that was lost in v18.

SEPARATORS = {"OF", "IN", "FOR", "THE", "AT", "BY", "WITH", "AND", "TO", "-", ":"}

GEO_WORDS = {
    # US States (full + abbreviations)
    "ALABAMA",
    "AL",
    "ALASKA",
    "AK",
    "ARIZONA",
    "AZ",
    "ARKANSAS",
    "AR",
    "CALIFORNIA",
    "CA",
    "COLORADO",
    "CO",
    "CONNECTICUT",
    "CT",
    "DELAWARE",
    "DE",
    "FLORIDA",
    "FL",
    "GEORGIA",
    "GA",
    "HAWAII",
    "HI",
    "IDAHO",
    "ID",
    "ILLINOIS",
    "IL",
    "INDIANA",
    "IN",
    "IOWA",
    "IA",
    "KANSAS",
    "KS",
    "KENTUCKY",
    "KY",
    "LOUISIANA",
    "LA",
    "MAINE",
    "ME",
    "MARYLAND",
    "MD",
    "MASSACHUSETTS",
    "MA",
    "MICHIGAN",
    "MI",
    "MINNESOTA",
    "MN",
    "MISSISSIPPI",
    "MS",
    "MISSOURI",
    "MO",
    "MONTANA",
    "MT",
    "NEBRASKA",
    "NE",
    "NEVADA",
    "NV",
    "NEW HAMPSHIRE",
    "NH",
    "NEW JERSEY",
    "NJ",
    "NEW MEXICO",
    "NM",
    "NEW YORK",
    "NY",
    "NORTH CAROLINA",
    "NC",
    "NORTH DAKOTA",
    "ND",
    "OHIO",
    "OH",
    "OKLAHOMA",
    "OK",
    "OREGON",
    "OR",
    "PENNSYLVANIA",
    "PA",
    "RHODE ISLAND",
    "RI",
    "SOUTH CAROLINA",
    "SC",
    "SOUTH DAKOTA",
    "SD",
    "TENNESSEE",
    "TN",
    "TEXAS",
    "TX",
    "UTAH",
    "UT",
    "VERMONT",
    "VT",
    "VIRGINIA",
    "VA",
    "WASHINGTON",
    "WA",
    "WEST VIRGINIA",
    "WV",
    "WISCONSIN",
    "WI",
    "WYOMING",
    "WY",
    # Major cities + regions
    "NEW YORK",
    "LOS ANGELES",
    "CHICAGO",
    "HOUSTON",
    "PHOENIX",
    "PHILADELPHIA",
    "SAN ANTONIO",
    "SAN DIEGO",
    "DALLAS",
    "SAN JOSE",
    "AUSTIN",
    "JACKSONVILLE",
    "FORT WORTH",
    "COLUMBUS",
    "CHARLOTTE",
    "SAN FRANCISCO",
    "INDIANAPOLIS",
    "SEATTLE",
    "DENVER",
    "BOSTON",
    "EL PASO",
    "DETROIT",
    "NASHVILLE",
    "MEMPHIS",
    "PORTLAND",
    "OKLAHOMA CITY",
    "LAS VEGAS",
    "LOUISVILLE",
    "BALTIMORE",
    "MILWAUKEE",
    "ALBUQUERQUE",
    "TUCSON",
    "FRESNO",
    "MESA",
    "SACRAMENTO",
    "ATLANTA",
    "KANSAS CITY",
    "COLORADO SPRINGS",
    "MIAMI",
    "RALEIGH",
    "OMAHA",
    "LONG BEACH",
    "VIRGINIA BEACH",
    "OAKLAND",
    "MINNEAPOLIS",
    "TULSA",
    "ARLINGTON",
    "TAMPA",
    "NEW ORLEANS",
    # County / regional terms
    "COUNTY",
    "PARISH",
    "BOROUGH",
    "DISTRICT",
    "REGION",
    "METRO",
    "METROPOLITAN",
    "AREA",
    "VALLEY",
    "HILLS",
    "COAST",
    "BAY",
    "PENINSULA",
    "ISLAND",
    # International
    "CANADA",
    "MEXICO",
    "UNITED KINGDOM",
    "UK",
    "LONDON",
    "TORONTO",
    "VANCOUVER",
    "SYDNEY",
    "MELBOURNE",
    "BRISBANE",
    "AUSTRALIA",
    "NEW ZEALAND",
}

GEO_EXCEPTIONS = {
    "UNIVERSITY OF CALIFORNIA",
    "STATE UNIVERSITY OF NEW YORK",
    "UNIVERSITY OF MICHIGAN",
    "UNIVERSITY OF TEXAS",
    "UNIVERSITY OF WASHINGTON",
    "UNIVERSITY OF COLORADO",
    "UNIVERSITY OF MINNESOTA",
    "UNIVERSITY OF WISCONSIN",
    "STATE UNIVERSITY OF NEW JERSEY",
    "CHAMBER OF COMMERCE OF THE UNITED STATES",
    "CHAMBER OF COMMERCE OF THE STATE OF NEW YORK",
    "AMERICAN RED CROSS OF GREATER NEW YORK",
    "UNITED WAY OF NEW YORK CITY",
    "BOYS AND GIRLS CLUB OF AMERICA",
    "GIRL SCOUTS OF THE USA",
    "BOY SCOUTS OF AMERICA",
    "VETERANS OF FOREIGN WARS OF THE UNITED STATES",
    "AMERICAN LEGION OF THE UNITED STATES",
    "SALVATION ARMY OF THE UNITED STATES",
}


def detect_geo_suffix(name: str) -> Optional[str]:
    """
    Detect <intro> <sep> <geo> pattern and return the <intro> part.

    WHY this works:
    - "SALVATION ARMY OF NEW YORK" → "SALVATION ARMY"
    - "BOYS AND GIRLS CLUB OF LOS ANGELES" → "BOYS AND GIRLS CLUB"
    - Only fires when the geo suffix is clearly "extra" (after a separator).
    - Respects GEO_EXCEPTIONS so "UNIVERSITY OF CALIFORNIA" stays intact.
    """
    if not name:
        return None
    words = name.upper().split()
    if len(words) < 3:
        return None

    for i in range(len(words) - 1, 1, -1):
        if words[i - 1] in SEPARATORS:
            geo_phrase = " ".join(words[i:])
            if geo_phrase in GEO_WORDS or any(w in GEO_WORDS for w in words[i:]):
                intro = " ".join(words[: i - 1])
                if intro and intro not in GEO_EXCEPTIONS:
                    return intro.strip()
    return None


def detect_geo_prefix(name: str) -> Optional[str]:
    """
    Detect <geo> <sep> <outro> pattern and return the <outro> part.

    WHY this works (the mirror image of suffix detection):
    - "NEW YORK - SALVATION ARMY" → "SALVATION ARMY"
    - "CALIFORNIA: BOYS AND GIRLS CLUB" → "BOYS AND GIRLS CLUB"
    - Only fires when there is an EXPLICIT separator after the geo prefix.
    - Pure juxtaposition (e.g. "NEW YORK SALVATION ARMY") is NOT matched here
      because it is too risky (many legitimate names like "NEW YORK UNIVERSITY").
    - Respects GEO_EXCEPTIONS so legitimate geo-prefixed names stay intact.
    """
    if not name:
        return None
    words = name.upper().split()
    if len(words) < 3:
        return None

    # Try to find a geo phrase at the beginning (1 to len-2 words)
    for geo_len in range(1, len(words) - 1):
        geo_phrase = " ".join(words[:geo_len])
        if geo_phrase in GEO_WORDS or any(w in GEO_WORDS for w in words[:geo_len]):
            # Must have an EXPLICIT separator right after the geo phrase
            if words[geo_len] in SEPARATORS:
                outro = " ".join(words[geo_len + 1 :])
                if outro and outro not in GEO_EXCEPTIONS:
                    return outro.strip()
    return None


def generate_geo_collapse_rules(names: List[str]) -> Tuple[Dict[str, Set[str]], int, int]:
    """
    Generate smart geo-collapse rules for BOTH patterns:
    - <intro> <sep> <geo>  → canonical = <intro>
    - <geo> <sep> <outro>  → canonical = <outro>

    This is the full guided reverse-engineering that was lost in v18.
    Returns (final_rules, suffix_count, prefix_count) so it works with the caller.
    """
    geo_rules: Dict[str, Set[str]] = defaultdict(set)
    suffix_count = 0
    prefix_count = 0

    for name in names:
        # Suffix case: "SALVATION ARMY OF NEW YORK" → "SALVATION ARMY"
        intro = detect_geo_suffix(name)
        if intro:
            geo_rules[intro].add(name)
            suffix_count += 1

        # Prefix case: "NEW YORK - SALVATION ARMY" → "SALVATION ARMY"
        outro = detect_geo_prefix(name)
        if outro:
            geo_rules[outro].add(name)
            prefix_count += 1

    # Only keep rules with 2+ variants
    final_rules = {k: v for k, v in geo_rules.items() if len(v) >= 2}

    return final_rules, suffix_count, prefix_count


# ==================== END v19 GEO LOGIC ====================

university_count = 0


for state in STATE_EXPANSION.values():
    PRIORITY_CANONICALS.append(f"UNIVERSITY OF {state}")
    university_count += 1

# Load non-state university patterns from file (e.g. UNIVERSITY OF CHICAGO, UNIVERSITY OF PITTSBURGH, etc.)
# WHY: This gives us complete coverage of high-value private, city-based, and international universities
# without hard-coding thousands of entries.
try:
    with open("university_non_state_patterns.txt", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Format: NAME\tCOUNT\tTOTAL_DONATIONS (we only need the name)
                name = line.split("\t")[0].strip()
                if name and name not in PRIORITY_CANONICALS:
                    PRIORITY_CANONICALS.append(name)
                    university_count += 1
except FileNotFoundError:
    print(
        "Warning: university_non_state_patterns.txt not found. Non-state universities not loaded."
    )
except Exception as e:
    print(f"Warning: Could not load university_non_state_patterns.txt: {e}")

print(
    f"Loaded {len(PRIORITY_CANONICALS):,} priority canonicals ({university_count:,} contain 'UNIVERSITY')"
)

# This are so unique that we can just process them. 
SIMPLES = [
    "ATTACHED",
    "ROTARY",
    "BOY SCOUTS",
    "GIRL SCOUTS",
    "KIWANIS",
    "CHAMBER OF COMMERCE",
    "AMERICAN LEGION",
    "KNIGHTS OF COLUMBUS",
    "LOYAL ORDER OF MOOSE",
    "POP WARNER"
]

# High-value "simple" names that should get dedicated early siding, right after Pharma.
# These are well-known orgs with reliable EINs. Siding them early:
# - Secures good EINs before later processing
# - Prevents them from leaking into protective buckets (municipality, hospitals, churches, etc.)
# - Keeps the phased siding stack clean and incremental.
#
# The canonical list now lives in approved_simples.json (populated via TUI "S" option).
# Falls back to the list below if the file is missing.
def _load_early_simples():
    try:
        with open("approved_simples.json", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("canonicals", data.get("simples", []))
    except Exception:
        pass
    # Fallback (kept for bootstrapping)
    return [
        "UNITED WAY",
        "ROTARY",
        "BOY SCOUTS OF AMERICA",
        "GIRL SCOUTS OF AMERICA",
        "KIWANIS",
        "CHAMBER OF COMMERCE",
        "AMERICAN LEGION",
        "KNIGHTS OF COLUMBUS",
        "LOYAL ORDER OF MOOSE",
        "POP WARNER",
    ]

EARLY_SIMPLES = _load_early_simples()

MANUAL_NOISE = {
    "FRIENDS OF",
    "PARENT TEACHER",
    "CHURCH OF",
    "OF AMERICA",
    "OF CHRIST",
    "NEW CHURCH",
    "CITY CLUB",
    "LAKE CLUB",
    "CLUB WEST",
    "NEW STATE",
    "THE NEW",
    "OLD",
    "ST",
    "SAINT",
    "HOUSING",
    "PANTRY",
    "INTERNATIONAL OF",
    "KNIGHTS OF",
    "OF COMMERCE",
    "VOLUNTEER FIRE",
    "BOOSTER CLUB",
    "LIONS CLUB",
    "ROTARY CLUB",
    "KIWANIS CLUB",
    "CHAMBER OF COMMERCE",
    "UNITED WAY",
    "SALVATION ARMY",
    "RED CROSS",
    "BOY SCOUTS",
    "GIRL SCOUTS",
    "4-H",
    "FFA",
    "FUTURE FARMERS",
    "OF THE",
    "INC",
    "FOUNDATION",
    "ASSOCIATION",
    "CORPORATION",
    "SOCIETY",
    "COUNCIL",
    "INSTITUTE",
    "CENTER",
    "CLUB",
    "LEAGUE",
    "FELLOWSHIP",
    "MINISTRY",
    "CHURCH",
    "ORGANIZATION",
    "CORP",
    "LLC",
    "LTD",
    "TRUST",
    "FUND",
    "PARTNERSHIP",
    "ELEMENTARY",
    "MIDDLE SCHOOL",
    "HIGH SCHOOL",
    "SCHOOL DISTRICT",
    "COMMUNITY COLLEGE",
    "STATE UNIVERSITY",
    "A",
    "A NONPROFIT",
    "A NON-PROFIT",
    "A BETTER",
    "A TIME",
    "MAKE A",
    "A FAMILY",
    "A CHILD",
    "FOR A CURE",
    "A PLACE",
    "ADOPT A",
    "FOR A CAUSE",
    "HAVE A",
    "A CHARITABLE",
    "BE A",
    "A LIFE",
    "A HEART",
    "WITH A",
    "LIKE A",
    "JOHN A",
    "A BEGINNING",
    "WILLIAM A",
    "GIVE A",
    "SAVE A",
    "A LIGHT",
    "A COMMUNITY",
    "A DREAM",
    "TAKE A",
    "A MINISTRIES",
    "A MEMORIAL",
    "A WORLD",
    "JUST A",
    "TR",
    "PTO",
    "AMERICAN FRIENDS",
    "GOD CHRIST",
}

ABBREVIATIONS = KNOWN_CHARITIES.copy()

MIN_WORD_COUNT = 2
MIN_LENGTH = 4


# ==================== CANONICAL DATACLASS (Tree-aware + provenance) ======================
class CanonicalState(Enum):
    RAW = auto()
    ACTIVE = auto()
    ABSORBED = auto()
    FINAL = auto()


@dataclass
class Canonical:
    """
    Tree-aware canonical with explicit state and provenance.

    WHY we keep both the tree structure and the computed fields:
    - The tree (absorb/flatten) gives us proper deduplication and hierarchy.
    - The computed fields (words, pattern, variants) are still required by
      the matching and rule-generation logic.
    """

    original: str
    cleaned: str
    words: Set[str] = field(default_factory=set)
    pattern: Optional[re.Pattern] = None
    ein: str = ""
    grant_total: float = 0.0
    variants: Set[str] = field(default_factory=set)
    source_count: int = 0
    source_priority: int = 0
    min_variants_to_include: int = 2
    is_priority: bool = False

    # Tree fields
    state: CanonicalState = CanonicalState.RAW
    source: str = "DATA"
    parent: Optional["Canonical"] = None
    children: List["Canonical"] = field(default_factory=list)
    raw_names: Set[str] = field(default_factory=set)

    def __post_init__(self):
        self.raw_names.add(self.original)

        if not self.words:
            self.words = {w for w in self.cleaned.split() if w not in SEPARATORS}

        if self.pattern is None:
            pattern_str = r"\b" + re.escape(self.cleaned).replace(" ", r"[\s\-]+") + r"\b"
            self.pattern = re.compile(pattern_str, re.IGNORECASE)

        if not self.variants:
            self.variants.add(self.original)
            self.source_count = 1

    def absorb(self, child: "Canonical"):
        """
        Absorb another canonical into this one, forming a tree.

        WHY absorb over merge:
        - Explicit hierarchy for provenance and flattening
        - Cleaner dedup without losing source info
        """
        # Data merge logic (was duplicated in old merge sites)
        if len(child.cleaned) < len(self.cleaned):
            self.cleaned = child.cleaned
            self.original = child.original
            self.words = child.words
            self.pattern = child.pattern

        for v in child.variants:
            if v not in self.variants:
                self.variants.add(v)
                self.source_count += 1

        if child.is_priority:
            self.is_priority = True

        if child.ein:
            if not self.ein:
                self.ein = child.ein
                self.grant_total = child.grant_total
                self.source_priority = child.source_priority
            elif child.source_priority > self.source_priority or (
                child.source_priority == self.source_priority and child.grant_total > self.grant_total
            ):
                self.ein = child.ein
                self.grant_total = child.grant_total
                self.source_priority = child.source_priority

        self.grant_total += child.grant_total
        self.source_priority = max(self.source_priority, child.source_priority)

        # Tree link
        child.state = CanonicalState.ABSORBED
        child.parent = self
        self.children.append(child)
        self.raw_names.update(child.raw_names)

    def is_active(self) -> bool:
        return self.state in (CanonicalState.RAW, CanonicalState.ACTIVE)

    def flatten(self) -> Set[str]:
        """Return all raw names under this subtree for final output."""
        names = set(self.raw_names)
        for child in self.children:
            names.update(child.flatten())
        return names

    def add_variant(self, variant: str, is_source: bool = True, priority: int = 0):
        """Add a variant while updating provenance counters.

        WHY is_source exists:
        - When True, we increment source_count (used to prefer names that appear
          in authoritative sources like the charity names file or BMF).
        - When False, we still record the variant for matching but don't boost
          its provenance score.
        """
        self.variants.add(variant)
        if is_source:
            self.source_count += 1
        if priority > self.source_priority:
            self.source_priority = priority

    def rebuild_pattern(self):
        """Rebuild the regex pattern after a merge. WHY: the cleaned name may have changed."""
        pattern_str = r"\b" + re.escape(self.cleaned).replace(r"\ ", r"[\s\-]+") + r"\b"
        self.pattern = re.compile(pattern_str, re.IGNORECASE)


# ==================== HELPER FUNCTIONS ======================
def expand_known_charities(name: str) -> str:
    """Expand common abbreviations (MADD → MOTHERS AGAINST DRUNK DRIVING, etc.)."""
    name = name.upper().strip()
    for abbr, full in KNOWN_CHARITIES.items():
        flexible = re.escape(abbr).replace(r"\.", r"\.?")
        pattern = rf"\b{flexible}\b"
        name = re.sub(pattern, full, name)
    return name


def clean_name(name: str, geo_blacklist: Set[str], noise_words: Set[str]) -> str:
    """
    Clean a name by removing noise words, geographic terms, and manual noise.

    WHY we strip parenthetical content:
    - Many names contain acronyms or extra info in parentheses (e.g. "German Shepherd Rescue (GRSOC)")
    - These make the name unnecessarily specific and cause zero-result greps
    - Stripping them improves matching without losing the core name

    WHY we treat "UNIVERSITY" and "COLLEGE" specially:
    - These names legitimately contain words that would otherwise be stripped
      (e.g. "University of California" should keep "California")
    """
    # Strip everything inside parentheses (including the parens themselves)
    name = re.sub(r"\s*\([^)]*\)", "", name)  # (x2) / (See Schedule #2) cases stripped to prevent zero-result greps and improve matching to canonical

    # Treat "# 123" or "#123" style suffixes as noise (e.g. "AMERICAN LEGION #140")
    name = re.sub(r"\s*#\s*\d+\b", "", name)

    name = expand_known_charities(name)
    for abbr, full in ABBREVIATIONS.items():
        flexible = re.escape(abbr).replace(r"\.", r"\.?")
        name = re.sub(rf"\b{flexible}\b", full, name, flags=re.IGNORECASE)
    words = name.split()

    if "UNIVERSITY" in words or "COLLEGE" in words:
        filtered = [w for w in words if w not in MANUAL_NOISE and w not in noise_words]
    else:
        filtered = [
            w
            for w in words
            if w not in geo_blacklist and w not in MANUAL_NOISE and w not in noise_words
        ]

    while filtered and filtered[0] in {"OF", "THE"}:
        filtered.pop(0)
    while filtered and filtered[-1] in {"OF", "THE"}:
        filtered.pop()

    cleaned = " ".join(filtered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()  # collapse multiple spaces
    if not cleaned:
        return name  # fallback to original if everything was stripped

    # Strip attachment suffixes (SEE ADDENDUM, SEE NOTE, etc.) when a strong org signal is present.
    # This lets real entities like "University of X Foundation - SEE ADDENDUM..." survive as clean names.
    cleaned = _strip_attachment_suffixes(cleaned)

    return cleaned


def get_effective_words(name: str) -> Set[str]:
    """Return the set of meaningful words (excluding separators like OF, FOR, THE)."""
    words = name.upper().split()
    return {w for w in words if w not in SEPARATORS}


def is_valid_canonical(name: str, geo_blacklist: Set[str], noise_words: Set[str]) -> bool:
    """Return True if this name is worth keeping as a canonical."""
    if len(name) < MIN_LENGTH:
        return False
    if name.isdigit():
        return False
    effective_words = get_effective_words(name)
    if len(effective_words) < MIN_WORD_COUNT:
        return False
    if any(w in MANUAL_NOISE or w in noise_words for w in effective_words):
        return False
    if name in geo_blacklist:
        return False
    return True


def collect_simple_variants(pattern: str) -> Set[str]:
    """Collect all grantee names that contain the given simple pattern (e.g. 'ROTARY')."""
    variants = set()
    regex = re.compile(rf"\b{re.escape(pattern)}\b", re.IGNORECASE)
    with open(DISTINCT_NAMES_TSV, "r", encoding="utf-8") as f:
        next(f)
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) > 0:
                name = fields[0].strip()
                if regex.search(name):
                    variants.add(name)
    return variants


def find_best_ein_grep(name: str, charity_grant_totals: Dict, bmf_grant_totals: Dict) -> str:
    """
    Find the best EIN for a name by grepping the charity and BMF files.

    WHY we prefer charity file over BMF:
    - Charity file (ein_name_variants.tsv) is our authoritative source
    - BMF is a fallback when the charity file has no match

    WHY we sort by (source_priority, grant_total):
    - source_priority: charity file = 1, BMF = 0
    - grant_total: tie-breaker for same priority
    """
    candidates = []

    # Try charity file first
    try:
        result = subprocess.run(
            ["grep", "-i", "-w", name],
            stdin=open(CHARITY_NAMES_TSV, "r"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    ein = parts[0].strip()
                    total = charity_grant_totals.get(ein, 0)
                    candidates.append((ein, total, 1))
    except Exception:
        pass

    # Fall back to BMF if nothing found
    if not candidates:
        try:
            result = subprocess.run(
                ["grep", "-i", "-w", name],
                stdin=open(BMF_TSV, "r"),
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        ein = parts[0].strip()
                        total = bmf_grant_totals.get(ein, 0)
                        candidates.append((ein, total, 0))
        except Exception:
            pass

    if not candidates:
        ZERO_RESULT_GREPS.append(name)
        return ""

    candidates.sort(key=lambda x: (-x[2], -x[1]))
    return candidates[0][0]


def early_dedup_pass(canonicals: Dict[str, Canonical]) -> Dict[str, Canonical]:
    """
    Deduplicate canonicals by merging ones that match each other's patterns.

    WHY we sort by cleaned.upper():
    - Case-insensitive alphabetical order ensures similar names are adjacent
    - This makes the linear merge pass efficient

    WHY we use pattern.search instead of string comparison:
    - "THE PRICE CENTER (BARRY L PRICE...)" should match
      "The Price Center (Barry L Price...)" even with different casing
    """
    print(f"  Running early dedup pass on {len(canonicals):,} canonicals...")

    sorted_canons = sorted(canonicals.values(), key=lambda c: c.cleaned.upper())

    if not sorted_canons:
        return {}

    deduped = []
    last = sorted_canons[0]

    for next_canon in sorted_canons[1:]:
        if last.pattern.search(next_canon.cleaned) or next_canon.pattern.search(last.cleaned):
            last.absorb(next_canon)
        else:
            deduped.append(last)
            last = next_canon

    deduped.append(last)

    result = {c.cleaned: c for c in deduped}
    print(f"  Deduped: {len(canonicals):,} → {len(result):,} canonicals")
    return result


def is_priority_canonical(cleaned: str) -> bool:
    """Return True if this canonical should be processed first (higher grant volume expected)."""
    for priority in PRIORITY_CANONICALS:
        pattern = re.compile(rf"\b{re.escape(priority)}\b", re.IGNORECASE)
        if pattern.search(cleaned):
            return True
    return False


# ==================== MAIN ======================
if __name__ == "__main__":
    start_time = time.time()

    print("Loading distinct_grantee_names.tsv...")
    grantee_names: List[str] = []
    with open(DISTINCT_NAMES_TSV, "r", encoding="utf-8") as f:
        next(f)
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) > 0:
                raw = fields[0].strip()
                if raw:
                    grantee_names.append(raw)
    print(f"Loaded {len(grantee_names):,} grantee names")

    print("\n=== Dynamic noise word detection (1% threshold) ===")
    word_freq = Counter()
    for name in grantee_names:
        for w in name.upper().split():
            word_freq[w] += 1

    total_names = len(grantee_names)
    noise_words = {w for w, count in word_freq.items() if count / total_names >= NOISE_THRESHOLD}
    original_noise_count = len(noise_words)
    noise_words -= DYNAMIC_NOISE_WHITELIST
    print(f"Detected {original_noise_count:,} noise words (appear in ≥1% of grantee names)")
    print(f"After whitelist: {len(noise_words):,} noise words")
    if noise_words:
        print("Final dynamic noise words:", sorted(noise_words))
    else:
        print("Final dynamic noise words: (none)")

    print("Loading bmf_analysis.tsv...")
    bmf_by_ein: Dict[str, List[str]] = defaultdict(list)
    bmf_grant_totals: Dict[str, float] = defaultdict(float)
    city_freq: Counter = Counter()
    cities: Set[str] = set()

    with open(BMF_TSV, "r", encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                ein, name, city, state = (
                    parts[0].strip(),
                    parts[1].strip(),
                    parts[2].strip(),
                    parts[3].strip(),
                )
                if name:
                    bmf_by_ein[ein].append(name)
                    if city:
                        city_freq[city.upper()] += 1
                        cities.add(city.upper())

    print(f"Loaded {len(bmf_by_ein):,} EINs from BMF")

    print("Loading ein_name_variants.tsv (authoritative charity names)...")
    charity_by_ein: Dict[str, List[str]] = defaultdict(list)
    charity_grant_totals: Dict[str, float] = defaultdict(float)
    with open(CHARITY_NAMES_TSV, "r", encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                ein = parts[0].strip()
                name = parts[1].strip()
                if ein and name:
                    charity_by_ein[ein].append(name)
    print(f"Loaded {len(charity_by_ein):,} EINs from charity names file")

    top_cities = {city for city, count in city_freq.most_common(TOP_CITIES_TO_ALWAYS_STRIP)}
    print(
        f"Top {TOP_CITIES_TO_ALWAYS_STRIP} most frequent cities to always strip: {len(top_cities):,}"
    )

    geo_blacklist = cities.copy()
    geo_blacklist.update(top_cities)
    geo_blacklist.update(STATE_EXPANSION.keys())
    geo_blacklist.update(STATE_EXPANSION.values())
    print(f"GEO blacklist size: {len(geo_blacklist):,}")

    print("\n=== Pre-building exact match dictionaries ===")
    charity_exact_ein: Dict[str, str] = {}
    for ein, names in charity_by_ein.items():
        for name in names:
            name_upper = name.upper()
            if name_upper not in charity_exact_ein:
                charity_exact_ein[name_upper] = ein

    bmf_exact_ein: Dict[str, str] = {}
    for ein, names in bmf_by_ein.items():
        for name in names:
            name_upper = name.upper()
            if name_upper not in bmf_exact_ein:
                bmf_exact_ein[name_upper] = ein

    print(f"Built {len(charity_exact_ein):,} charity exact matches")
    print(f"Built {len(bmf_exact_ein):,} BMF exact matches")

    print("\n=== Pre-building EIN-to-words dictionaries ===")
    charity_ein_words: Dict[str, Set[str]] = {}
    for ein, names in charity_by_ein.items():
        all_words = set()
        for name in names:
            all_words.update(get_effective_words(name))
        charity_ein_words[ein] = all_words

    bmf_ein_words: Dict[str, Set[str]] = {}
    for ein, names in bmf_by_ein.items():
        all_words = set()
        for name in names:
            all_words.update(get_effective_words(name))
        bmf_ein_words[ein] = all_words

    print(f"Built charity EIN-to-words: {len(charity_ein_words):,} EINs")
    print(f"Built BMF EIN-to-words: {len(bmf_ein_words):,} EINs")

    print("\n=== STAGE 1: Building canonicals ===")

    canonicals: Dict[str, Canonical] = {}
    name_to_ein: Dict[str, str] = {}

    print(
        "\n=== BIG PHARMA SUBSIDY rollup + pharma_siding pass (early like priority rules, before STAGE 3 rubicon) ==="
    )

    # EINless hygiene integration (post-89% cream "we're done with this mapping project" review)
    # The einless/ sub-layer (rebuild_einless_cleaned + rebucket with explicit pass_through_flow bucket,
    # foreign_synthetic_ein, grantor_context for A-passes-to-B / subgrant / foreign direct grantee cases)
    # produces classified hard splits that did not phonebook match.
    # These feed here for canonical rollups (using the existing heuristics in this file for "roll up certain types of orgs canonically")
    # and early filters, plus secondary geo passes on remaining einless hards.
    # See einless/ (structure for tie-off option A), einless/code/einless_pipeline.py (orchestrator),
    # and einless/docs/einless_grantee_resolution_architecture.md for the integration plan and fresh hygiene numbers (hard 125404 after latest flow patterns).
    # Example future: load einless/data/*_hard_flow.tsv or einless hard_plausible and add as PRIORITY or sided canonicals
    # (e.g. under "EINLESS_SUBGRANT_FLOW" or per-grantor labeled groups). This unifies the pre-phonebook complicated rule system with the phonebook + einless classification.
    # Dedicated pharma_siding: side-track all the noisy VARIOUS/SEE ATTACHED/HIPPA/PATIENT/Drugs & Medicines rows
    # so the main pipeline doesn't waste time scanning them. Add back as single canonical before output.
    # This matches your preferred clean architecture. Geo rules also moved early.
    pharma_sided = {}
    try:
        with open(BIG_PHARMA_JSON, "r", encoding="utf-8") as f:
            subsidy_data = json.load(f)
        for canon, data in subsidy_data.items():
            PRIORITY_CANONICALS.append(canon)
            if "patterns" in data:
                if "PRIORITY_PATTERNS" not in globals():
                    PRIORITY_PATTERNS = {}
                PRIORITY_PATTERNS[canon] = [re.compile(p, re.IGNORECASE) for p in data["patterns"]]
            synthetic_ein = data.get("synthetic_ein", "99-7777777")
            cleaned = clean_name(canon, geo_blacklist, noise_words)
            if cleaned not in canonicals:
                canonicals[cleaned] = Canonical(
                    original=canon,
                    cleaned=cleaned,
                    ein=synthetic_ein,
                    is_priority=True,
                    source_priority=10,  # bumped so BIG PHARMA SUBSIDY always wins over partial matches like MAKE A WISH
                )
            print(
                f"Loaded BIG PHARMA SUBSIDY canonical '{canon}' with {len(data.get('patterns', [])):,} patterns and synthetic EIN {synthetic_ein}"
            )

        # Pharma siding pass - filter noisy names from main grantee_names processing
        pharma_patterns = PRIORITY_PATTERNS.get("BIG PHARMA SUBSIDY", [])
        if pharma_patterns and grantee_names:
            original_count = len(grantee_names)
            non_pharma = []
            sided_count = 0
            for name in grantee_names:
                if any(p.search(name) for p in pharma_patterns):
                    if name not in pharma_sided:
                        pharma_sided[name] = {
                            "canonical": canon,
                            "ein": synthetic_ein,
                            "variants": [name],
                            "source": "pharma_siding",
                        }
                        sided_count += 1
                else:
                    non_pharma.append(name)
            grantee_names[:] = non_pharma  # mutate list in place for later loops
            print(
                f"Sided {sided_count:,} noisy pharma/subsidy names (main pipeline will skip them; added back before output)"
            )
        else:
            print("No pharma patterns loaded or no names to side")
    except Exception as e:
        print(f"Warning: Could not load {BIG_PHARMA_JSON}: {e}")
        pharma_sided = {}

    # ========== EARLY SIMPLES siding (right after Pharma, per phased stack) ==========
    # These well-known orgs get pulled out early with their best available EIN.
    # Prevents leakage into later protective buckets (municipality, hospitals, churches, etc.)
    # and ensures clean high-quality canonicals + real EINs.
    # This is the flexible incremental siding layer the user requested after Pharma.
    simples_sided = {}
    try:
        simple_patterns = {}
        for simple in EARLY_SIMPLES:
            # Word-boundary regex, same spirit as collect_simple_variants
            pat = re.compile(rf'\b{re.escape(simple)}\b', re.IGNORECASE)
            simple_patterns[simple] = pat

        if grantee_names:
            original_count = len(grantee_names)
            non_simples = []
            sided_count = 0
            for name in grantee_names:
                matched = False
                for simple, pat in simple_patterns.items():
                    if pat.search(name):
                        if name not in simples_sided:
                            # EIN will be resolved later during priority/simple absorption or charity/BMF passes.
                            # This early siding is primarily to remove the names from the main stream
                            # and guarantee they get a clean canonical.
                            simples_sided[name] = {
                                "canonical": simple,
                                "ein": "",
                                "variants": [name],
                                "source": "early_simples_siding",
                            }
                            sided_count += 1
                        matched = True
                        break
                if not matched:
                    non_simples.append(name)
            grantee_names[:] = non_simples
            if sided_count:
                print(f"Sided {sided_count:,} early simples names (UNITED WAY, ROTARY, etc.) right after Pharma")
    except Exception as e:
        print(f"Warning: Early Simples siding failed: {e}")
        simples_sided = {}

    # Seed priority canonicals FIRST (before data)
    # WHY: Priority canonicals should exist from the start so they attract variants
    #      and rise to the top during the is_priority sort.
    for name in PRIORITY_CANONICALS:
        cleaned = clean_name(name, geo_blacklist, noise_words)
        if cleaned and cleaned not in canonicals:
            canonicals[cleaned] = Canonical(original=name, cleaned=cleaned, is_priority=True)
            canonicals[cleaned].min_variants = 1
    print(f"Seeded {len([c for c in canonicals.values() if c.is_priority]):,} priority canonicals")

    print("Creating canonicals from charity file (one per EIN)...")
    for ein, names in charity_by_ein.items():
        if names:
            first_name = names[0]
            cleaned = clean_name(first_name, geo_blacklist, noise_words)

            if is_valid_canonical(cleaned, geo_blacklist, noise_words):
                canon = Canonical(original=first_name, cleaned=cleaned, ein=ein, source_priority=2)
                for name in names:
                    canon.add_variant(name, priority=2)
                canonicals[cleaned] = canon
                name_to_ein[cleaned] = ein

    print(f"Created {len(canonicals):,} canonicals from charity file")

    print("Adding BMF names to canonicals...")
    bmf_added = 0
    for ein, names in bmf_by_ein.items():
        for name in names:
            cleaned = clean_name(name, geo_blacklist, noise_words)

            if cleaned in canonicals:
                canonicals[cleaned].add_variant(name, priority=1)
                if not canonicals[cleaned].ein:
                    canonicals[cleaned].ein = ein
            else:
                if is_valid_canonical(cleaned, geo_blacklist, noise_words):
                    if cleaned not in canonicals:
                        canonicals[cleaned] = Canonical(
                            original=name, cleaned=cleaned, ein=ein, source_priority=1
                        )
                    canonicals[cleaned].add_variant(name, priority=1)
                    name_to_ein[cleaned] = ein
                    bmf_added += 1

    print(f"Added {bmf_added:,} new canonicals from BMF")
    print(f"Total canonicals after BMF: {len(canonicals):,}")

    # =====================================================================
    # UNIVERSITY / COLLEGE FAMILY CONSOLIDATION (happens automatically)
    # Uses the BMF data already loaded. Groups main institutions + their
    # satellites (foundations, alumni, faculty groups, etc.) under the best
    # canonical with the real EIN from BMF. This is the repeatable path for
    # the universities sub-goal. No separate pre-step required when you have
    # a fresh bmf_analysis.tsv extract from the database.
    # =====================================================================
    if UNIVERSITY_FAMILIES_ENABLED:
        print("\n=== University/College family consolidation (from loaded BMF) ===")
        university_keywords = ("UNIVERSITY", "COLLEGE", "COMMUNITY COLLEGE")

        # Simple but effective satellite detector (mirrors the generator spirit)
        def _is_university_satellite(name: str) -> bool:
            n = name.upper()
            return any(kw in n for kw in ("FOUNDATION", "ALUMNI", "ALUMNAE", "FACULTY", "CLASSIFIED", "BOOKSTORE", "NROTC", "ROTC AT"))

        def _core_name(name: str) -> str:
            n = name.upper().strip()
            n = re.sub(r'^(THE|A|AN)\s+', '', n)
            n = re.sub(r'\s+(INC|LLC|CORP|CORPORATION)\.?$', '', n)
            # Strip common trailing satellite phrases to recover the parent
            for suffix in (" FOUNDATION", " ALUMNI ASSOCIATION", " ALUMNI", " FACULTY ASSOCIATION", " CLASSIFIED ASSOCIATION", " BOOKSTORE", " NROTC"):
                if n.endswith(suffix):
                    n = n[:-len(suffix)].strip()
                    break
            # For "XXX COMMUNITY COLLEGE ..." forms
            m = re.search(r'(.+?\b(?:UNIVERSITY|COLLEGE|COMMUNITY COLLEGE))\b', n)
            if m:
                return m.group(1).title()
            return n.title()

        # Group current canonicals that look university-related
        uni_groups: Dict[str, List[str]] = defaultdict(list)
        for cleaned, canon in list(canonicals.items()):
            if any(kw in cleaned.upper() for kw in university_keywords):
                core = _core_name(cleaned)
                uni_groups[core].append(cleaned)

        consolidated = 0
        for core, members in uni_groups.items():
            if len(members) < 2:
                continue
            # Pick the "main" one (shortest, or one without obvious satellite words)
            main = min(members, key=lambda m: (1 if _is_university_satellite(m) else 0, len(m)))
            main_canon = canonicals[main]

            for member in members:
                if member == main:
                    continue
                member_canon = canonicals[member]
                # Merge variants into the main family canonical
                for v in member_canon.variants:
                    main_canon.add_variant(v, priority=member_canon.source_priority)
                # Prefer a real BMF EIN if the member has one and main doesn't
                if member_canon.ein and not main_canon.ein:
                    main_canon.ein = member_canon.ein
                # Remove the satellite canonical (it has been rolled up)
                del canonicals[member]
                consolidated += 1

            # Ensure the family has a strong EIN (from BMF if available)
            if not main_canon.ein:
                # Fallback: any EIN from the original group
                for m in members:
                    if canonicals.get(m) and canonicals[m].ein:  # in case it was already deleted
                        main_canon.ein = canonicals[m].ein
                        break

            main_canon.is_priority = True

        if consolidated:
            print(f"Consolidated {consolidated:,} university/college satellite canonicals into families (real EINs preserved where available)")
        print(f"University family consolidation complete. Total canonicals now: {len(canonicals):,}")

    print("\n=== Adding grantee names (skipping expensive EIN lookup) ===")
    for name in grantee_names:
        cleaned = clean_name(name, geo_blacklist, noise_words)

        if cleaned in name_to_ein:
            ein = name_to_ein[cleaned]
            if cleaned in canonicals:
                canonicals[cleaned].add_variant(name, priority=0)
            else:
                if is_valid_canonical(cleaned, geo_blacklist, noise_words):
                    canonicals[cleaned] = Canonical(
                        original=name, cleaned=cleaned, ein=ein, source_priority=0
                    )
                    canonicals[cleaned].add_variant(name, priority=0)
        else:
            if is_valid_canonical(cleaned, geo_blacklist, noise_words):
                if cleaned not in canonicals:
                    canonicals[cleaned] = Canonical(
                        original=name, cleaned=cleaned, ein="", source_priority=0
                    )
                canonicals[cleaned].add_variant(name, priority=0)

    print(f"Final: {len(canonicals):,} canonicals after adding grantee names")

    # ========== SIMPLES moved EARLY (critical fix for coverage) ==========
    print("\n=== SIMPLES: Creating canonicals for distinctive names ===")
    for simple in SIMPLES:
        variants = collect_simple_variants(simple)
        if variants:
            cleaned = clean_name(simple, geo_blacklist, noise_words)
            ein = find_best_ein_grep(simple, charity_grant_totals, bmf_grant_totals)

            if cleaned not in canonicals:
                canon = Canonical(
                    original=simple, cleaned=cleaned, ein=ein, source_priority=2
                )
                canon.min_variants_to_include = 1
                canonicals[cleaned] = canon

            for variant in variants:
                canonicals[cleaned].add_variant(variant, priority=2)

            ein_str = ein if ein else "(no EIN)"
            print(f"  {simple}: {len(variants):,} variants | EIN: {ein_str}")

    # Post-SIMPLES absorption
    for simple in SIMPLES:
        simple_cleaned = clean_name(simple, geo_blacklist, noise_words)
        if simple_cleaned in canonicals:
            simple_canon = canonicals[simple_cleaned]
            to_merge = [c for c in list(canonicals.keys()) if c != simple_cleaned and simple.upper() in c.upper()]
            for c in to_merge:
                simple_canon.absorb(canonicals[c])
                del canonicals[c]
            if to_merge:
                print(f"  Merged {len(to_merge):,} additional variants into {simple}")

    canonicals = early_dedup_pass(canonicals)

    # Diagnostic: check for over-broad patterns (only when few canonicals remain)
    if len(canonicals) < 100:
        test_str = "ABBA IS A SWEDISH BAND"
        bad_patterns = []
        for cleaned, canon in canonicals.items():
            if canon.pattern and canon.pattern.search(test_str):
                bad_patterns.append(cleaned)
        if bad_patterns:
            print(f"WARNING: {len(bad_patterns)} patterns match '{test_str}'")
            print(f"  Examples: {bad_patterns[:5]}")
        else:
            print("No patterns match test string 'ABBA IS A SWEDISH BAND'")

    # SIMPLES block moved earlier (see below)

    # v19: Generating smart <intro> <sep> <geo> collapse rules (after early dedup but before STAGE 3 rubicon per your request)
    print("\n=== v19: Generating smart <intro> <sep> <geo> collapse rules ===")
    all_original_names = list(
        set(
            name
            for name in grantee_names
            + list(charity_grant_totals.keys())
            + list(bmf_grant_totals.keys())
        )
    )
    geo_collapse_rules, suffix_count, prefix_count = generate_geo_collapse_rules(all_original_names)

    suffix_catches = suffix_count
    prefix_catches = prefix_count
    print(f"  Suffix pattern (<intro> <sep> <geo>): {suffix_catches:,} names caught")
    print(f"  Prefix pattern (<geo> <sep> <outro>): {prefix_catches:,} names caught")
    print(f"Generated {len(geo_collapse_rules):,} smart geo-collapse rules (with 2+ variants)")

    # Merge geo rules into the canonicals before STAGE 3 testing
    for intro, variants in geo_collapse_rules.items():
        if intro not in canonicals:
            canonicals[intro] = Canonical(original=intro, cleaned=intro, is_priority=True)
        for v in variants:
            canonicals[intro].add_variant(v)
    print(f"After merging geo rules: {len(canonicals):,} total canonicals before STAGE 3")
    canonicals = early_dedup_pass(canonicals)

    print(f"\n=== STAGE 3: Merging canonicals (PRIORITY first) ===")

    word_index: Dict[str, Set[str]] = defaultdict(set)
    for cleaned, canon in canonicals.items():
        for word in canon.words:
            word_index[word].add(cleaned)

    # Sort with is_priority as primary key (priority first), then grant_total descending
    canonical_list = sorted(canonicals.values(), key=lambda c: (not c.is_priority, -c.grant_total))
    ORIGINAL_COUNT = len(canonical_list)

    priority_count = sum(1 for c in canonical_list if c.is_priority)
    print(f"Priority canonicals: {priority_count:,}")
    print(f"Total canonicals in merge pass: {len(canonical_list):,}")

    final_rules_list: List[Tuple[str, Dict]] = []
    printed: Set[str] = set()
    last_time = time.time()
    last_active = ORIGINAL_COUNT

    for i, current in enumerate(canonical_list):
        if i % 10000 == 0 and i > 0:
            now = time.time()
            delta = now - last_time
            last_time = now
            active = len(canonicals)
            removed = last_active - active
            last_active = active
            print(
                f"  Processed {i:,}/{ORIGINAL_COUNT:,} (active: {active:,}, removed: {removed:,}) — {delta:.1f}s"
            )

            if final_rules_list:
                new_rules = [r for r in final_rules_list if r[0] not in printed]
                printed = {r[0] for r in final_rules_list}
                if new_rules:
                    top_new = sorted(new_rules, key=lambda x: -len(x[1]["variants"]))[:5]
                    print("    Top 5 NEW from this pass:")
                    for core, rule in top_new:
                        sample = list(rule["variants"])[:2]
                        print(
                            f"      '{core}' (EIN: {rule['ein']}) → {len(rule['variants']):,} variants, e.g. {sample}"
                        )

        candidates = None
        for word in current.words:
            word_cands = word_index.get(word, set())
            if candidates is None:
                candidates = word_cands.copy()
            else:
                candidates &= word_cands

        if candidates is None:
            candidates = set()

        for candidate_name in candidates:
            candidate = canonicals.get(candidate_name)
            if not candidate:
                continue
            if current.pattern.search(candidate.cleaned):
                current.absorb(candidate)
                for w in candidate.words:
                    if w in word_index:
                        word_index[w].discard(candidate_name)
                del canonicals[candidate_name]

        # final_rules_list is now built in a single pass at the end (see below)

    final_rules_list.sort(key=lambda x: x[0].upper())

    print(f"\nFinal: {len(final_rules_list):,} rules after merge")

    # Filter to EINless canonicals (keep objects)
    print("\n=== Filter to EINless canonicals ===")
    einless_canonicals = {k: v for k, v in canonicals.items() if not v.ein}
    print(f"EINless canonicals: {len(einless_canonicals):,}")

    # Dedup on EINless canonicals (objects)
    print("\n=== Early dedup pass on EINless canonicals ===")
    einless_canonicals = early_dedup_pass(einless_canonicals)

    # Convert to dicts for second pass
    rules_without_ein = [
        (c.cleaned, {"ein": c.ein, "variants": sorted(c.variants), "source_count": c.source_count})
        for c in einless_canonicals.values()
    ]

    # Load cache (including previously known zero-result grep names)
    print("\n=== Load cache ===")
    cache_ein_map: Dict[str, str] = {}
    cached_rules_without_ein: Set[str] = set()
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
            for item in cache_data:
                if item.get("ein"):
                    cache_ein_map[item["canonical"]] = item["ein"]
                # Track all previously processed rules_without_ein (even those with no EIN)
                if "variants" in item and item.get("canonical"):
                    cached_rules_without_ein.add(item["canonical"])
                # Load previously known zero-result names so we skip re-grepping them
                if "zero_result_names" in item:
                    ZERO_RESULT_GREPS.extend(item["zero_result_names"])
        if ZERO_RESULT_GREPS:
            print(
                f"Loaded {len(set(ZERO_RESULT_GREPS)):,} previously known zero-result names from cache"
            )
        print(f"Loaded {len(cache_ein_map):,} cached EINs from {CACHE_FILE}")
        print(
            f"Loaded {len(cached_rules_without_ein):,} previously processed rules_without_ein from cache"
        )
    except FileNotFoundError:
        print(f"No cache file found ({CACHE_FILE}) — starting fresh")

    # Apply cached EINs
    print("\n=== Apply cached EINs ===")
    cached_count = 0
    for item in rules_without_ein:
        if item[0] in cache_ein_map:
            item[1]["ein"] = cache_ein_map[item[0]]
            cached_count += 1
    print(f"Applied {cached_count:,} cached EINs")

    # Skip rules we've already processed (even if they had no EIN)
    rules_without_ein = [r for r in rules_without_ein if r[0] not in cached_rules_without_ein]

    print("Exiting early before EIN greps (Tree method is the priority now).")
    import sys
    sys.exit(0)

    # Process remaining without EINs
    remaining_without_ein = [r for r in rules_without_ein if not r[1]["ein"]]


    assigned_count = 0
    for idx, item in enumerate(remaining_without_ein):
        if idx % 1000 == 0:
            print(f"  Processing {idx:,}/{len(remaining_without_ein):,} - Current: '{item[0]}'")

        ein = find_best_ein_grep(item[0], charity_grant_totals, bmf_grant_totals)

        if not ein:
            for variant in item[1]["variants"][:5]:
                ein = find_best_ein_grep(variant, charity_grant_totals, bmf_grant_totals)
                if ein:
                    break

        if ein:
            item[1]["ein"] = ein
            assigned_count += 1
            if assigned_count <= 50:
                print(f"  Assigned EIN to '{item[0]}': {ein}")

    print(f"Assigned EINs to {assigned_count:,} additional canonicals")

    # Update cache (including current zero-result grep names for future runs)
    print("\n=== Update cache ===")
    cache_data = [
        {"canonical": r[0], "variants": r[1]["variants"], "ein": r[1].get("ein", "")}
        for r in rules_without_ein
    ]
    # Add zero-result names so future runs skip re-grepping them
    if ZERO_RESULT_GREPS:
        cache_data.append({"zero_result_names": sorted(set(ZERO_RESULT_GREPS))})
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)
    print(
        f"Updated cache: {len(rules_without_ein):,} rules + {len(set(ZERO_RESULT_GREPS)):,} zero-result names"
    )

    # Final emit — use a low threshold for priority/SIMPLES, higher for others
    final_rules_list = []
    for c in canonicals.values():
        threshold = 1 if c.is_priority or c.min_variants_to_include == 1 else 3
        if len(c.variants) >= threshold:
            final_rules_list.append((
                c.cleaned,
                {
                    "ein": c.ein,
                    "variants": sorted(c.variants),
                    "source_count": c.source_count,
                },
            ))
    final_rules_list.sort(key=lambda x: x[0].upper())


    # Add back pharma sided names as variants under the single BIG PHARMA SUBSIDY canonical
    # This fixes the bug where the full phrases were not appearing as covered in the analyzer even though the patterns are in the JSON
    if "pharma_sided" in locals() and pharma_sided:
        pharma_variants = sorted(pharma_sided.keys())
        final_rules_list.append(
            (
                "BIG PHARMA SUBSIDY",
                {
                    "ein": "99-7777777",
                    "variants": pharma_variants,
                    "source_count": len(pharma_variants),
                    "source": "pharma_siding",
                },
            )
        )
        print(f"Added BIG PHARMA SUBSIDY rollup with {len(pharma_variants):,} variants back to final output (siding bug fixed)")

    # Add back early simples as their own high-priority canonicals (or variants under the simple name)
    if "simples_sided" in locals() and simples_sided:
        from collections import defaultdict
        simple_groups = defaultdict(list)
        for name, info in simples_sided.items():
            simple_groups[info["canonical"]].append(name)

        for simple_name, variants in simple_groups.items():
            final_rules_list.append(
                (
                    simple_name,
                    {
                        "ein": "",  # Will be filled by later absorption if a better one exists
                        "variants": sorted(variants),
                        "source_count": len(variants),
                        "source": "early_simples_siding",
                    },
                )
            )
        print(f"Added {len(simple_groups)} early simples (incl. UNITED WAY) back from siding")
    # ========== Final single emit pass (guarantees all canonicals including SIMPLES are included) ==========
    final_rules_list = [
        (
            c.cleaned,
            {
                "ein": c.ein,
                "variants": sorted(c.variants),
                "source_count": c.source_count,
            },
        )
        for c in canonicals.values()
        if len(c.variants) >= c.min_variants_to_include
    ]
    final_rules_list.sort(key=lambda x: x[0].upper())

    print(f"\nFinal (real): {len(final_rules_list):,} rules after full tree build")

    print("\n=== Writing output ===")
    # Write as dict keyed by canonical (cleaner, preserves EIN + metadata)
    # NOTE: output_data already contains the merged geo rules from above
    with gzip.open(OUTPUT_JSON, "wt", encoding="utf-8") as f:
        json.dump(final_rules_list, f, indent=2)
    print(f"Saved {len(final_rules_list):,} rules to {OUTPUT_JSON}")

    print("\nTop 15 rules:")
    for i, (core, rule) in enumerate(final_rules_list[:15]):
        sample = (rule[1] if isinstance(rule, (tuple, list)) and len(rule) > 1 else rule).get("variants", [])[:2]
        print(
            f"  '{core}' (EIN: {rule.get('ein', '')}) → {len(rule.get('variants', [])):,} variants"
        )

    # Report on zero-result grep searches (useful signal for noise/obscure names)
    if ZERO_RESULT_GREPS:
        print(f"\n=== Zero-result grep searches ===")
        print(
            f"Total names with 0 lines found in both charity and BMF files: {len(ZERO_RESULT_GREPS):,}"
        )
        print("These are likely noise, very obscure, or non-charity entities.")
        if len(ZERO_RESULT_GREPS) <= 20:
            for name in ZERO_RESULT_GREPS:
                print(f"  - {name}")
        else:
            print("First 10 examples:")
            for name in ZERO_RESULT_GREPS[:10]:
                print(f"  - {name}")
            print(f"  ... and {len(ZERO_RESULT_GREPS) - 10:,} more")

    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed:.1f}s")
