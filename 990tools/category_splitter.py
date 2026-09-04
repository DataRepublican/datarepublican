#!/usr/bin/env python3
"""
category_splitter.py

Repeatable tool to carve the master distinct names list into category-specific
buckets (churches, pharma, etc.) so we can run targeted Splink discovery on
each bucket.

This supports the "hybrid of a hybrid" workflow:
- Master list -> category buckets
- Run splink_pattern_miner.py --use-clean-tsv <bucket>.tsv on each
- Review with review_suggestions_tui.py (with per-category seeds for pre-bless)
- Curated output becomes high-quality seeds for the main pipeline.

Usage examples (dive into Splink mode):
  python category_splitter.py --input distinct_grantee_names_clean.tsv \
      --categories churches,pharma --out-dir category_buckets/

  # Education work in progress (scaffolded May 2026):
  python category_splitter.py --input distinct_grantee_names_clean.tsv \
      --categories education --out-dir category_buckets/
  # Or more granular (once decided):
  # --categories universities_colleges,school_districts,high_schools

  # Then immediately dive into Splink on the pharma no-EIN-ish bucket:
  python splink_pattern_miner.py --use-clean-tsv category_buckets/pharma.tsv \
      --output suggestions_pharma.json --max-suggestions 200

  # Same for churches (leverages simple denomination keywords):
  python splink_pattern_miner.py --use-clean-tsv category_buckets/churches.tsv \
      --output suggestions_churches.json

The script also emits small <category>_seeds.json files that can be fed to the
TUI as --priority-canonicals for aggressive pre-blessing during review of that
bucket's suggestions.
"""
import argparse
import json
import re
import sys
from pathlib import Path
import pandas as pd

# Major simple denomination keywords (user note: CATHOLIC, LUTHERAN, BAPTIST are straightforward)
MAJOR_DENOMINATIONS = [
    "CATHOLIC", "LUTHERAN", "BAPTIST", "METHODIST", "PRESBYTERIAN",
    "EPISCOPAL", "SEVENTH DAY", "SEVENTH-DAY", "ADVENTIST",
    "ASSEMBLY OF GOD", "CHURCH OF CHRIST", "UNITED CHURCH OF CHRIST",
    "DISCIPLES OF CHRIST", "CONGREGATIONAL", "MENNONITE", "QUAKER",
    "MORAVIAN", "PENTECOSTAL", "HOLINESS", "SALVATION ARMY"
]

# Focused religious keywords for the "churches" bucket.
# Goal: Capture the main Christian denominations + core structural terms
# (Church, Temple, Synagogue, Parish, Diocese, etc.) plus a few explicitly
# requested expansions (Jehovah's Witnesses because of user's relatives).
#
# We are deliberately NOT trying to be exhaustive for every world religion
# here, because the broad expansions caused too much non-church noise
# (colleges, sailing clubs, "Charity Water", etc.).
#
# If broader multi-faith coverage is needed later, we can create a separate
# "religious_institutions" category.
ADDITIONAL_RELIGIOUS_KEYWORDS = [
    # Jehovah's Witnesses (explicitly requested)
    "WATCHTOWER", "WATCH TOWER", "KINGDOM HALL", "JEHOVAH",

    # Core Christian structural / hierarchy terms (very reliable signals)
    "PARISH", "DIOCESE", "ARCHDIOCESE", "CATHEDRAL", "BASILICA",
    "ABBEY", "MONASTERY", "CONVENT",

    # A small number of other major traditions that are relatively clean
    # and were specifically discussed. Kept minimal to control noise.
    "MOSQUE", "MASJID",
    "YESHIVA", "SHUL", "CHABAD", "LUBAVITCH",
]

CHURCH_KEYWORDS = ["CHURCH", "TEMPLE", "SYNAGOGUE"] + MAJOR_DENOMINATIONS + ADDITIONAL_RELIGIOUS_KEYWORDS

