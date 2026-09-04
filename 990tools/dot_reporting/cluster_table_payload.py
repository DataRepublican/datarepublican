#!/usr/bin/env python3
"""Build JSON payloads for TanStack cluster index tables."""

from __future__ import annotations

import html
import json
from typing import Any

from html_format import linkify_zip_codes, zip_link_html  # noqa: E402
from percentiles import MetricScale  # noqa: E402


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def metric_tier(value: float, vmax: float) -> str:
    """Legacy bands vs max (value/vmax tertiles). Prefer MetricScale.tier()."""
    if vmax <= 0 or value is None:
        return "none"
    t = min(1.0, float(value) / float(vmax))
    if t > 0.66:
        return "high"
    if t > 0.33:
        return "mid"
    return "low"


def rank_dot_html(
    value: float,
    vmax: float | None = None,
    *,
    kind: str | None = None,
    scale: Any | None = None,
    label: str = "metric",
) -> str:
    """Colored rank pip.

    Prefer passing ``scale=MetricScale.from_values(...)`` so color + tooltip
    use empirical percentiles (p50/p90/p99) within the series, not value/max.
    """
    if kind == "po_zip":
        cls = "po"
        title = "PO Box (zip centroid)"
    elif scale is not None:
        cls = scale.tier(value)
        title = scale.tier_title(value, label=label)
    else:
        cls = metric_tier(value, float(vmax or 0))
        title = {
            "high": "Higher rank metric",
            "mid": "Mid rank metric",
            "low": "Lower rank metric",
            "none": "No metric",
        }.get(cls, "")
    return f'<span class="rank-dot {cls}" title="{_esc(title)}"></span>'


def build_dot_cluster_table(clusters: list[dict], *, min_dot_carriers: int) -> dict[str, Any]:
    # Composite matches SQL: records dominate, types break ties (types ≪ 100).
    def _rank_tuple(c: dict) -> tuple[int, int]:
        return (
            int(c.get("dot_carrier_count") or 0),
            int(c.get("multi_type_count") or 0),
        )

    metrics = [float(d * 100 + t) for d, t in (_rank_tuple(c) for c in clusters)]
    scale = MetricScale.from_values(metrics)
    vmax = scale.vmax
    rows = []
    for c in clusters:
        maps = c.get("maps_url") or "#"
        addr = c.get("canonical_address") or c.get("cluster_key") or ""
        detail = c.get("detail_file") or "#"
        slug = c.get("slug") or ""
        reasons = ", ".join(c.get("reason_codes") or [])
        grift = c.get("max_grift_ratio")
        grift_s = f"{grift:.1f}" if grift is not None else "—"
        active_pu = int(c.get("active_power_units") or c.get("dot_active_power_units") or 0)
        dots_n, types_n = _rank_tuple(c)
        rank_val = dots_n * 100 + types_n
        key = str(c.get("cluster_key") or "")
        kind = "po_zip" if key.upper().startswith("PO:") else None
        # Zip-only keys: primary label is the ZIP search link; else maps link with
        # embedded ZIP search links in the street string.
        if key.isdigit() and len(key) == 5:
            addr_html = (
                zip_link_html(key)
                + (
                    f'  ·  e.g. <a href="{_esc(maps)}" target="_blank" rel="noopener">'
                    f"{linkify_zip_codes(c.get('sample_address') or '')}</a>"
                    if c.get("sample_address")
                    else ""
                )
            )
        else:
            addr_html = (
                f'<a href="{_esc(maps)}" target="_blank" rel="noopener">'
                f"{linkify_zip_codes(addr)}</a>"
            )
        pct = scale.percentile(rank_val)
        rows.append(
            {
                "slug": slug,
                "rank": rank_val,
                "rank_html": rank_dot_html(
                    rank_val, vmax, kind=kind, scale=scale, label="DOT records · types"
                )
                + _esc(f"{dots_n:,} · {types_n} types"),
                "percentile": pct,
                "score": int(c.get("suspicion_score") or 0),
                "address": addr,
                "address_html": addr_html,
                "types": types_n,
                "dot": dots_n,
                "active_pus": active_pu,
                "rows": int(c.get("total_rows") or 0),
                "max_grift": grift_s,
                "misrep": int(c.get("misrep_count") or 0),
                "reasons": reasons,
                "review_html": (
                    f'<button onclick="setReview(this, \'{_esc(slug)}\', false)" '
                    f'style="font-size:0.75rem; padding:1px 6px;">Not</button> '
                    f'<button onclick="setReview(this, \'{_esc(slug)}\', \'ins\')" '
                    f'style="font-size:0.75rem; padding:1px 6px; background:#d97706; color:white; border:none;">Ins</button> '
                    f'<button onclick="setReview(this, \'{_esc(slug)}\', \'dot\')" '
                    f'style="font-size:0.75rem; padding:1px 6px; background:#b91c1c; color:white; border:none;">DOT</button>'
                ),
                "detail_html": f'<a href="{_esc(detail)}">Detail →</a>',
                "dot_heavy": int(c.get("dot_carrier_count") or 0) >= min_dot_carriers,
                "phy_po_box": bool(c.get("phy_is_po_box")),
                "has_physical": "dot_carrier_phy" in (c.get("address_types") or []),
            }
        )
    columns = [
        {"id": "rank", "header": "● DOT rec · types"},
        {"id": "score", "header": "Score"},
        {"id": "address", "header": "Address"},
        {"id": "types", "header": "Types"},
        {"id": "dot", "header": "DOT"},
        {"id": "active_pus", "header": "Active PUs"},
        {"id": "rows", "header": "Rows"},
        {"id": "max_grift", "header": "Max Grift"},
        {"id": "misrep", "header": "Misrep"},
        {"id": "reasons", "header": "Reasons"},
        {"id": "review_html", "header": "Review", "sortable": False},
        {"id": "detail_html", "header": "", "sortable": False},
    ]
    return {
        "rows": rows,
        "columns": columns,
        "initialSort": [{"id": "rank", "desc": True}, {"id": "types", "desc": True}],
        "pageSize": 50,
        "rank_metric": "dot_records_types",
        "rank_label": "DOT records · types",
    }


