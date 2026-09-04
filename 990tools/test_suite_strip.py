#!/usr/bin/env python3
"""Tests for census_strip suite/unit removal."""

import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import geocoding_api_processor


def test_suite_strip():
    importlib.reload(geocoding_api_processor)
    processor = geocoding_api_processor.GeocodingAPIProcessor(None)

    cases = [
        (
            "100 N Pacific Coast Hwy Ste 1400, El Segundo, Ca, 90245",
            "100 N Pacific Coast Hwy, El Segundo, Ca, 90245",
        ),
        (
            "100 Woodruff Cir Ne Ste P375, Atlanta, Ga, 30322",
            "100 Woodruff Cir Ne, Atlanta, Ga, 30322",
        ),
        (
            "1818 New York Ave Ne, 228, Washington, Dc, 20002",
            "1818 New York Ave Ne, Washington, Dc, 20002",
        ),
        (
            "2080 N Tustin Ave Ste B, Santa Ana, Ca, 92705",
            "2080 N Tustin Ave, Santa Ana, Ca, 92705",
        ),
        (
            "Main St, Ste Genevieve, Mo, 63670",
            "Main St, Ste Genevieve, Mo, 63670",
        ),
        (
            "C/O Acme 100 Main St Ste 5, Boston, Ma, 02101",
            "100 Main St, Boston, Ma, 02101",
        ),
    ]

    for raw, expected in cases:
        got = processor._strip_for_census_strip(raw)
        ok = got == expected
        print(f"{'OK' if ok else 'FAIL'}: {raw}")
        if not ok:
            print(f"  expected: {expected}")
            print(f"  got:      {got}")
            raise AssertionError(f"suite strip failed for {raw!r}")


if __name__ == "__main__":
    test_suite_strip()
    print("All suite strip tests passed.")