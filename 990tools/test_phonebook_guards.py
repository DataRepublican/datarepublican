#!/usr/bin/env python3
"""Guards from the $100M ghost→EIN review. Run: python test_phonebook_guards.py"""

from bmf_fuzzy_candidate_matcher import (
    build_exact_core_phonebook,
    find_perfect_core_ein,
    is_generic_grantee,
    repair_ein_typo,
    resolve_donor_advised_fund_ein,
    resolve_phonebook_name,
)


def bmf(*rows):
    return [
        {"ein": e, "name": n, "asset_cd": a}
        for e, n, a in rows
    ]


def test_generic_never_matches():
    book = build_exact_core_phonebook(bmf(("473740770", "SEE FOUNDATION INC", 8)))
    assert is_generic_grantee("See Attachment")
    assert is_generic_grantee("VARIOUS - SEE ATTACHED")
    assert resolve_phonebook_name("See Attachment", book) is None
    assert resolve_phonebook_name("DONOR ADVISED FUND", book) is None


def test_who_is_not_world_organization():
    book = build_exact_core_phonebook(
        bmf(("611577084", "World Organization", 6), ("123456789", "WORLD HEALTH ORGANIZATION", 9))
    )
    assert find_perfect_core_ein("WORLD HEALTH ORGANIZATION", book) == "123456789"
    # If WHO is missing from the book, do not fall through to World Organization.
    book = build_exact_core_phonebook(bmf(("611577084", "World Organization", 6)))
    assert find_perfect_core_ein("WORLD HEALTH ORGANIZATION", book) is None


def test_university_not_its_fund():
    book = build_exact_core_phonebook(
        bmf(
            ("136166288", "UNIVERSITY OF PENNSYLVANIA FUND", 7),
            ("231353685", "UNIVERSITY OF PENNSYLVANIA", 9),
        )
    )
    assert find_perfect_core_ein("UNIVERSITY OF PENNSYLVANIA", book) == "231353685"
    assert find_perfect_core_ein("UNIVERSITY OF PENNSYLVANIA FUND", book) == "136166288"


def test_edf_not_edc():
    book = build_exact_core_phonebook(
        bmf(
            ("131640476", "ENVIRONMENTAL DEFENSE FUND", 9),
            ("770061994", "ENVIRONMENTAL DEFENSE CENTER", 7),
        )
    )
    assert find_perfect_core_ein("ENVIRONMENTAL DEFENSE FUND", book) == "131640476"
    assert find_perfect_core_ein("ENVIRONMENTAL DEFENSE CENTER", book) == "770061994"


def test_jhu_duplicate_picks_giant():
    book = build_exact_core_phonebook(
        bmf(
            ("520591627", "JOHNS HOPKINS UNIVERSITY", 0),
            ("520595110", "JOHNS HOPKINS UNIVERSITY", 9),
        )
    )
    assert find_perfect_core_ein("Johns Hopkins University", book) == "520595110"


def test_jhu_charity_filer_beats_bmf_clones():
    book = build_exact_core_phonebook(
        bmf(
            ("237424444", "JOHNS HOPKINS UNIVERSITY", 9),
            ("520591627", "JOHNS HOPKINS UNIVERSITY", 0),
            ("520595110", "JOHNS HOPKINS UNIVERSITY", 9),
        ),
        [
            {"ein": "520595110", "name": "JOHNS HOPKINS UNIVERSITY", "asset_cd": -1},
            {"ein": "237424444", "name": "JHPIEGO CORPORATION", "asset_cd": -1},
        ],
    )
    assert find_perfect_core_ein("JOHNS HOPKINS UNIVERSITY", book) == "520595110"


def test_princeton_subordinates_skipped_without_giant_same_name():
    # Real university files as PRINCETON UNIVERSITY; subordinates share TRUSTEES OF...
    book = build_exact_core_phonebook(
        bmf(
            ("371951649", "TRUSTEES OF PRINCETON UNIVERSITY", 0),
            ("222711242", "TRUSTEES OF PRINCETON UNIVERSITY", 0),
            ("210634501", "PRINCETON UNIVERSITY", 9),
        )
    )
    assert find_perfect_core_ein("TRUSTEES OF PRINCETON UNIVERSITY", book) is None
    assert find_perfect_core_ein("PRINCETON UNIVERSITY", book) == "210634501"