# Education-related keywords (scaffolded for upcoming university/college/high school/school district work)
# These are intentionally broad; granularity decisions (higher_ed vs K-12 vs districts) still being finalized.
UNIVERSITY_COLLEGE_KEYWORDS = [
    "UNIVERSITY", "UNIVERSITIES", "COLLEGE", "COLLEGES",
    "UNIVERSITY OF", "STATE UNIVERSITY", "COMMUNITY COLLEGE"
]
HIGH_SCHOOL_KEYWORDS = [
    "HIGH SCHOOL", "HIGH SCHOOLS", "SECONDARY SCHOOL"
]
SCHOOL_DISTRICT_KEYWORDS = [
    "SCHOOL DISTRICT", "SCHOOL DISTRICTS", "UNIFIED SCHOOL DISTRICT",
    "INDEPENDENT SCHOOL DISTRICT", "ISD", "USD", "SCHOOL DIST"
]
EDUCATION_KEYWORDS = (
    UNIVERSITY_COLLEGE_KEYWORDS + HIGH_SCHOOL_KEYWORDS + SCHOOL_DISTRICT_KEYWORDS + ["SCHOOL"]
)

# === Hospitals / Clinics bucket (protective layer before churches) ===
# Large category (~26k hospitals + ~11k clinics from greps).
# Purpose: Catch religious-named and other hospitals/clinics (e.g. "ST. JUDE HOSPITAL",
# "MERCY MEDICAL CENTER", "SACRED HEART CLINIC") so they don't pollute church patterns.
# Also catches many "XXX HOSPITAL FOUNDATION" riders that would otherwise be noisy.
HOSPITAL_CLINIC_KEYWORDS = [
    "HOSPITAL", "HOSPITALS",
    "MEDICAL CENTER", "MEDICAL CENTRE",
    "HEALTH SYSTEM", "HEALTH SYSTEMS",
    "CLINIC", "CLINICS",
    "MEDICAL CLINIC", "HEALTH CLINIC",
    "URGENT CARE CENTER", "URGENT CARE CLINIC",
]

# === Municipality bucket ===
# Civil government entities: cities, towns, townships, counties, boroughs, etc.
# High volume from greps (county alone >100k). These are often low-EIN or special
# handling cases in the phased siding stack (after hospitals, before or alongside schools).
# Goal: Cleanly separate "XXX COUNTY", "CITY OF YYY", "TOWN OF ZZZ" style names.
MUNICIPALITY_KEYWORDS = [
    "CITY OF",
    "TOWN OF",
    "TOWNSHIP OF",
    "COUNTY OF",
    "BOROUGH OF",
    "VILLAGE OF",
    "MUNICIPALITY OF",
    "MUNICIPAL",
]

# === Muniservices bucket (protective layer before churches) ===
# Covers sheriff, police, fire, transit and related municipal services.
# Goal: Strip things like "ST JUDE PARISH SHERIFF'S OFFICE", "XXX FIRE DEPT",
# "CITY POLICE DEPARTMENT", etc. so they don't pollute church/school patterns.
#
# This is the next major siding after pharma (per phased stack discussion).
MUNISERVICE_KEYWORDS = [
    # Sheriff variants
    "SHERIFF", "SHERIFF'S", "SHERIFFS", "SHERIFF DEPARTMENT", "SHERIFF DEPT",
    # Police
    "POLICE DEPARTMENT", "POLICE DEPT", "POLICE DEPARTMENT", "CITY POLICE",
    # Fire
    "FIRE DEPARTMENT", "FIRE DEPT", "FIRE DISTRICT", "FIRE PROTECTION DISTRICT",
    "FIRE AND RESCUE", "FIRE RESCUE",
    # Transit / public transport
    "TRANSIT AUTHORITY", "PUBLIC TRANSIT", "TRANSIT DISTRICT", "METROPOLITAN TRANSIT",
    "MTA", "RTA", "TRANSPORTATION AUTHORITY",
]

# Note: The simple keyword list above is still used for the broad "education" bucket.
# For the dedicated "school_districts" category we now use a smarter detector
# (see is_school_district_name) based on analysis of real patterns.

