#!/usr/bin/env python3
"""
us_zip_lookup.py — Shared US ZIP → state lookup (from US_zips.txt.gz).

Used by Address.canonicalize (colocator at ingest) and geocode preprocess
(residual Geocoding rows that never re-pass Address).
"""

from __future__ import annotations

import gzip
import os
from typing import Dict, Optional, Tuple

_zip_codes: Optional[frozenset] = None
_zip_states: Optional[Dict[str, str]] = None
_zip_coords: Optional[Dict[str, Tuple[float, float]]] = None

# Military / territory state codes — not used for civilian state↔ZIP mismatch
_SKIP_STATE_MISMATCH = frozenset({
    "AP", "AE", "AA",  # military
    "PR", "VI", "GU", "AS", "MP", "FM", "MH", "PW",
})


def _us_zips_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(os.getcwd(), "US_zips.txt.gz"),
        os.path.join(here, "US_zips.txt.gz"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(here, "US_zips.txt.gz")


def ensure_loaded() -> None:
    """Load US_zips.txt.gz once into process memory."""
    global _zip_codes, _zip_states, _zip_coords
    if _zip_codes is not None:
        return
    path = _us_zips_path()
    codes: set[str] = set()
    states: Dict[str, str] = {}
    coords: Dict[str, Tuple[float, float]] = {}
    if not os.path.isfile(path):
        _zip_codes = frozenset()
        _zip_states = {}
        _zip_coords = {}
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 11:
                continue
            zip_code = parts[1].strip()
            if not zip_code or zip_code in codes:
                continue
            codes.add(zip_code)
            states[zip_code] = parts[4].strip()
            try:
                coords[zip_code] = (float(parts[9]), float(parts[10]))
            except ValueError:
                pass
    _zip_codes = frozenset(codes)
    _zip_states = states
    _zip_coords = coords


def is_valid_us_zip(zip5: str) -> bool:
    ensure_loaded()
    return bool(zip5 and _zip_codes is not None and zip5 in _zip_codes)


def state_for_zip(zip5: str) -> str:
    """Return 2-letter state code for ZIP, or '' if unknown."""
    ensure_loaded()
    z = (zip5 or "")[:5]
    if not z:
        return ""
    return (_zip_states or {}).get(z, "") or ""


def is_state_zip_mismatch(state: str, zip5: str) -> bool:
    """
    True when both a 2-letter US state and a known US ZIP are present and
    the ZIP's primary state disagrees with the declared state.
    """
    state_u = (state or "").strip().upper()
    z = (zip5 or "")[:5]
    if len(state_u) != 2 or not z.isdigit() or len(z) != 5:
        return False
    if state_u in _SKIP_STATE_MISMATCH:
        return False
    if not is_valid_us_zip(z):
        return False
    expected = state_for_zip(z).strip().upper()
    if not expected or len(expected) != 2:
        return False
    if expected in _SKIP_STATE_MISMATCH:
        return False
    return state_u != expected


def ambig_colocator(state: str, zip5: str) -> str:
    """Colocator string for a state/ZIP region conflict."""
    state_u = (state or "").strip().upper()
    z = (zip5 or "")[:5]
    return f"AMBIG:{state_u}:{z}"
