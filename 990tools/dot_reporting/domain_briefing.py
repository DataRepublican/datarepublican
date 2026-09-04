#!/usr/bin/env python3
"""Self-documenting domain briefings + population percentile cutpoints.

Index pages use FOCUS_BRIEFINGS so each suite explains *what* we optimize for
and *why*. Population cutpoints (DuckDB quantile_cont) live in suite
export_metadata.json and drive absolute chips like ``carriers p99.9+``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from percentiles import duckdb_quantiles, format_quantile_table  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_PATH = SCRIPT_DIR / "cache" / "population_cutpoints.json"
CACHE_MAX_AGE_SEC = 7 * 24 * 3600  # refresh weekly by default

# Probabilities stored for every metric
CUT_PROBS = (0.5, 0.75, 0.9, 0.95, 0.99, 0.999)

# Metrics we materialize once and reuse across suite runs
CUTPOINT_METRICS: dict[str, dict[str, Any]] = {
    "dot_carriers_per_address": {
        "label": "DOT physical rows per canonical_address (phy only)",
        "money": False,
        "sql": """
            SELECT count(*)::DOUBLE
            FROM Addresses
            WHERE address_type = 'dot_carrier_phy'
            GROUP BY canonical_address
        """,
    },
    "medicare_paid_per_npi": {
        "label": "Medicare total_paid per billing NPI",
        "money": True,
        "sql": """
            SELECT total_paid::DOUBLE
            FROM medicare_provider_rollup
            WHERE total_paid > 0
        """,
    },
    "medicare_hcpcs_types": {
        "label": "HCPCS type count per NPI",
        "money": False,
        "sql": """
            SELECT hcpcs_type_count::DOUBLE
            FROM medicare_provider_rollup
            WHERE total_paid > 0
        """,
    },
    "medicare_paid_per_hcpcs_type": {
        "label": "Medicare paid / HCPCS type count",
        "money": True,
        "sql": """
            SELECT CASE
                     WHEN hcpcs_type_count > 0
                     THEN total_paid::DOUBLE / hcpcs_type_count
                   END
            FROM medicare_provider_rollup
            WHERE total_paid > 0 AND hcpcs_type_count > 0
        """,
    },
}

# Index-page methodology (self-documenting). Keys match focus ids + "dot" + "ofac".
FOCUS_BRIEFINGS: dict[str, dict[str, Any]] = {
    "dot": {
        "title": "What this view is for",
        "question": (
            "Is this an operational carrier farm — many DOT identities "
            "claiming the same physical footprint that should support real "
            "carrier duties (not just a mailbox and a laptop)?"
        ),
        "signals": [
            "High physical (`dot_carrier_phy`) carrier count at one street / suite / colocator",
            "Shared phone stacks (one number, dozens–hundreds of legal names)",
            "Active vs inactive authority mix at that physical key",
            "Address typo / variant farms (same lat-long, mangled city/street)",
            "Maps / Street View: yard, shop, or home — not a UPS Store / virtual office",
        ],
        "rank": (
            "Default rank: physical DOT records, then distinct address types "
            "(charity / contractor / NPPES / … at the same key). Active power "
            "units stay a column — they measure fleet size, not stack density. "
            "Mailing addresses (`dot_carrier_mail`) are ignored for matching and "
            "counts — paperwork only. Open the phone breakout on a detail page "
            "for dispatcher shells."
        ),
        "thresholds": (
            "Selection: multi-type ≥ N OR physical DOT carriers ≥ M. "
            "Population note: most phy addresses have 1 DOT row; the high tail "
            "(p99 / p99.9) is extreme — large M is not “a bit high.”"
        ),
        "caveats": (
            "MCS-150 physical can still be a mail drop mis-coded as phy. "
            "Search Carriers may show a newer physical than our snapshot. "
            "We intentionally do not rank on mailing. Requirements below are "
            "general FMCSR / New Entrant expectations (49 CFR Parts 382–396, "
            "390.29); not every rule applies to every carrier size or commodity."
        ),
        # needs_physical=True → bold in UI: needs more than a computer + printer
        "carrier_duties": [
            {
                "text": (
                    "Operate commercial motor vehicles (CMVs) in commerce under a "
                    "USDOT number / operating authority — actual trucks on public roads"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Inspect, repair, and maintain CMVs (preventive maintenance, "
                    "periodic/annual inspections, correct out-of-service defects) — "
                    "Part 396; needs vehicles and a place to work on them"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Driver vehicle inspection reports (DVIR) and repair-before-dispatch "
                    "when defects are found — tied to real equipment, not a PMB"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Employ / dispatch CDL drivers: qualification files, annual MVRs, "
                    "medical certificates, prior-employer investigations — Part 391 "
                    "(records can be electronic, but the driver workforce is real)"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Hours of service / ELD (or other RODS) compliance and retention "
                    "of supporting documents — Part 395; drivers and vehicles, not a mailbox"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Controlled substances & alcohol program for CDL drivers: "
                    "pre-employment, random, post-accident, reasonable suspicion testing; "
                    "Clearinghouse queries — Part 382 (testing is real-world; a C/TPA "
                    "can administer, but the carrier still must run a program)"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Maintain an accident register and crash-related records — Part 390"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Make required safety records available for FMCSA / state inspection "
                    "at the principal place of business (or produce them within 48 hours) "
                    "— 49 CFR 390.29; a UPS Store box is not a credible PPB for a fleet"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Carry required levels of public liability / cargo insurance and "
                    "keep filings current (when subject to financial responsibility rules)"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Pass New Entrant safety audit review of systems: driver qualification, "
                    "duty status, vehicle maintenance, accident register, drug/alcohol "
                    "— 49 CFR Part 385 Subpart D"
                ),
                "needs_physical": True,
            },
            {
                "text": (
                    "Register for a USDOT number, file MCS-150 / biennial updates, and "
                    "keep census data current — can be done online with a computer"
                ),
                "needs_physical": False,
            },
            {
                "text": (
                    "Designate process agents / boilerplate corporate filings in many "
                    "states — paper / portal work, not a truck yard"
                ),
                "needs_physical": False,
            },
            {
                "text": (
                    "Print BOLs, rate confirmations, or lease packets — computer + printer "
                    "only; not evidence of operations"
                ),
                "needs_physical": False,
            },
        ],
        "cutpoint_keys": ["dot_carriers_per_address"],
        "chip_rules": [
            {
                "metric": "dot_carriers_per_address",
                "field": "dot_carrier_count",
                "label": "carriers",
            },
        ],
    },
    "medicare": {
        "title": "What this view is for",
        "question": (
            "Where does Medicare paid concentrate in ways that look like "
            "billing mills rather than hospital campuses?"
        ),
        "signals": [
            "High paid with a narrow HCPCS / procedure mix (few code types)",
            "High $ per billing NPI or per code type (intensity)",
            "Many NPIs at one suite / industrial corridor / mill street",
            "Home-care / personal-care code families (e.g. T1019-class) when present",
            "Multi-type co-tenants (990 / DOT / FEC) at the same key",
        ],
        "rank": (
            "Admission: any key with ≥1 NPPES practice/mailing row (no multi-type "
            "or density floor). Default rank: Medicare paid ÷ HCPCS type count "
            "(cluster intensity). High $ with a narrow codebook (e.g. T1019 mills) "
            "rises; full-spectrum hospitals fall relative to pure $ sort. "
            "Suite size: top N after rank (max_clusters)."
        ),
        "thresholds": (
            "Population: median NPI paid ~$56K; p99 ~$30M. "
            "Median HCPCS types ~4; p90 ~20. "
            "Narrow-code intensity (paid/types) p95 ~$824K — primary rank ingredient."
        ),
        "caveats": (
            "Public rollups are imperfect; multi-tenant medical buildings and "
            "county campuses create false density. Not an allegation of fraud."
        ),
        "cutpoint_keys": [
            "medicare_paid_per_hcpcs_type",
            "medicare_paid_per_npi",
            "medicare_hcpcs_types",
        ],
        "chip_rules": [
            {
                "metric": "medicare_paid_per_hcpcs_type",
                "field": "paid_per_hcpcs_type",
                "label": "$/types",
                "money": True,
            },
            {
                "metric": "medicare_paid_per_npi",
                "field": "focus_amount",
                "label": "paid",
                "money": True,
            },
        ],
    },
    "fec": {
        "title": "What this view is for",
        "question": (
            "Where do many FEC contributor / committee / spend address rows "
            "stack on the same geographic key?"
        ),
        "signals": [
            "High entity-row count (donor / committee density)",
            "Distinct individual contributors at one street",
            "Mix of contributor vs committee vs expenditure types",
            "Co-location with 990 / Medicare / DOT (dual signal)",
        ],
        "rank": (
            "Default rank: FEC address-row count (density), then distinct "
            "contributors, then $. Mega committee wires no longer own the list."
        ),
        "thresholds": (
            "Party HQs and mail houses still stack; prefer multi-type and "
            "non-HQ geography for odd donor mills."
        ),
        "caveats": "Shared commercial mail and consultant suites are common false positives.",
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "fec_committee": {
        "title": "What this view is for",
        "question": (
            "Which FEC *committee* streets (real line 1, not 29M contributor "
            "city/ZIP blobs) sit on the same colocator as a 990 charity, "
            "contractor, DOT carrier, or NPPES provider?"
        ),
        "signals": [
            "fec_committee row with a non-empty address_line1",
            "Same tight colocator as charity / contractor / DOT phy / NPPES",
            "How many of those four families share the street",
        ],
        "rank": (
            "Default rank: count of other-type families (0–4), then other-type "
            "row count, then committee rows. Bulk FEC types are not a focus."
        ),
        "thresholds": (
            "Admission requires at least one other family. Party HQs and "
            "K Street / Capitol Hill office buildings will still dominate."
        ),
        "caveats": (
            "Colocator is street/building, not suite. Shared mail drops and "
            "law-firm floors are expected false-ish positives."
        ),
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "contractor": {
        "title": "What this view is for",
        "question": (
            "Which 990 contractor payees concentrate money — and which "
            "addresses are multi-suite contractor shells?"
        ),
        "signals": [
            "High contractor payment $ (who got paid)",
            "Many distinct contractor streets at one colocator (suite-mill mode)",
            "Overlap with grants / officers / DOT at the same key",
        ],
        "rank": (
            "Default rank: distinct focus addresses (shell / multi-suite bias). "
            "For pure money, re-sort or treat $ as the investigative metric."
        ),
        "thresholds": "Geography is optional for the payee story; central for suite mills.",
        "caveats": "Large legitimate vendors (software, facilities) also rank high on $.",
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "grants": {
        "title": "What this view is for",
        "question": (
            "Where does Form 990 grant money *land* — grantee / grant addresses "
            "(incoming NGO grants by recipient geography)?"
        ),
        "signals": [
            "High grant $ (excluding known name-suppressed privacy rollups when applied)",
            "Many grant rows / grantees at one key",
            "Co-location with contractors, officers, or OFAC",
        ],
        "rank": "Default rank: incoming grant $ (suppressed-name exclusions when configured).",
        "thresholds": "Big foundations and universities dominate; look for odd multi-type stacks.",
        "caveats": "Name-suppressed rows can distort $; check suite notes.",
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "grants_out": {
        "title": "What this view is for",
        "question": (
            "Where do Form 990 *filers* that grant money out concentrate — "
            "charity addresses ranked by grants_to_others?"
        ),
        "signals": [
            "High grants_to_others $ at a filer address / colocator / ZIP",
            "Foundation / pass-through shells with thin multi-type co-tenants",
            "Same footprint as large incoming-grant recipients or USG-funded orgs",
        ],
        "rank": (
            "Default rank: sum of Charities.grants_to_others across filer rows "
            "at the geographic key (multi-year filings add)."
        ),
        "thresholds": "Large private foundations and national charities dominate the top.",
        "caveats": (
            "This is the *giver* side (filer geography), not where the money landed. "
            "Compare with NGO Grants (incoming) for recipient addresses."
        ),
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "usg": {
        "title": "What this view is for",
        "question": (
            "Where do nonprofits that report government funding concentrate — "
            "charity addresses ranked by Form 990 govt_amt?"
        ),
        "signals": [
            "High govt_amt (government grants / contributions reported on the 990)",
            "Contractor / research institutes and healthcare systems with federal money",
            "Multi-year filings stacked at one suite / campus",
        ],
        "rank": (
            "Default rank: sum of Charities.govt_amt across filer rows at the key "
            "(multi-year filings add)."
        ),
        "thresholds": (
            "National labs, hospitals, and large contractors often top pure $. "
            "Look for odd small orgs with high govt_amt relative to footprint."
        ),
        "caveats": (
            "govt_amt is filer-reported government support on the 990 — not a "
            "complete USAspending award ledger. Multi-year rows can inflate SUM ranks."
        ),
        "cutpoint_keys": [],
        "chip_rules": [],
    },
    "ofac": {
        "title": "What this view is for",
        "question": (
            "Does a Treasury SDN / sanctions address share a footprint with "
            "US commercial or program data (990, Medicare, DOT, FEC)?"
        ),
        "signals": [
            "OFAC entities at a street / colocator / ZIP",
            "Any co-tenant rows: charities, grants, Medicare, DOT, FEC",
            "Program tags (e.g. country / EO designations) on the SDN rows",
        ],
        "rank": "Co-location richness beats nearby hospital $.",
        "thresholds": "Even 1 SDN + Medicare/990 rows is review-worthy.",
        "caveats": (
            "Shared towers and mail services create innocent co-location. "
            "Confirm UIDs on sanctionssearch.ofac.treas.gov."
        ),
        "cutpoint_keys": [],
        "chip_rules": [],
    },
}


def briefing_for(focus: str) -> dict[str, Any]:
    return dict(FOCUS_BRIEFINGS.get(focus or "dot") or FOCUS_BRIEFINGS["dot"])


def _empty_cache() -> dict[str, Any]:
    return {"generated_at": None, "metrics": {}}


def load_cutpoints_cache(path: Path | None = None) -> dict[str, Any]:
    p = path or CACHE_PATH
    if not p.exists():
        return _empty_cache()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _empty_cache()


def save_cutpoints_cache(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def compute_population_cutpoints(
    conn,
    *,
    keys: list[str] | None = None,
    probs: tuple[float, ...] = CUT_PROBS,
) -> dict[str, Any]:
    """Compute selected metrics via DuckDB; return {metric: quantile result}."""
    want = keys or list(CUTPOINT_METRICS.keys())
    out: dict[str, Any] = {}
    for key in want:
        cfg = CUTPOINT_METRICS.get(key)
        if not cfg:
            continue
        try:
            res = duckdb_quantiles(conn, cfg["sql"].strip(), probs=probs)
            res["label"] = cfg["label"]
            res["money"] = bool(cfg.get("money"))
            out[key] = res
        except Exception as e:
            out[key] = {"error": str(e), "label": cfg["label"], "quantiles": {}}
    return out


def ensure_population_cutpoints(
    conn=None,
    *,
    keys: list[str] | None = None,
    force: bool = False,
    cache_path: Path | None = None,
    max_age_sec: float = CACHE_MAX_AGE_SEC,
) -> dict[str, Any]:
    """Return full cache doc, refreshing stale/missing metrics if conn provided."""
    cache = load_cutpoints_cache(cache_path)
    metrics: dict[str, Any] = dict(cache.get("metrics") or {})
    want = keys or list(CUTPOINT_METRICS.keys())
    missing = [k for k in want if k not in metrics or not metrics[k].get("quantiles")]

    gen = cache.get("generated_at")
    age_ok = False
    if gen and not force:
        try:
            # ISO timestamp
            from datetime import datetime

            age = time.time() - datetime.fromisoformat(str(gen)).timestamp()
            age_ok = age < max_age_sec
        except Exception:
            age_ok = False

    need = force or missing or not age_ok
    if need and conn is not None:
        computed = compute_population_cutpoints(conn, keys=want)
        metrics.update(computed)
        from datetime import datetime

        cache = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "probs": list(CUT_PROBS),
            "metrics": metrics,
            "source": "duckdb quantile_cont",
        }
        save_cutpoints_cache(cache, cache_path)
    elif not cache.get("metrics"):
        cache = {"generated_at": None, "metrics": metrics, "probs": list(CUT_PROBS)}
    return cache


def cutpoints_for_focus(focus: str, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Subset of population metrics relevant to this focus."""
    brief = briefing_for(focus)
    cache = cache or load_cutpoints_cache()
    metrics = cache.get("metrics") or {}
    keys = brief.get("cutpoint_keys") or []
    return {k: metrics[k] for k in keys if k in metrics}