def load_pharma_patterns(pharma_json: str = "big_pharma_subsidy.json"):
    """Load the patterns used for pharma inference (including no-EIN subsidy rows)."""
    p = Path(pharma_json)
    if not p.exists():
        print(f"Warning: {pharma_json} not found. Pharma bucket will be empty.")
        return []
    with open(p) as f:
        data = json.load(f)
    patterns = []
    # The structure is {"BIG PHARMA SUBSIDY": {"patterns": [...]}, ...} or list of dicts
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and "patterns" in v:
                patterns.extend(v["patterns"])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "patterns" in item:
                patterns.extend(item["patterns"])
            elif isinstance(item, str):
                patterns.append(item)
    # Compile as regex for consistency with the generator
    compiled = []
    for pat in patterns:
        if pat:
            try:
                compiled.append(re.compile(pat, re.IGNORECASE))
            except re.error:
                compiled.append(pat)
    print(f"Loaded {len(compiled)} pharma patterns from {pharma_json} (as regex)")
    return compiled

def _contains_word(name_upper: str, keyword: str) -> bool:
    """True if keyword appears as a whole word (bounded by non-letters or string edges)."""
    # Use word boundaries so "WAT" doesn't match inside "CLEARWATER" or "WATER"
    pattern = rf'(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])'
    return bool(re.search(pattern, name_upper))

def is_church_name(name: str) -> bool:
    if not isinstance(name, str):
        return False
    n = name.upper()

    # Must contain at least one religious keyword as a whole word
    if not any(_contains_word(n, kw) for kw in CHURCH_KEYWORDS):
        return False

    # Hard exclusions for common non-church noise
    hard_excludes = [
        "CHARITY WATER",           # Famous water charity
    ]
    if any(ex in n for ex in hard_excludes):
        return False

    # Hard exclusion for clear education institutions
    education_noise = ("COLLEGE", "UNIVERSITY", "UNIVERSITIES", "COMMUNITY COLLEGE")
    if any(_contains_word(n, edu) for edu in education_noise):
        strong_church_signals = ("CHURCH", "TEMPLE", "SYNAGOGUE", "MOSQUE", "PARISH", "DIOCESE")
        if not any(_contains_word(n, sig) for sig in strong_church_signals):
            return False

    return True

def is_pharma_name(name: str, patterns: list) -> bool:
    if not isinstance(name, str) or not patterns:
        return False
    for p in patterns:
        if isinstance(p, re.Pattern):
            if p.search(name):
                return True
        else:
            if p in name.upper():
                return True
    return False


def is_university_name(name: str) -> bool:
    """
    Detects university names.
    Requires "UNIVERSITY" (or plural) signal.
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    if "UNIVERSITY" not in n and "UNIVERSITIES" not in n:
        return False

    # Drop foundation noise
    noise_tokens = ["FOUNDATION", "EDUCATION FOUNDATION", "PARENT TEACHER"]
    if any(token in n for token in noise_tokens):
        return False

    return True


def is_college_name(name: str) -> bool:
    """
    Detects college names, but not universities.
    Requires "COLLEGE" (or plural) but excludes things that are clearly universities.
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    if "COLLEGE" not in n and "COLLEGES" not in n:
        return False

    # Explicitly exclude universities (some places are called "University College")
    if "UNIVERSITY" in n:
        return False

    # Drop foundation noise
    noise_tokens = ["FOUNDATION", "EDUCATION FOUNDATION", "PARENT TEACHER"]
    if any(token in n for token in noise_tokens):
        return False

    return True


