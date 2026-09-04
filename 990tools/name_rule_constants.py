#!/usr/bin/env python3
"""
name_rule_constants.py

Shared constants for the 990 name rules system.
This is the SINGLE SOURCE OF TRUTH for:
- GENERIC_SINGLE_WORDS (blacklist for single-word canonicals)
- GOOD_SINGLE_WORD_PRIORITIES (exceptions that should NEVER appear in BAD SHORT CANONICALS)

Both generate_name_rules_v19.1.py and the analyze_*.py scripts import from here.
This guarantees that adding a new priority or expanding the generic blacklist
automatically updates every diagnostic report.

Edit this file when you want to:
- Add/remove generic single words (e.g. new noise patterns)
- Add new high-value single-word priorities (UNICEF, JOBSOHIO, KIPP, etc.)
"""

# =============================================================================
# GENERIC_SINGLE_WORDS
# Single words that should NEVER become standalone canonicals (unless is_priority=True)
# These are either too generic, too common as noise, or have better multi-word forms.
# =============================================================================
GENERIC_SINGLE_WORDS = {
    'SCHOOL', 'WAY', 'E', 'RED', 'ORDER', 'CLINIC', 'POLICY', 'POP', 
    'CHAPEL', 'AREA', 'ON', 'OF', 'THE', 'AND', 'FOR', 'INC', 'LLC',
    'BROAD', 'ROBIN', 'UC', 'MUSEUM', 'ISRAEL', 'TECH',
    'COMMUNITY', 'UNIVERSITY', 'NATIONAL', 'CHAMBER', "CHILDREN'S", 'PARTNERS',
    'HOSPITAL', 'CENTER', 'INSTITUTE', 'FOUNDATION', 'ASSOCIATION', 'SOCIETY',
    'INTERNATIONAL', 'IMPACT', 'DONORS', 'GAVE', 'GIVE', 'SEE', 'VARIOUS'
    # Note: ROTARY and SIERRA intentionally removed (useful single-word patterns:
    # ROTARY clubs, SIERRA CLUB / Sierra <geo> orgs). KIPP and AHAVAS also removed
    # (KIPP <geo> pattern is useful; AHAVAS is a legitimate Jewish org pattern).
}

# =============================================================================
# GOOD_SINGLE_WORD_PRIORITIES
# Single-word canonicals that are KNOWN to be high-value and should NEVER
# appear in the "BAD SHORT CANONICALS" diagnostic list, even if they have
# thousands of variants.
# =============================================================================
GOOD_SINGLE_WORD_PRIORITIES = {
    # Core high-value single words
    "UNICEF", "UCLA", "UCSF", "TIDES", "PATH", "BIOHUB",
    "BROAD", "ROBIN", "SIERRA", "UC", "POP",
    
    # High-dollar single-word priorities added in v19.1+
    "JOBSOHIO", "BCFS", "USOPC", "EARTHJUSTICE", "GIVEWELL",
    "POLICYLINK", "MULTIPLIER", "WNET", "GIVE2ASIA", "IMPACTASSETS",
    
    # Legitimate single-word patterns (per user feedback)
    "KIPP", "DONORS", "AHAVAS",
    
    # Multi-word but treated as priority (for completeness in diagnostics)
    "GIVEDIRECTLY", "MILKEN", "50CAN", "SMP",
    "INTERNATIONAL JUSTICE MISSION", "ALLIANCE DEFENDING FREEDOM",
    "MILKEN INSTITUTE", "BADER PHILANTHROPIES",
    "CHARTER FUND", "BIG WIN PHILANTHROPY", "IMPACT FOUNDATION",
    "THE VALLEY HOSPITAL", "JHPIEGO", "SPAULDING REHABILITATION",
    "CENTRAL TEXAS COUNCIL OF GOVERNMENTS", "THE MCLEAN HOSPITAL",
    "BRAZOS ELECTRIC", "STATEMENT D", "CIRCUIT OF THE AMERICAS",
    "VCU HEALTH", "NSMC HEALTHCARE", "UNIVERSITY OF FLORIDA JACKSONVILLE PHYSICIANS",
    "KIPP FOUNDATION", "DONORS TRUST", "ROTARY FOUNDATION",
    "COMMUNITY FOUNDATION", "ROTARY",

    # New single-word priorities (fullproof distinctive cores)
    "BRIGHAM", "MAYO"
}

# Convenience: set of single-word good priorities (for fast lookup in analyze scripts)
GOOD_SINGLE_WORD_PRIORITIES_SINGLE = {
    w for w in GOOD_SINGLE_WORD_PRIORITIES if ' ' not in w
}