def _pct_label(p: float) -> str:
    pct = p * 100
    if abs(pct - round(pct)) < 0.05:
        return f"p{int(round(pct))}"
    return f"p{pct:.1f}".rstrip("0").rstrip(".")


def value_population_percentile(
    value: float | None,
    metric_result: dict[str, Any],
) -> str | None:
    """Map a value to the highest cutpoint it meets, e.g. 'p99.9+' or 'p95+'."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    qs = metric_result.get("quantiles") or {}
    if not qs:
        return None
    # qs keys may be str after JSON
    items = sorted(((float(p), float(q)) for p, q in qs.items()), key=lambda x: x[0])
    met: float | None = None
    for p, q in items:
        if v >= q:
            met = p
    if met is None:
        # below p50
        p0, q0 = items[0]
        if v < q0:
            return f"<{_pct_label(p0)}"
        return None
    return f"{_pct_label(met)}+"


def annotate_cluster_percentile_chips(
    cluster: dict[str, Any],
    focus: str,
    cutpoints: dict[str, Any] | None,
) -> list[str]:
    """Return chip labels for absolute population percentiles."""
    if not cutpoints:
        return []
    brief = briefing_for(focus)
    chips: list[str] = []
    for rule in brief.get("chip_rules") or []:
        metric_key = rule["metric"]
        field = rule["field"]
        label = rule.get("label") or field
        mres = cutpoints.get(metric_key) or {}
        val = cluster.get(field)
        if val is None and field == "dot_carrier_count":
            val = cluster.get("focus_count")
        tag = value_population_percentile(val, mres)
        if not tag:
            continue
        # Only show meaningful tail chips on detail (p90+)
        if tag.startswith("<"):
            continue
        try:
            # p90+ → 90
            num = float(tag.lstrip("p").rstrip("+").replace("p", ""))
        except ValueError:
            num = 0
        if num < 90 and not tag.endswith("9+"):
            # keep p90, p95, p99, p99.9
            if "90" not in tag and "95" not in tag and "99" not in tag:
                continue
        chips.append(f"{label} {tag}")
    return chips


def cutpoints_summary_lines(cutpoints: dict[str, Any]) -> list[str]:
    """Short lines for index methodology box."""
    lines: list[str] = []
    for key, res in cutpoints.items():
        if res.get("error"):
            lines.append(f"{key}: error {res['error']}")
            continue
        label = res.get("label") or key
        qs = res.get("quantiles") or {}
        if not qs:
            continue
        # compact: p50 / p90 / p99 / p99.9
        bits = []
        for p in (0.5, 0.9, 0.99, 0.999):
            # JSON may stringify keys
            q = qs.get(p, qs.get(str(p)))
            if q is None:
                continue
            money = res.get("money")
            if money:
                if q >= 1e6:
                    bits.append(f"{_pct_label(p)}=${q/1e6:.1f}M")
                elif q >= 1e3:
                    bits.append(f"{_pct_label(p)}=${q/1e3:.0f}K")
                else:
                    bits.append(f"{_pct_label(p)}=${q:,.0f}")
            else:
                bits.append(f"{_pct_label(p)}={q:g}")
        n = res.get("count")
        nbit = f"n={int(n):,}" if n else ""
        lines.append(f"{label}: " + ", ".join(bits) + (f" ({nbit})" if nbit else ""))
    return lines


def index_methodology_context(focus: str, cutpoints: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bundle for Mako index templates."""
    brief = briefing_for(focus)
    cps = cutpoints if cutpoints is not None else cutpoints_for_focus(focus)
    return {
        "focus": focus,
        "title": brief.get("title") or "What this view is for",
        "question": brief.get("question") or "",
        "signals": list(brief.get("signals") or []),
        "rank": brief.get("rank") or "",
        "thresholds": brief.get("thresholds") or "",
        "caveats": brief.get("caveats") or "",
        "carrier_duties": list(brief.get("carrier_duties") or []),
        "cutpoint_lines": cutpoints_summary_lines(cps),
        "cutpoints": cps,
    }