def is_high_school_name(name: str) -> bool:
    """
    Tightened high school detector.

    Requires a strong "HIGH SCHOOL" phrase.
    Filters common foundation noise (consistent with school district approach).
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    if "HIGH SCHOOL" not in n and "HIGH SCHOOLS" not in n:
        return False

    # Drop foundation-style noise
    noise_tokens = ["FOUNDATION", "PARENT TEACHER", "EDUCATION FOUNDATION", "PTA", "PTO"]
    if any(token in n for token in noise_tokens):
        return False

    return True


def is_school_district_name(name: str) -> bool:
    """
    Improved school district detector (data-driven, May 2026).

    Analysis of the clean TSV showed:
    - High-volume real districts are almost always "GEO + [UNIFIED|INDEPENDENT|COUNTY] SCHOOL DISTRICT"
      or short forms like "GEO ISD" / "GEO USD".
    - Major noise sources: "XXX SCHOOL DISTRICT [PARENT TEACHER|EDUCATION] FOUNDATION",
      "XXX USD MEDICAL CENTER", etc.
    - "SCHOOL DISTRICT OF XXX" is a real and common form (Philadelphia etc.).

    This function tries to keep the geo identity while filtering obvious foundation noise.
    """
    if not isinstance(name, str):
        return False

    n = name.upper().strip()

    # Strong, specific district suffixes (must appear as meaningful phrases)
    strong_patterns = [
        " UNIFIED SCHOOL DISTRICT",
        " INDEPENDENT SCHOOL DISTRICT",
        "SCHOOL DISTRICT OF ",           # "SCHOOL DISTRICT OF PHILADELPHIA" (can start the string)
        " COUNTY SCHOOL DISTRICT",
        " UNION HIGH SCHOOL DISTRICT",
    ]

    has_strong = any(pat in n for pat in strong_patterns)

    # Short/abbreviated forms that are very common in real data
    # (e.g. "TERRELL ISD", "HOUSTON ISD", "CLARK COUNTY USD")
    has_short = bool(re.search(r'\b(USD|ISD)\b', n))

    # Plain " SCHOOL DISTRICT" at the end (catches many "XXX SCHOOL DISTRICT")
    # but we are more permissive here because the analysis showed this is the dominant form.
    has_plain = n.endswith(" SCHOOL DISTRICT") or " SCHOOL DISTRICT " in n

    if not (has_strong or has_short or has_plain):
        return False

    # Filter common foundation / parent-teacher noise that rides along with district names
    noise_tokens = [
        "FOUNDATION",
        "PARENT TEACHER",
        "EDUCATION FOUNDATION",
        "PTA",
        "PTO",
        "COMMUNITY COUNCIL",
        " MEDICAL CENTER",   # catches "SANFORD USD MEDICAL CENTER" etc.
    ]
    if any(token in n for token in noise_tokens):
        return False

    return True


def is_muniservice_name(name: str) -> bool:
    """
    Detector for municipal services (sheriff, police, fire, transit, etc.).

    Uses whole-word matching to avoid substring disasters (e.g. "TRANSIT" inside
    unrelated words).

    This is intended as an early siding layer to protect later church/school
    patterns from things like "ST. JUDE PARISH SHERIFF'S OFFICE" or
    "HOLY CROSS FIRE DEPARTMENT".
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    # Must contain at least one muniservice keyword as a whole word/phrase
    if not any(_contains_word(n, kw) for kw in MUNISERVICE_KEYWORDS):
        return False

    # Light noise filter: drop obvious foundation/PTA riders that sometimes
    # attach to these names.
    noise_tokens = ["FOUNDATION", "EDUCATION FOUNDATION", "PARENT TEACHER", "PTA", "PTO", "BENEVOLENT FUND"]
    if any(token in n for token in noise_tokens):
        # Only drop if it's clearly riding along (not the core name)
        if not any(kw in n for kw in ("SHERIFF", "POLICE", "FIRE DEPARTMENT")):
            return False

    # Hard exclusions for very generic or low-signal patterns that shouldn't
    # become their own muniservice canonicals (e.g. "CITY", "HEROES", standalone "FUND").
    hard_generic = ["^CITY$", "^HEROES$", "^FUND$", "MEADOW FOUNDATION", "YOUTH RANCH"]
    if any(re.search(pat, n) for pat in hard_generic):
        return False

    return True