def build_focus_cluster_table(
    clusters: list[dict],
    *,
    focus: str,
    min_focus: int,
    rank_metric: str,
    rank_label: str,
) -> dict[str, Any]:
    # Precompute metric values for scale
    metric_vals: list[float] = []
    for c in clusters:
        mv = c.get("rank_metric_value")
        if mv is None:
            if rank_metric in ("focus_amount", "grant_dollars", "fec_dollars"):
                mv = float(c.get("focus_amount") or 0)
            elif rank_metric in ("paid_per_hcpcs_type",):
                mv = float(c.get("paid_per_hcpcs_type") or c.get("rank_metric_value") or 0)
            elif rank_metric in ("active_power_units",):
                mv = float(c.get("active_power_units") or 0)
            elif rank_metric in ("distinct_addresses", "address_count"):
                mv = float(c.get("distinct_focus_addresses") or c.get("focus_count") or 0)
            else:
                mv = float(c.get("focus_count") or 0)
        metric_vals.append(float(mv or 0))
    scale = MetricScale.from_values(metric_vals)
    vmax = scale.vmax

    rows = []
    for c, metric_val in zip(clusters, metric_vals):
        maps = c.get("maps_url") or "#"
        addr = c.get("canonical_address") or c.get("cluster_key") or ""
        detail = c.get("detail_file") or "#"
        slug = c.get("slug") or ""
        reasons = ", ".join(c.get("reason_codes") or [])
        grift = c.get("max_grift_ratio")
        grift_s = f"{grift:.1f}" if grift is not None else "—"
        metric_display = c.get("rank_metric_fmt")
        if metric_display is None:
            moneyish = (
                rank_metric.endswith("amount")
                or "dollar" in rank_metric
                or "paid_per" in rank_metric
                or rank_metric
                in (
                    "focus_amount",
                    "grant_dollars",
                    "fec_dollars",
                    "paid_per_hcpcs_type",
                )
            )
            if moneyish and isinstance(metric_val, (int, float)):
                from generate_address_reports import fmt_money  # noqa: WPS433

                metric_display = fmt_money(metric_val)
            else:
                metric_display = (
                    f"{int(metric_val):,}" if metric_val is not None else "—"
                )
        key = str(c.get("cluster_key") or "")
        kind = "po_zip" if key.upper().startswith("PO:") else None
        if key.isdigit() and len(key) == 5:
            addr_html = (
                zip_link_html(key)
                + (
                    f'  ·  e.g. <a href="{_esc(maps)}" target="_blank" rel="noopener">'
                    f"{linkify_zip_codes(c.get('sample_address') or '')}</a>"
                    if c.get("sample_address")
                    else ""
                )
            )
        else:
            addr_html = (
                f'<a href="{_esc(maps)}" target="_blank" rel="noopener">'
                f"{linkify_zip_codes(addr)}</a>"
            )
        rows.append(
            {
                "slug": slug,
                "score": int(c.get("suspicion_score") or 0),
                "address": addr,
                "address_html": addr_html,
                "types": int(c.get("multi_type_count") or 0),
                "focus_n": int(c.get("focus_count") or 0),
                "rank_metric": metric_val,
                "rank_metric_display": metric_display,
                "rank_metric_html": rank_dot_html(
                    metric_val,
                    vmax,
                    kind=kind,
                    scale=scale,
                    label=rank_label or "metric",
                )
                + _esc(str(metric_display)),
                "percentile": scale.percentile(metric_val),
                "rows": int(c.get("total_rows") or 0),
                "max_grift": grift_s,
                "misrep": int(c.get("misrep_count") or 0),
                "reasons": reasons,
                "review_html": (
                    f'<button onclick="setReview(this, \'{_esc(slug)}\', \'not\')" '
                    f'style="font-size:0.75rem; padding:1px 6px;">Not</button> '
                    f'<button onclick="setReview(this, \'{_esc(slug)}\', \'sus\')" '
                    f'style="font-size:0.75rem; padding:1px 6px; background:#b91c1c; color:white; border:none;">Sus</button>'
                ),
                "detail_html": f'<a href="{_esc(detail)}">Detail →</a>',
                "dot_heavy": int(c.get("focus_count") or 0) >= min_focus,
                "phy_po_box": bool(c.get("phy_is_po_box")),
                "has_physical": False,
            }
        )
    columns = [
        {"id": "rank_metric", "header": f"● {rank_label}"},
        {"id": "score", "header": "Score"},
        {"id": "address", "header": "Cluster"},
        {"id": "types", "header": "Types"},
        {"id": "focus_n", "header": "Focus #"},
        {"id": "rows", "header": "Rows"},
        {"id": "max_grift", "header": "Max Grift"},
        {"id": "misrep", "header": "Misrep"},
        {"id": "reasons", "header": "Reasons"},
        {"id": "review_html", "header": "Review", "sortable": False},
        {"id": "detail_html", "header": "", "sortable": False},
    ]
    return {
        "rows": rows,
        "columns": columns,
        "initialSort": [{"id": "rank_metric", "desc": True}],
        "pageSize": 50,
        "rank_metric": rank_metric,
        "rank_label": rank_label,
        "focus": focus,
    }