def test_ms_gift_picks_giant():
    book = build_exact_core_phonebook(
        bmf(
            ("320534221", "MORGAN STANLEY GLOBAL IMPACT FUNDING TRUST INC", 4),
            ("527082731", "MORGAN STANLEY GLOBAL IMPACT FUNDING TRUST INC", 9),
        )
    )
    assert find_perfect_core_ein("MORGAN STANLEY GLOBAL IMPACT FUNDING TRUST INC", book) == "527082731"


def test_daf_allowlist_not_family_foundations():
    assert resolve_donor_advised_fund_ein("FIDELITY CHARITABLE GIFT FUND") == "110303001"
    assert resolve_donor_advised_fund_ein("FIDELITY D & D CHARITABLE FOUNDATION") is None
    assert resolve_donor_advised_fund_ein("SCHWAB CHARITABLE (DONOR ADVISED FUND)") == "311640316"
    assert resolve_donor_advised_fund_ein("Elmont-Schwabe Charitable Corporation") is None
    assert resolve_donor_advised_fund_ein("VANGUARD CHARITABLE") == "232888152"
    assert resolve_donor_advised_fund_ein("The Vanguard Group Foundation") is None
    assert resolve_donor_advised_fund_ein("CHABOT FAMILY DAF - VANGUARD") == "232888152"
    assert resolve_donor_advised_fund_ein("DAF - STABLER CHARITABLE FUND") is None
    assert resolve_donor_advised_fund_ein("NATIONAL PHILANTHROPIC TRUST") == "237825575"


def test_gates_exact_and_inc_suffix():
    book = build_exact_core_phonebook(
        bmf(("562618866", "GATES FOUNDATION", 9), ("562618866", "BILL & MELINDA GATES FOUNDATION", 9))
    )
    assert find_perfect_core_ein("GATES FOUNDATION", book) == "562618866"
    assert find_perfect_core_ein("GATES FOUNDATION INC", book) == "562618866"


def test_digit_repair():
    by_ein = {
        "042103594": {"ein": "042103594", "name": "MASSACHUSETTS INSTITUTE OF TECHNOLOGY"},
        "951642394": {"ein": "951642394", "name": "UNIVERSITY OF SOUTHERN CALIFORNIA"},
        "042103580": {"ein": "042103580", "name": "PRESIDENT AND FELLOWS OF HARVARD COLLEGE"},
        "135562308": {"ein": "135562308", "name": "NEW YORK UNIVERSITY"},
        "237825575": {"ein": "237825575", "name": "NATIONAL PHILANTHROPIC TR"},
    }
    assert repair_ein_typo("042103694", "MASSACHUSETTS INSTITUTE OF TECHNOLOGY", by_ein) == "042103594"
    assert repair_ein_typo("911642394", "UNIVERSITY OF SOUTHERN CALIFORNIA", by_ein) == "951642394"
    assert repair_ein_typo("421035800", "President and Fellows Of Harvard College", by_ein) == "042103580"
    assert repair_ein_typo("135562309", "NEW YORK UNIVERSITY", by_ein) == "135562308"
    assert repair_ein_typo("237285575", "NATIONAL PHILANTHROPIC TRUST", by_ein) == "237825575"
    # Hamming-1 onto an unrelated org must not win
    by_ein["911183340"] = {"ein": "911183340", "name": "KNIGHTS OF COLUMBUS"}
    assert repair_ein_typo("911183380", "UNITED STATES FUND FOR UNICEF", by_ein) is None


def test_short_one_token_not_assigned():
    book = build_exact_core_phonebook(bmf(("043584637", "LIFE", 9), ("320582594", "LIFE INC", 6)))
    assert find_perfect_core_ein("LIFE", book) is None


def test_no_typo_repair_when_ein_exists():
    by_ein = {
        "340714585": {"ein": "340714585", "name": "CLEVELAND CLINIC FOUNDATION"},
        "340714588": {"ein": "340714588", "name": "CLEVELAND CLINIC FOUNDATION"},
    }
    assert repair_ein_typo("340714585", "CLEVELAND CLINIC FOUNDATION", by_ein) is None


def test_stanford_university_not_wt_foundation():
    book = build_exact_core_phonebook(
        bmf(("941156365", "STANFORD UNIVERSITY", 9), ("830708637", "WT STANFORD FOUNDATION", 6))
    )
    assert find_perfect_core_ein("STANFORD UNIVERSITY", book) == "941156365"
    assert find_perfect_core_ein("WT STANFORD FOUNDATION", book) == "830708637"


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok ", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, exc)
    if failed:
        raise SystemExit(1)
    print(f"{len(tests)} passed")