def is_hospital_or_clinic_name(name: str) -> bool:
    """
    Detector for hospitals, medical centers, health systems, and clinics.

    This is the next major protective siding layer after muniservices.
    Goal: Remove religious and other named hospitals/clinics before the
    churches bucket runs, avoiding the classic "ST. JUDE HOSPITAL" vs
    "ST. JUDE PARISH" collision problem.
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    if not any(_contains_word(n, kw) for kw in HOSPITAL_CLINIC_KEYWORDS):
        return False

    # Drop obvious foundation / auxiliary / volunteer riders that ride along
    # with real hospitals (these are common and noisy).
    foundation_riders = [
        "FOUNDATION", "AUXILIARY", "VOLUNTEER", "GUILD", "BENEVOLENT",
        "FRIENDS OF", "SUPPORT GROUP",
    ]
    if any(rider in n for rider in foundation_riders):
        # Only keep if the core hospital signal is extremely strong
        strong_core = any(kw in n for kw in ("HOSPITAL", "MEDICAL CENTER", "HEALTH SYSTEM"))
        if not strong_core:
            return False

    # Avoid veterinary / animal hospitals polluting the human health category
    # (optional but usually desired for this protective use case).
    if any(x in n for x in ["VETERINARY", "VET ", "ANIMAL HOSPITAL", "PET HOSPITAL"]):
        return False

    return True


def is_municipality_name(name: str) -> bool:
    """
    Detector for civil/municipal government entities.

    Focuses on strong geo-civil patterns like "CITY OF", "COUNTY OF", "TOWN OF",
    and common standalone forms ("XXX COUNTY", "XXX TOWNSHIP") while trying
    to avoid obvious non-civil noise (hospitals, schools, churches, etc.).
    """
    if not isinstance(name, str):
        return False
    n = name.upper().strip()

    # Strong phrase matches first (highest signal)
    if any(phrase in n for phrase in ("CITY OF ", "TOWN OF ", "TOWNSHIP OF ",
                                       "COUNTY OF ", "BOROUGH OF ", "VILLAGE OF ",
                                       "MUNICIPALITY OF ")):
        return True

    # Common standalone civil suffixes (very high volume per user's greps)
    civil_suffixes = [" COUNTY", " TOWNSHIP", " CITY", " TOWN"]
    has_civil_suffix = any(n.endswith(suf) or f"{suf} " in n for suf in civil_suffixes)

    if not has_civil_suffix:
        # Also catch "MUNICIPAL" standalone as a weaker signal
        if "MUNICIPAL" not in n:
            return False

    # Exclude strong non-civil signals that often collide
    # (e.g. "ST. JUDE COUNTY HOSPITAL" should go to hospitals first)
    exclude_signals = [
        "HOSPITAL", "CLINIC", "MEDICAL CENTER",
        "SCHOOL", "HIGH SCHOOL", "ELEMENTARY",
        "CHURCH", "PARISH", "TEMPLE", "SYNAGOGUE",
        "FIRE DEPARTMENT", "POLICE DEPARTMENT", "SHERIFF",
    ]
    if any(sig in n for sig in exclude_signals):
        return False

    return True


def is_education_name(name: str) -> bool:
    """Broad education catch-all (for when granularity is still being decided)."""
    if not isinstance(name, str):
        return False
    n = name.upper()
    return any(kw in n for kw in EDUCATION_KEYWORDS)

def make_seeds_for_category(category: str) -> list:
    """Small curated seeds for TUI pre-blessing when reviewing this bucket's Splink output."""
    if category == "churches":
        # Focused seeds matching what the user actually wants for the churches grind:
        # the major denominations + a few explicitly requested expansions (JWs).
        # Broad matches on these are acceptable; fine distinctions inside them
        # (e.g. "Catholic Services" vs "Catholic Charities") are not important.
        return [
            "CATHOLIC CHARITIES",
            "LUTHERAN SERVICES",
            "BAPTIST HEALTH",
            "METHODIST HOSPITAL",
            "PRESBYTERIAN CHURCH",
            "EPISCOPAL CHURCH",
            "GREEK ORTHODOX",
            "SALVATION ARMY",
            "SEVENTH DAY ADVENTIST",
            "CHURCH OF JESUS CHRIST OF LATTER-DAY SAINTS",

            # Explicitly requested
            "WATCHTOWER BIBLE AND TRACT SOCIETY",
            "KINGDOM HALL",
            "JEHOVAH'S WITNESSES",

            # Useful structural terms
            "PARISH OF",
            "DIOCESE OF",
        ]
    if category == "pharma":
        return [
            "PFIZER", "MODERNA", "JOHNSON & JOHNSON", "MERCK", "NOVARTIS",
            "BRISTOL MYERS", "ABBOTT", "ELI LILLY", "GILEAD", "AMGEN",
        ]
    if category in ("universities", "higher_ed"):
        return [
            "UNIVERSITY OF CALIFORNIA",
            "HARVARD UNIVERSITY",
            "STANFORD UNIVERSITY",
            "UNIVERSITY OF MICHIGAN",
            "DUKE UNIVERSITY",
            "UNIVERSITY OF FLORIDA",
            "JOHNS HOPKINS UNIVERSITY",
        ]
    if category in ("colleges",):
        return [
            "HILLSDALE COLLEGE",
            "DARTMOUTH COLLEGE",
            "BOSTON COLLEGE",
            "WELLESLEY COLLEGE",
            "BOWDOIN COLLEGE",
            "WILLIAMS COLLEGE",
            "AMHERST COLLEGE",
        ]
    if category in ("high_schools", "high school"):
        return [
            "CENTRAL CATHOLIC HIGH SCHOOL", "NOTRE DAME HIGH SCHOOL",
            "EPISCOPAL HIGH SCHOOL", "JESUIT HIGH SCHOOL",
        ]
    if category in ("school_districts", "school district", "k12"):
        # Data-driven seeds from analysis of real high-volume districts (May 2026)
        return [
            "LOS ANGELES UNIFIED SCHOOL DISTRICT",
            "OAKLAND UNIFIED SCHOOL DISTRICT",
            "SCHOOL DISTRICT OF PHILADELPHIA",
            "SAN FRANCISCO UNIFIED SCHOOL DISTRICT",
            "SAN DIEGO UNIFIED SCHOOL DISTRICT",
            "HOUSTON INDEPENDENT SCHOOL DISTRICT",
            "DALLAS INDEPENDENT SCHOOL DISTRICT",
            "CLARK COUNTY SCHOOL DISTRICT",
            "WASHOE COUNTY SCHOOL DISTRICT",
            "TERRELL ISD",
        ]
    if category == "muniservices":
        # Starter seeds for the protective municipal services layer.
        # These help with pre-blessing in the TUI. Expanded based on first grind pass.
        return [
            "SHERIFF'S OFFICE",
            "SHERIFF DEPARTMENT",
            "POLICE DEPARTMENT",
            "POLICE DEPT",
            "CITY POLICE",
            "FIRE DEPARTMENT",
            "FIRE DEPT",
            "FIRE PROTECTION DISTRICT",
            "FIRE DISTRICT",
            "FIRE RESCUE",
            "FIRE AND RESCUE",
            "TRANSIT AUTHORITY",
            "TRANSPORTATION AUTHORITY",
            "MTA",
            "RTA",
            "PUBLIC TRANSIT",
        ]
    if category == "hospitals":
        # Initial high-signal seeds for hospitals + clinics protective layer.
        # Focused on common real patterns to bootstrap pre-blessing.
        return [
            "GENERAL HOSPITAL",
            "MEMORIAL HOSPITAL",
            "REGIONAL MEDICAL CENTER",
            "COMMUNITY HOSPITAL",
            "HEALTH SYSTEM",
            "MEDICAL CENTER",
            "CHILDREN'S HOSPITAL",
            "UNIVERSITY HOSPITAL",
            "SACRED HEART HOSPITAL",
            "MERCY HOSPITAL",
            "ST. FRANCIS HOSPITAL",
            "ST. JOSEPH HOSPITAL",
            "CLINIC",
            "MEDICAL CLINIC",
            "HEALTH CLINIC",
        ]
    if category == "municipality":
        # Starter seeds for the civil/municipality layer.
        # High-volume real patterns from common government entities.
        return [
            "LOS ANGELES COUNTY",
            "COOK COUNTY",
            "MARICOPA COUNTY",
            "CITY OF LOS ANGELES",
            "CITY OF CHICAGO",
            "CITY OF NEW YORK",
            "TOWN OF",
            "TOWNSHIP",
            "BOROUGH OF",
        ]
    return []