def build_state_heatmap_table(
    states: list[dict[str, Any]],
    *,
    focus: str,
) -> dict[str, Any]:
    """TanStack payload for the national by-state heatmap index."""
    usg = focus == "usg"
    rows: list[dict[str, Any]] = []
    for s in states:
        st = str(s.get("state") or "")
        show = int(s.get("show_n") or 0)
        href = f"states/{st}/index.html" if show > 0 and st else ""
        row: dict[str, Any] = {
            "state": st,
            "state_html": (
                f'<a href="{_esc(href)}">{_esc(st)}</a>' if href else _esc(st)
            ),
            "pass_clusters": int(s.get("pass_clusters") or 0),
            "show_n": show,
            "focus_rows": int(s.get("focus_rows") or 0),
            "detail_html": (
                f'<a href="{_esc(href)}">Open →</a>' if href else "—"
            ),
        }
        if usg or s.get("focus_amount") is not None:
            amt = float(s.get("focus_amount") or 0)
            per = float(s.get("amount_per_ein") or 0)
            row["focus_amount"] = amt
            row["focus_amount_html"] = _esc(s.get("focus_amount_fmt") or "—")
            row["distinct_eins"] = int(s.get("distinct_eins") or 0)
            row["amount_per_ein"] = per
            row["amount_per_ein_html"] = _esc(s.get("amount_per_ein_fmt") or "—")
        rows.append(row)

    columns: list[dict[str, Any]] = [{"id": "state", "header": "State"}]
    if usg or any("focus_amount" in r for r in rows):
        columns.extend(
            [
                {"id": "focus_amount", "header": "Govt $"},
                {"id": "distinct_eins", "header": "EINs"},
                {"id": "amount_per_ein", "header": "$ / EIN"},
            ]
        )
    columns.extend(
        [
            {"id": "pass_clusters", "header": "Pass clusters"},
            {"id": "show_n", "header": "Show"},
            {"id": "focus_rows", "header": "Focus rows"},
            {"id": "detail_html", "header": "", "sortable": False},
        ]
    )
    return {
        "rows": rows,
        "columns": columns,
        "initialSort": [
            {
                "id": "focus_amount" if usg else "pass_clusters",
                "desc": True,
            }
        ],
        "pageSize": 100,
        "pageSizeOptions": [25, 50, 100, 200],
        "focus": focus,
    }