# =============================================================================
# SIMPLES
# Simple canonicals that get explicit priority treatment (aggressive variant
# collection + dedicated EIN lookup). These bypass many guards and rise to
# the top of the final rules list.
# =============================================================================
SIMPLES = [
    "MAKE A WISH",
    "FIDELITY CHARITABLE",
    "ATTACHED",
    "BIOHUB",
    "UNICEF",
    "UCLA",
    "UCSF",
    "TIDES",
    "PATH",
    "JOBSOHIO",
    "BCFS",
    "USOPC",
    "EARTHJUSTICE",
    "GIVEWELL",
    "POLICYLINK",
    "MULTIPLIER",
    "WNET",
    "GIVE2ASIA",
    "GIVEDIRECTLY",
    "MILKEN INSTITUTE",
    "50CAN",
    "BADER PHILANTHROPIES",
    "CHARTER FUND",
    "BIG WIN PHILANTHROPY",
    "IMPACT FOUNDATION",
    "THE VALLEY HOSPITAL",
    "JHPIEGO",
    "SPAULDING REHABILITATION",
    "CENTRAL TEXAS COUNCIL OF GOVERNMENTS",
    "THE MCLEAN HOSPITAL",
    "BRAZOS ELECTRIC",
    "STATEMENT D",
    "CIRCUIT OF THE AMERICAS",
    "VCU HEALTH",
    "NSMC HEALTHCARE",
    "UNIVERSITY OF FLORIDA JACKSONVILLE PHYSICIANS",
    "KIPP FOUNDATION",
    "DONORS TRUST",
    "ROTARY FOUNDATION",
    "COMMUNITY FOUNDATION",
    "ROTARY",
    "SIERRA CLUB",
    "WK KELLOGG FOUNDATION",
    "BLUE MERIDIAN PARTNERS",
    "NATIONAL PHILANTHROPIC",
    "NATIONAL PHILANTHROPIC TRUST",
    "DECHOMAI FOUNDATION",
    "GAVI ALLIANCE",
    "THE NEMOURS FOUNDATION",
    "85 FUND",
    "VAN ANDEL INSTITUTE",
    "SEATTLE ART MUSEUM",
    "THE BROAD INSTITUTE",
    "ROBIN HOOD FOUNDATION",
    "SOUTHEASTERN CONFERENCE",
    "CHOP FOUNDATION",
    "AMERICANS FOR PROSPERITY",
    "VIRGINIA TECH",
    "FOUNDATION FOR THE CAROLINAS",
    "KIPP",
    "ALLIANCE DEFENDING FREEDOM",
    "INTERNATIONAL JUSTICE MISSION",
    "BRIGHAM",
    "MAYO",
    "FIRST BAPTIST",
    "HABITAT HUMANITY",
    "SALVATION ARMY",
    "AMERICAN LEGION",
    "UNITED WAY",
    "KNIGHTS OF COLUMBUS",
    "VETERANS OF FOREIGN WARS",
    "PLANNED PARENTHOOD",
    "WOUNDED WARRIOR",
    "ALZHEIMER",
    "ST JUDE",
    "FOOD BANK",
    "OUR LADY",
    "VFW",
    "BOYS AND GIRLS CLUB",
    "COMMUNITY FOUNDATION",
    "PUBLIC LIBRARY",
    "FOOD BANK",
    "ALZHEIMER"
]
# =============================================================================
# PROBLEM_SUFFIXES
# Growing list of common suffixes and noise words that should be stripped
# aggressively for most names but protected for priority cores (universities,
# ROTARY, BRIGHAM, MAYO, etc.). This is the "growing list" for dynamic noise
# word collection you requested.
# =============================================================================
PROBLEM_SUFFIXES = {
    'INC', 'LLC', 'FDN', 'TR', 'TRUST', 'TRUSTEE', 'TRUSTEES', 'CORP',
    'CORPORATION', 'NFP', 'FOUNDATION', 'ASSOCIATION', 'SOCIETY', 'GROUP',
    'SERVICES', 'HEALTH', 'OF', 'THE', 'AND', 'FOR', 'INCORPORATED',
    'LIMITED', 'CO', 'COMPANY', 'PARTNERS', 'CLUB', 'FUND', 'CHARITABLE'
}

# Update the docstring mention

# Update the docstring at the top to mention PROBLEM_SUFFIXES
# (manual edit recommended after this append)

# Additional high-value cores from latest v2 analyzer + greps
# (SCHWAB CHARITABLE, GATES FOUNDATION, NATIONAL CHRISTIAN, RENAISSANCE CHARITABLE, 
# WORLD HEALTH, DIGNITY HEALTH, LUCAS MUSEUM, ECMC GROUP)
SIMPLES.extend([
    "SCHWAB CHARITABLE",
    "GATES FOUNDATION",
    "NATIONAL CHRISTIAN",
    "RENAISSANCE CHARITABLE",
    "WORLD HEALTH",
    "DIGNITY HEALTH",
    "LUCAS MUSEUM",
    "ECMC GROUP", "PATIENT", "HIPPA", "PATIENTS", "ELIGIBLE PATIENTS", "NEW VENTURE FUND",
])