def main():
    parser = argparse.ArgumentParser(
        description="Split master distinct names into category buckets for targeted Splink runs."
    )
    parser.add_argument("--input", default="distinct_grantee_names_clean.tsv",
                        help="Path to the clean distinct names TSV (or fuller version)")
    parser.add_argument("--categories", default="churches,pharma",
                        help="Comma-separated categories. Supported: churches, pharma, "
                             "muniservices, hospitals, municipality, school_districts, high_schools, "
                             "universities, colleges, higher_ed, education (broad catch-all).")
    parser.add_argument("--out-dir", default="category_buckets",
                        help="Directory for output bucket TSVs and seeds files")
    parser.add_argument("--pharma-json", default="big_pharma_subsidy.json",
                        help="Source of pharma patterns (for no-EIN inference style)")
    parser.add_argument("--min-grants", type=int, default=1,
                        help="Minimum grant_count to include in a bucket (for noise reduction)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading master list: {args.input}")
    df = pd.read_csv(args.input, sep="\t")
    print(f"Loaded {len(df):,} rows")

    # Normalize name column (consistent with miner + TUI)
    if "grantee_name" in df.columns:
        name_col = "grantee_name"
    else:
        name_col = df.columns[0]
    df["_norm_name"] = df[name_col].astype(str).str.upper()

    # Optional light filter
    if "grant_count" in df.columns:
        before = len(df)
        df = df[df["grant_count"] >= args.min_grants]
        print(f"After min-grants filter: {len(df):,} (dropped {before - len(df)})")

    pharma_patterns = []
    cats = [c.strip().lower() for c in args.categories.split(",") if c.strip()]

    for cat in cats:
        if cat == "churches":
            mask = df["_norm_name"].apply(is_church_name)
            bucket = df[mask].copy()
            print(f"Churches bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "churches.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("churches")
            seeds_file = out_dir / "churches_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file} ({len(seeds)} entries)")

        elif cat == "pharma":
            pharma_patterns = load_pharma_patterns(args.pharma_json)
            mask = df["_norm_name"].apply(lambda n: is_pharma_name(n, pharma_patterns))
            bucket = df[mask].copy()
            print(f"Pharma bucket (matching big_pharma patterns, suitable for no-EIN Splink exploration): {len(bucket):,} rows")
            bucket_file = out_dir / "pharma.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("pharma")
            seeds_file = out_dir / "pharma_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        elif cat == "muniservices":
            # Protective municipal services layer (sheriff/police/fire/transit).
            # Runs early in the future phased siding stack to prevent pollution
            # of church and school patterns (e.g. "ST JUDE PARISH SHERIFF").
            mask = df["_norm_name"].apply(is_muniservice_name)
            bucket = df[mask].copy()
            print(f"Muniservices bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "muniservices.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("muniservices")
            seeds_file = out_dir / "muniservices_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file} ({len(seeds)} entries)")

        elif cat in ("hospitals", "hospital", "clinics", "clinic"):
            # Hospitals + clinics as the next protective layer in the phased siding stack.
            # This is deliberately broad to catch the ~38k hospital/clinic names
            # before churches run.
            mask = df["_norm_name"].apply(is_hospital_or_clinic_name)
            bucket = df[mask].copy()
            print(f"Hospitals + clinics bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "hospitals.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("hospitals")
            seeds_file = out_dir / "hospitals_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file} ({len(seeds)} entries)")

        elif cat == "municipality":
            # Civil government / municipality layer (cities, towns, counties, townships, etc.)
            # Large and important for the phased siding stack.
            mask = df["_norm_name"].apply(is_municipality_name)
            bucket = df[mask].copy()
            print(f"Municipality bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "municipality.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("municipality")
            seeds_file = out_dir / "municipality_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file} ({len(seeds)} entries)")

        # === Education scaffolding (2026-05) ===
        elif cat in ("universities", "higher_ed"):
            mask = df["_norm_name"].apply(is_university_name)
            bucket = df[mask].copy()
            print(f"{cat} bucket: {len(bucket):,} rows")
            bucket_file = out_dir / f"{cat}.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category(cat)
            seeds_file = out_dir / f"{cat}_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        elif cat in ("colleges",):
            mask = df["_norm_name"].apply(is_college_name)
            bucket = df[mask].copy()
            print(f"{cat} bucket: {len(bucket):,} rows")
            bucket_file = out_dir / f"{cat}.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category(cat)
            seeds_file = out_dir / f"{cat}_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        elif cat in ("high_schools", "high school"):
            mask = df["_norm_name"].apply(is_high_school_name)
            bucket = df[mask].copy()
            print(f"High schools bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "high_schools.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("high_schools")
            seeds_file = out_dir / "high_schools_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        elif cat in ("school_districts", "school district", "k12"):
            mask = df["_norm_name"].apply(is_school_district_name)
            bucket = df[mask].copy()

            # Explicitly drop foundation / parent-teacher / education foundation rows.
            # Data analysis showed these are a major source of noise riding along
            # with real district names (e.g. "XXX SCHOOL DISTRICT EDUCATION FOUNDATION").
            before_len = len(bucket)
            noise_mask = ~bucket["_norm_name"].str.contains(
                r"FOUNDATION|PARENT TEACHER|EDUCATION FOUNDATION|PTA|PTO|COMMUNITY COUNCIL",
                case=False, na=False, regex=True
            )
            bucket = bucket[noise_mask].copy()
            dropped = before_len - len(bucket)
            if dropped > 0:
                print(f"  Dropped {dropped:,} foundation/PTA-style noise rows")

            print(f"School districts bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "school_districts.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("school_districts")
            seeds_file = out_dir / "school_districts_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        elif cat == "education":
            # Broad catch-all while granularity is being decided
            mask = df["_norm_name"].apply(is_education_name)
            bucket = df[mask].copy()
            print(f"Broad education bucket: {len(bucket):,} rows")
            bucket_file = out_dir / "education.tsv"
            bucket.drop(columns=["_norm_name"], errors="ignore").to_csv(
                bucket_file, sep="\t", index=False
            )
            print(f"  Wrote {bucket_file}")

            seeds = make_seeds_for_category("education")
            seeds_file = out_dir / "education_seeds.json"
            with open(seeds_file, "w") as f:
                json.dump({"canonicals": seeds}, f, indent=2)
            print(f"  Wrote seeds for TUI pre-bless: {seeds_file}")

        else:
            print(f"Unknown category: {cat}")

    print("\n=== Ready to dive into Splink (as requested) ===")
    print("Example commands:")
    for cat in cats:
        tsv = out_dir / f"{cat}.tsv"
        if tsv.exists():
            print(f"  python splink_pattern_miner.py --use-clean-tsv {tsv} \\")
            print(f"      --output suggestions_{cat}.json --max-suggestions 200")
            print(f"  # Then review:")
            print(f"  python review_suggestions_tui.py --suggestions suggestions_{cat}.json \\")
            print(f"      --priority-canonicals {out_dir / f'{cat}_seeds.json'} \\")
            print(f"      --clean-names-tsv {args.input}")

    print("\nTip for pharma no-EIN focus: The pharma bucket above contains names matching the")
    print("subsidy/privacy patterns. Run Splink on it to discover what common structures it finds")
    print("(exactly as you described). If you have a grants-level file with EIN flags, you can")
    print("further pre-filter the input TSV before running this splitter.")

if __name__ == "__main__":
    main()