def dumps_table_json(payload: Any) -> str:
    """JSON for embedding in <script> (safe for </script> via unicode escape)."""
    return json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")


def _dot_link_html(dot_number: Any) -> str:
    d = _esc(dot_number or "")
    if not d:
        return "—"
    return (
        f'<a href="https://searchcarriers.com/company/{d}" target="_blank" rel="noopener">{d}</a> '
        f'<small>['
        f'<a href="https://searchcarriers.com/company/{d}" target="_blank" rel="noopener">SC</a>] '
        f'[<a href="https://searchcarriers.com/map/company/{d}" target="_blank" rel="noopener" '
        f'title="Search Carriers map" aria-label="Search Carriers map">🌐</a>] '
        f'[<a href="https://motus.dot.gov/customer/{d}/account" target="_blank" rel="noopener">MOTUS</a>]'
        f"</small>"
    )


def build_detail_tables(
    *,
    charities: list[dict] | None = None,
    officers: list[dict] | None = None,
    grants: list[dict] | None = None,
    address_subgroups: list[dict] | None = None,
    phone_groups: list | None = None,
    address_groups: list[dict] | None = None,
    entities: list[dict] | None = None,
    focus: str | None = None,
    entity_title: str = "Entities",
) -> list[dict[str, Any]]:
    """Build multi-table TanStack configs for cluster detail pages."""
    tables: list[dict[str, Any]] = []

    if address_subgroups:
        rows = []
        for a in address_subgroups:
            addr = a.get("canonical_address") or ""
            maps = a.get("maps_url") or ""
            types = ", ".join(a.get("address_types") or [])
            addr_core = (
                f'<a href="{_esc(maps)}" target="_blank" rel="noopener">{linkify_zip_codes(addr)}</a>'
                if maps
                else linkify_zip_codes(addr)
            )
            rows.append(
                {
                    "address": addr,
                    "address_html": addr_core
                    + (
                        ' <span class="chip" style="background:#fee2e2;color:#991b1b;">PO Box</span>'
                        if a.get("phy_is_po_box")
                        else ""
                    ),
                    "rows": int(a.get("total_rows") or 0),
                    "types": types,
                    "dot": int(a.get("dot_carrier_count") or 0),
                    "active_pu": int(a.get("active_power_units") or 0),
                    "inactive_pu": int(a.get("inactive_power_units") or 0),
                    "charities": int(a.get("charity_count") or 0),
                    "grants": int(a.get("grant_count") or 0),
                    "officers": int(a.get("officer_count") or 0),
                    "dot_heavy": int(a.get("dot_carrier_count") or 0) >= 10,
                }
            )
        tables.append(
            {
                "rootId": "ts-address-subgroups",
                "pageSize": 25,
                "initialSort": [{"id": "dot", "desc": True}, {"id": "types", "desc": True}],
                "columns": [
                    {"id": "address", "header": "Street address"},
                    {"id": "rows", "header": "Rows"},
                    {"id": "types", "header": "Types"},
                    {"id": "dot", "header": "DOT"},
                    {"id": "active_pu", "header": "Active PU"},
                    {"id": "inactive_pu", "header": "Inactive PU"},
                    {"id": "charities", "header": "Charities"},
                    {"id": "grants", "header": "Grants"},
                    {"id": "officers", "header": "Officers"},
                ],
                "rows": rows,
            }
        )

    # Phone stacks (classic breakout: one row per phone × active/inactive counts)
    # Built before the flat carrier list so analysts see shared-phone shells first.
    phone_stack_rows: list[dict] = []
    if phone_groups:
        for phone, carriers in phone_groups:
            active = [d for d in carriers if d.get("status_code") == "A"]
            inactive = [d for d in carriers if d.get("status_code") != "A"]
            act_pu = sum(int(d.get("power_units") or 0) for d in active)
            ina_pu = sum(int(d.get("power_units") or 0) for d in inactive)
            n = len(carriers)
            ia_pct = round(100.0 * len(inactive) / n, 1) if n else 0.0
            ph_disp = phone if phone and phone != "No Phone" else "—"
            names: list[str] = []
            for d in sorted(
                carriers,
                key=lambda x: (
                    0 if x.get("status_code") == "A" else 1,
                    -(x.get("power_units") or 0),
                ),
            ):
                nm = (d.get("legal_name") or d.get("dba_name") or "").strip()
                if nm and nm not in names:
                    names.append(nm)
                if len(names) >= 4:
                    break
            sample = ", ".join(names)
            if len(names) >= 4 and n > 4:
                sample += f" … (+{n - len(names)} more)"
            # Clickable phone → filters the carriers table (see tanstack_table_assets)
            phone_html = (
                f'<button type="button" class="ts-filter-phone" '
                f'data-phone="{_esc(ph_disp)}" data-target="ts-carriers" '
                f'title="Filter carriers by this phone">{_esc(ph_disp)}</button>'
            )
            phone_stack_rows.append(
                {
                    "phone": ph_disp,
                    "phone_html": phone_html,
                    "carriers": n,
                    "active": len(active),
                    "inactive": len(inactive),
                    "active_pu": act_pu,
                    "inactive_pu": ina_pu,
                    "ia_pct": ia_pct,
                    "sample": sample,
                    # highlight shared phones and inactive-heavy stacks
                    "dot_heavy": n >= 5 or (n >= 3 and ia_pct >= 40),
                }
            )
        if phone_stack_rows:
            phone_stack_rows.sort(
                key=lambda r: (int(r["carriers"]), int(r["inactive_pu"]), int(r["active_pu"])),
                reverse=True,
            )
            tables.append(
                {
                    "rootId": "ts-phone-groups",
                    "pageSize": 25,
                    "initialSort": [{"id": "carriers", "desc": True}],
                    "columns": [
                        {"id": "phone", "header": "Phone"},
                        {"id": "carriers", "header": "Carriers"},
                        {"id": "active", "header": "Active (A)"},
                        {"id": "inactive", "header": "Inactive (I)"},
                        {"id": "active_pu", "header": "Active PU"},
                        {"id": "inactive_pu", "header": "Inactive PU"},
                        {"id": "ia_pct", "header": "Inactive %"},
                        {"id": "sample", "header": "Sample legal names"},
                    ],
                    "rows": phone_stack_rows,
                }
            )

    # Flatten all DOT carriers from phone groups and/or address groups
    carriers_flat: list[dict] = []
    seen_dot: set[str] = set()
    if phone_groups:
        for phone, carriers in phone_groups:
            for r in carriers:
                dn = str(r.get("dot_number") or "")
                key = dn or f"{r.get('legal_name')}-{phone}"
                if key in seen_dot:
                    continue
                seen_dot.add(key)
                status = r.get("status_code") or ""
                pu = r.get("power_units")
                street = r.get("canonical_address") or ""
                ph_disp = phone if phone != "No Phone" else (r.get("phone") or "—")
                carriers_flat.append(
                    {
                        "dot": dn,
                        "dot_html": _dot_link_html(dn),
                        "name": r.get("legal_name") or r.get("dba_name") or "",
                        "phone": ph_disp,
                        "phone_html": (
                            f'<button type="button" class="ts-filter-phone" '
                            f'data-phone="{_esc(ph_disp)}" data-target="ts-carriers" '
                            f'title="Filter to this phone">{_esc(ph_disp)}</button>'
                        ),
                        "status": status or "—",
                        "power_units": pu if pu is not None else None,
                        "address": street,
                        "address_html": linkify_zip_codes(street),
                        "dot_heavy": status == "I",
                    }
                )
    if address_groups and not carriers_flat:
        for ag in address_groups:
            for r in ag.get("carriers") or []:
                dn = str(r.get("dot_number") or "")
                key = dn or str(r.get("legal_name"))
                if key in seen_dot:
                    continue
                seen_dot.add(key)
                status = r.get("status_code") or ""
                pu = r.get("power_units")
                street = ag.get("canonical_address") or r.get("canonical_address") or ""
                ph_disp = r.get("phone") or "—"
                carriers_flat.append(
                    {
                        "dot": dn,
                        "dot_html": _dot_link_html(dn),
                        "name": r.get("legal_name") or r.get("dba_name") or "",
                        "phone": ph_disp,
                        "phone_html": (
                            f'<button type="button" class="ts-filter-phone" '
                            f'data-phone="{_esc(ph_disp)}" data-target="ts-carriers" '
                            f'title="Filter to this phone">{_esc(ph_disp)}</button>'
                            if ph_disp and ph_disp != "—"
                            else _esc(ph_disp)
                        ),
                        "status": status or "—",
                        "power_units": pu if pu is not None else None,
                        "address": street,
                        "address_html": linkify_zip_codes(street),
                        "dot_heavy": status == "I",
                    }
                )
    if carriers_flat:
        pu_vals = [
            float(r["power_units"])
            for r in carriers_flat
            if r.get("power_units") is not None
        ]
        pu_scale = MetricScale.from_values(pu_vals)
        vmax = pu_scale.vmax
        for r in carriers_flat:
            pu = float(r["power_units"]) if r.get("power_units") is not None else 0.0
            r["power_units_html"] = rank_dot_html(
                pu, vmax, scale=pu_scale, label="power units"
            ) + (
                _esc(f"{int(pu):,}") if r.get("power_units") is not None else "—"
            )
            r["percentile"] = pu_scale.percentile(pu)
        # Default: group by phone, active first, then power units (classic stack view)
        tables.append(
            {
                "rootId": "ts-carriers",
                "pageSize": 50,
                "initialSort": [
                    {"id": "phone", "desc": False},
                    {"id": "status", "desc": False},
                    {"id": "power_units", "desc": True},
                ],
                "columns": [
                    {"id": "dot", "header": "DOT#"},
                    {"id": "name", "header": "Legal name"},
                    {"id": "phone", "header": "Phone"},
                    {"id": "status", "header": "Status"},
                    {"id": "power_units", "header": "● Power units"},
                    {"id": "address", "header": "Street"},  # uses address_html when set
                ],
                "rows": carriers_flat,
            }
        )

    if entities:
        rows = []
        for r in entities:
            street = r.get("canonical_address") or ""
            name = r.get("name") or "—"
            detail_href = (r.get("detail_href") or "").strip()
            name_html = (
                f'<a href="{_esc(detail_href)}">{_esc(name)}</a>'
                if detail_href
                else _esc(name)
            )
            row = {
                "name": name,
                "name_html": name_html,
                "detail": r.get("detail") or r.get("id") or "—",
                "amount": float(r.get("amount") or 0) if r.get("amount") is not None else None,
                "amount_display": r.get("amount_fmt") or "—",
                "amount_html": _esc(r.get("amount_fmt") or "—"),
                "address_type": r.get("address_type") or "",
                "street": street,
                "street_html": linkify_zip_codes(street),
            }
            # sort amount by numeric; display via amount_html when we map column amount
            if focus == "medicare":
                from provider_pages import format_hcpcs_label  # noqa: WPS433

                row["hcpcs_types"] = int(r.get("hcpcs_type_count") or 0)
                row["claims"] = int(r.get("total_claims") or 0)
                npi = str(r.get("id") or "").strip()
                if npi and detail_href:
                    row["detail"] = r.get("detail") or f"NPI {npi}"
                    row["detail_html"] = (
                        f'<a href="{_esc(detail_href)}">{_esc(row["detail"])}</a>'
                    )
                # Prefer human labels: "Therapeutic activities (97530) $2.97M"
                hlist = r.get("hcpcs") or []
                bits = []
                for h in hlist[:8]:
                    label = (
                        h.get("hcpcs_label")
                        or format_hcpcs_label(h.get("hcpcs_code"))
                        or h.get("hcpcs_code")
                        or "—"
                    )
                    paid = (h.get("paid_fmt") or "").strip()
                    bits.append(f"{label} {paid}".strip())
                row["hcpcs_summary"] = ", ".join(bits)
                top_lab = r.get("top_hcpcs_label") or format_hcpcs_label(
                    r.get("top_hcpcs_code")
                )
                row["top_service"] = top_lab if top_lab and top_lab != "—" else "—"
            rows.append(row)
        cols = [
            {"id": "name", "header": "Name"},
            {"id": "detail", "header": "Detail"},
            {"id": "amount", "header": "Amount"},
        ]
        if focus == "medicare":
            cols.extend(
                [
                    {"id": "hcpcs_types", "header": "Code types"},
                    {"id": "claims", "header": "Claims"},
                    {"id": "top_service", "header": "Top service"},
                    {"id": "hcpcs_summary", "header": "Top services ($)"},
                ]
            )
        cols.extend(
            [
                {"id": "address_type", "header": "Type"},
                {"id": "street", "header": "Street"},
            ]
        )
        amt_scale = MetricScale.from_values(
            float(r["amount"]) for r in rows if r.get("amount") is not None
        )
        vmax = amt_scale.vmax
        for row in rows:
            amt = float(row["amount"]) if row.get("amount") is not None else 0.0
            disp = row.get("amount_display") or "—"
            row["amount_html"] = rank_dot_html(
                amt, vmax, scale=amt_scale, label="amount"
            ) + _esc(str(disp))
            row["percentile"] = amt_scale.percentile(amt)
        tables.append(
            {
                "rootId": "ts-entities",
                "pageSize": 25,
                "initialSort": [{"id": "amount", "desc": True}],
                "columns": cols,
                "rows": rows,
            }
        )

    if charities:
        rows = []
        for r in charities:
            grift = r.get("grift_ratio")
            rows.append(
                {
                    "ein": r.get("ein") or "",
                    "name": r.get("filer_name") or "",
                    "year": r.get("tax_year") or "",
                    "receipts": r.get("receipt_fmt") or "—",
                    "receipts_num": float(r.get("receipt_amt") or 0)
                    if r.get("receipt_amt") is not None
                    else None,
                    "grift": f"{grift:.1f}" if grift is not None else "—",
                    "grift_num": float(grift) if grift is not None else None,
                    "misrep": "yes" if r.get("misrep") else "",
                    "dot_heavy": bool(r.get("misrep")) or (grift or 0) > 5,
                }
            )
        tables.append(
            {
                "rootId": "ts-charities",
                "pageSize": 25,
                "initialSort": [{"id": "grift_num", "desc": True}],
                "columns": [
                    {"id": "ein", "header": "EIN"},
                    {"id": "name", "header": "Name"},
                    {"id": "year", "header": "Year"},
                    {"id": "receipts", "header": "Receipts"},
                    {"id": "grift", "header": "Grift"},
                    {"id": "misrep", "header": "Misrep"},
                ],
                "rows": rows,
            }
        )

    if officers:
        rows = []
        for r in officers:
            rows.append(
                {
                    "name": r.get("display_name") or "",
                    "comp": r.get("comp_fmt") or "—",
                    "comp_num": float(r.get("compensation") or 0)
                    if r.get("compensation") is not None
                    else None,
                    "year": r.get("tax_year") or "",
                }
            )
        tables.append(
            {
                "rootId": "ts-officers",
                "pageSize": 25,
                "initialSort": [{"id": "comp_num", "desc": True}],
                "columns": [
                    {"id": "name", "header": "Name"},
                    {"id": "comp", "header": "Compensation"},
                    {"id": "year", "header": "Year"},
                ],
                "rows": rows,
            }
        )

    if grants:
        rows = []
        for r in grants:
            rows.append(
                {
                    "filer_ein": r.get("filer_ein") or "",
                    "grantee": r.get("grantee_name") or "",
                    "amount": r.get("amt_fmt") or "—",
                    "amount_num": float(r.get("grant_amt") or 0)
                    if r.get("grant_amt") is not None
                    else None,
                    "year": r.get("tax_year") or "",
                }
            )
        tables.append(
            {
                "rootId": "ts-grants",
                "pageSize": 25,
                "initialSort": [{"id": "amount_num", "desc": True}],
                "columns": [
                    {"id": "filer_ein", "header": "Filer EIN"},
                    {"id": "grantee", "header": "Grantee"},
                    {"id": "amount", "header": "Amount"},
                    {"id": "year", "header": "Year"},
                ],
                "rows": rows,
            }
        )

    return tables
