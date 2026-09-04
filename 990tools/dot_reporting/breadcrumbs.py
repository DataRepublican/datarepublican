#!/usr/bin/env python3
"""Breadcrumb trails that always reach reports/master_index.html."""

from __future__ import annotations

from typing import Any


def _crumb(label: str, href: str | None = None) -> dict[str, Any]:
    return {"label": label, "href": href}


def focus_label(focus: str | None) -> str:
    return {
        "dot": "DOT / trucking",
        "medicare": "Medicare / NPPES",
        "fec": "FEC",
        "fec_committee": "FEC committee × other",
        "contractor": "Contractors",
        "grants": "NGO Grants (in)",
        "grants_out": "NGO Grants (out)",
        "usg": "USG NGO Funding",
    }.get(focus or "dot", focus or "Report")


def slice_label(slice_by: str | None) -> str:
    return {
        "address": "Address",
        "colocator": "Colocator",
        "loose_colocator": "Loose colocator",
        "zipcode": "Zip code",
        "colocator_ll": "Colocator (LL only)",
    }.get(slice_by or "", slice_by or "clusters")


def national_suite_label(focus: str | None, slice_by: str | None) -> str:
    return f"{focus_label(focus)} · {slice_label(slice_by)}"


def by_state_suite_label(focus: str | None, slice_by: str | None) -> str:
    return f"{focus_label(focus)} · {slice_label(slice_by)} · by state"


def crumbs_national_index(*, focus: str = "dot", slice_by: str = "address") -> list[dict]:
    """reports/<suite>/index.html"""
    return [
        _crumb("All reports", "../master_index.html"),
        _crumb(national_suite_label(focus, slice_by)),
    ]


def crumbs_national_detail(
    *, focus: str = "dot", slice_by: str = "address", detail_label: str
) -> list[dict]:
    """reports/<suite>/<detail>.html"""
    return [
        _crumb("All reports", "../master_index.html"),
        _crumb(national_suite_label(focus, slice_by), "index.html"),
        _crumb(detail_label[:80] + ("…" if len(detail_label) > 80 else "")),
    ]


def crumbs_by_state_us(*, focus: str = "dot", slice_by: str = "address") -> list[dict]:
    """reports/<focus>_<slice>_by_state_DATE/index.html"""
    return [
        _crumb("All reports", "../master_index.html"),
        _crumb(by_state_suite_label(focus, slice_by)),
    ]


def crumbs_by_state_state(
    *, focus: str = "dot", slice_by: str = "address", state: str
) -> list[dict]:
    """reports/.../states/XX/index.html"""
    return [
        _crumb("All reports", "../../../master_index.html"),
        _crumb(by_state_suite_label(focus, slice_by), "../../index.html"),
        _crumb(f"State {state}"),
    ]


def crumbs_by_state_detail(
    *,
    focus: str = "dot",
    slice_by: str = "address",
    state: str,
    detail_label: str,
) -> list[dict]:
    """reports/.../states/XX/<detail>.html"""
    return [
        _crumb("All reports", "../../../master_index.html"),
        _crumb(by_state_suite_label(focus, slice_by), "../../index.html"),
        _crumb(f"State {state}", "index.html"),
        _crumb(detail_label[:80] + ("…" if len(detail_label) > 80 else "")),
    ]
