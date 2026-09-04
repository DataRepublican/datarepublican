#!/usr/bin/env python3
"""Medicare / NPPES provider detail pages (static HTML under reports/providers/).

Each NPI gets a dossier: identity, rollup $, HCPCS codes, practice/mail addresses
with Google Maps, plus Google and Grok search links.

Usage:
  python provider_pages.py --npi 1750942355
  python provider_pages.py --min-paid 50000 --limit 2000
  python provider_pages.py --npis-file npis.txt

From focus medicare report generation, call write_provider_page() per cluster NPI.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_address_reports import CSS, fmt_money, google_maps_url  # noqa: E402
from generate_focus_reports import ensure_medicare_rollup  # noqa: E402

DEFAULT_DB = os.environ.get("IRS990_DB_PATH", "/Volumes/Data/final/irs990.duckdb")
DEFAULT_PROVIDERS_DIR = SCRIPT_DIR / "reports" / "providers"

# Fallback labels for high-volume CPT/HCPCS missing from incomplete hcpcs_codes loads.
_COMMON_HCPCS_LABELS: dict[str, str] = {
    "97110": "Therapeutic exercises",
    "97112": "Neuromuscular reeducation",
    "97116": "Gait training therapy",
    "97140": "Manual therapy",
    "97161": "PT evaluation low complex",
    "97162": "PT evaluation mod complex",
    "97163": "PT evaluation high complex",
    "97164": "PT re-evaluation",
    "97165": "OT evaluation low complex",
    "97166": "OT evaluation mod complex",
    "97167": "OT evaluation high complex",
    "97168": "OT re-evaluation",
    "97530": "Therapeutic activities",
    "97535": "Self-care management training",
    "97542": "Wheelchair management training",
    "97750": "Physical performance test",
    "97760": "Orthotic management initial",
    "97761": "Prosthetic training initial",
    "99202": "Office/outpatient visit new",
    "99203": "Office/outpatient visit new",
    "99204": "Office/outpatient visit new",
    "99205": "Office/outpatient visit new",
    "99211": "Office/outpatient visit est",
    "99212": "Office/outpatient visit est",
    "99213": "Office/outpatient visit est",
    "99214": "Office/outpatient visit est",
    "99215": "Office/outpatient visit est",
    "99232": "Subsequent hospital care",
    "99233": "Subsequent hospital care",
    "99308": "Subsequent nursing facility care",
    "T1019": "Personal care services, per 15 min",
    "H0044": "Supported housing, per month",
    "G0299": "Direct skilled nursing RN",
    "G0300": "Direct skilled nursing LPN",
}

_hcpcs_label_cache: dict[str, str] | None = None


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def load_hcpcs_labels(conn: duckdb.DuckDBPyConnection | None = None) -> dict[str, str]:
    """code → short description (from DB + optional sidecar + common CPT fallbacks)."""
    global _hcpcs_label_cache
    if _hcpcs_label_cache is not None:
        return _hcpcs_label_cache
    labels = dict(_COMMON_HCPCS_LABELS)

    def _ingest_from_relation(rel_sql: str, c: duckdb.DuckDBPyConnection) -> int:
        n = 0
        try:
            for code, desc, long_d in c.execute(
                f"""
                SELECT code,
                       NULLIF(TRIM(description), ''),
                       NULLIF(TRIM(long_description), '')
                FROM {rel_sql}
                """
            ).fetchall():
                key = str(code or "").strip().upper()
                if not key:
                    continue
                text = desc or long_d
                if text:
                    labels[key] = str(text).strip()
                    n += 1
        except Exception:
            return 0
        return n

    if conn is not None:
        _ingest_from_relation("hcpcs_codes", conn)
        # Sidecar written when main DB was locked during CMS load
        side = os.environ.get(
            "HCPCS_CODES_DB",
            "/Volumes/Data/final/hcpcs_codes.duckdb",
        )
        if os.path.exists(side):
            try:
                try:
                    conn.execute("DETACH hcpcs_side")
                except Exception:
                    pass
                conn.execute(f"ATTACH '{side}' AS hcpcs_side (READ_ONLY)")
                _ingest_from_relation("hcpcs_side.hcpcs_codes", conn)
            except Exception:
                pass
    _hcpcs_label_cache = labels
    return labels


def format_hcpcs_label(code: Any, labels: dict[str, str] | None = None) -> str:
    """Human label with code in parentheses, e.g. 'Therapeutic activities (97530)'."""
    c = str(code or "").strip()
    if not c or c == "—":
        return "—"
    key = c.upper()
    desc = None
    if labels is not None:
        desc = labels.get(key) or labels.get(c)
    else:
        desc = _COMMON_HCPCS_LABELS.get(key)
    if not desc:
        return c
    # Avoid "Foo (97530) (97530)" if description already ends with the code
    if desc.rstrip().endswith(f"({c})") or desc.rstrip().endswith(f"({key})"):
        return desc
    return f"{desc} ({c})"


def normalize_npi(npi: Any) -> str:
    d = re.sub(r"\D", "", str(npi or ""))
    return d if len(d) == 10 else ""


def provider_detail_href(npi: str, *, relative: str = "../providers") -> str:
    """Relative link from a cluster detail page to the NPI dossier."""
    n = normalize_npi(npi)
    if not n:
        return ""
    return f"{relative.rstrip('/')}/{n}.html"


def provider_link_html(
    npi: Any,
    label: Any = None,
    *,
    relative: str = "../providers",
) -> str:
    n = normalize_npi(npi)
    text = _esc(label if label is not None else n or "—")
    if not n:
        return text
    href = provider_detail_href(n, relative=relative)
    return f'<a href="{_esc(href)}">{text}</a>'


def google_search_url(*parts: Any) -> str:
    q = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return f"https://www.google.com/search?q={quote_plus(q)}" if q else "https://www.google.com/"


def grok_search_url(*parts: Any) -> str:
    """Best-effort deep link into Grok with a prefilled query."""
    q = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    if not q:
        return "https://grok.com/"
    # grok.com accepts q= on the public web UI; falls back gracefully if ignored.
    return f"https://grok.com/?q={quote_plus(q)}"


def fetch_provider_dossier(
    conn: duckdb.DuckDBPyConnection,
    npi: str,
    *,
    line_grain: bool = False,
) -> dict[str, Any] | None:
    """Load provider dossier from main DB (+ rollup/hcpcs if available).

    ``line_grain`` hits ``medicare_provider_spending`` (~230M rows) for
    billing/servicing roles. Skip it for bulk page generation — rollup +
    HCPCS tables are enough for a complete dossier without 404s.
    """
    npi = normalize_npi(npi)
    if not npi:
        return None

    has_rollup = ensure_medicare_rollup(conn)
    hcpcs_labels = load_hcpcs_labels(conn)

    prov = conn.execute(
        """
        SELECT id, npi, entity_type_code, ein, organization_name,
               provider_last_name, provider_first_name, provider_middle_name,
               provider_credential, enumeration_date, last_update_date, is_sole_proprietor
        FROM medicare_providers
        WHERE npi = ?
        """,
        [npi],
    ).fetchone()
    if not prov:
        return None

    (
        pid,
        _npi,
        etc,
        ein,
        org,
        last,
        first,
        middle,
        cred,
        enum_dt,
        upd_dt,
        sole,
    ) = prov

    person = " ".join(x for x in (first or "", middle or "", last or "") if x).strip()
    display = (org or "").strip() or person or npi
    entity_label = {
        "1": "Individual",
        "2": "Organization",
    }.get(str(etc or ""), str(etc or "—"))

    rollup: dict[str, Any] = {}
    if has_rollup:
        r = conn.execute(
            """
            SELECT total_paid, total_claims, total_beneficiaries, hcpcs_type_count,
                   spend_rows, first_month, last_month, top_hcpcs_code, top_hcpcs_paid,
                   organization_name, person_name
            FROM medicare_provider_rollup
            WHERE npi = ?
            """,
            [npi],
        ).fetchone()
        if r:
            rollup = {
                "total_paid": float(r[0] or 0),
                "total_claims": int(r[1] or 0),
                "total_beneficiaries": int(r[2] or 0),
                "hcpcs_type_count": int(r[3] or 0),
                "spend_rows": int(r[4] or 0),
                "first_month": r[5],
                "last_month": r[6],
                "top_hcpcs_code": r[7],
                "top_hcpcs_paid": float(r[8] or 0),
                "rollup_org": r[9],
                "rollup_person": r[10],
            }

    hcpcs: list[dict[str, Any]] = []
    if has_rollup:
        try:
            for code, claims, paid, bens, first_m, last_m in conn.execute(
                """
                SELECT hcpcs_code, total_claims, total_paid, total_beneficiaries,
                       first_month, last_month
                FROM medicare_provider_hcpcs
                WHERE npi = ?
                ORDER BY total_paid DESC NULLS LAST, total_claims DESC NULLS LAST
                """,
                [npi],
            ).fetchall():
                raw = code or "—"
                hcpcs.append(
                    {
                        "hcpcs_code": raw,
                        "hcpcs_label": format_hcpcs_label(raw, hcpcs_labels),
                        "claims": int(claims or 0),
                        "paid": float(paid or 0),
                        "paid_fmt": fmt_money(paid),
                        "beneficiaries": int(bens or 0),
                        "first_month": first_m,
                        "last_month": last_m,
                    }
                )
        except Exception:
            pass

    # Billing vs servicing role — optional; line grain is ~230M rows.
    roles: list[dict[str, Any]] = []
    as_servicing: list[dict[str, Any]] = []
    if line_grain:
        try:
            roles = [
                {
                    "role": row[0],
                    "rows": int(row[1] or 0),
                    "claims": int(row[2] or 0),
                    "paid": float(row[3] or 0),
                    "paid_fmt": fmt_money(row[3]),
                    "first_month": row[4],
                    "last_month": row[5],
                }
                for row in conn.execute(
                    """
                    SELECT
                      CASE WHEN billing_provider_npi = ? THEN 'billing'
                           ELSE 'servicing' END AS npi_role,
                      count(*)::BIGINT,
                      coalesce(sum(total_claims), 0)::BIGINT,
                      coalesce(sum(total_paid), 0)::DOUBLE,
                      min(claim_from_month),
                      max(claim_from_month)
                    FROM medicare_provider_spending
                    WHERE billing_provider_npi = ? OR servicing_provider_npi = ?
                    GROUP BY 1
                    ORDER BY 1
                    """,
                    [npi, npi, npi],
                ).fetchall()
            ]
            as_servicing = [
                {
                    "billing_npi": bn,
                    "billing_name": bname,
                    "hcpcs_code": code,
                    "hcpcs_label": format_hcpcs_label(code, hcpcs_labels),
                    "claims": int(claims or 0),
                    "paid": float(paid or 0),
                    "paid_fmt": fmt_money(paid),
                    "first_month": fm,
                    "last_month": lm,
                }
                for bn, bname, code, claims, paid, fm, lm in conn.execute(
                    """
                    SELECT billing_provider_npi, billing_provider_name, hcpcs_code,
                           sum(total_claims)::BIGINT, sum(total_paid)::DOUBLE,
                           min(claim_from_month), max(claim_from_month)
                    FROM medicare_provider_spending
                    WHERE servicing_provider_npi = ?
                      AND (billing_provider_npi IS NULL OR billing_provider_npi != ?)
                    GROUP BY 1, 2, 3
                    ORDER BY sum(total_paid) DESC NULLS LAST
                    LIMIT 25
                    """,
                    [npi, npi],
                ).fetchall()
            ]
        except Exception:
            pass

    addresses: list[dict[str, Any]] = []
    try:
        for at, line1, line2, city, state, zipc, canon, colo, lat, lon in conn.execute(
            """
            SELECT address_type, address_line1, address_line2, city, state, zip_code,
                   canonical_address, colocator, latitude, longitude
            FROM Addresses
            WHERE owner_id = ?
            ORDER BY address_type, canonical_address
            """,
            [pid],
        ).fetchall():
            addr = (canon or "").strip()
            addresses.append(
                {
                    "address_type": at,
                    "address_line1": line1,
                    "address_line2": line2,
                    "city": city,
                    "state": state,
                    "zip_code": zipc,
                    "canonical_address": addr or "—",
                    "colocator": colo,
                    "latitude": lat,
                    "longitude": lon,
                    "maps_url": google_maps_url(addr, zoom=17) if addr else "",
                }
            )
    except Exception:
        pass

    paid = float(rollup.get("total_paid") or 0)
    search_bits = [display, f"NPI {npi}"]
    if cred:
        search_bits.append(str(cred))
    # Prefer practice location for search context (not mailing HQ)
    loc_src = next(
        (a for a in addresses if a.get("address_type") == "nppes_practice"),
        addresses[0] if addresses else None,
    )
    if loc_src:
        if loc_src.get("city"):
            search_bits.append(str(loc_src["city"]))
        if loc_src.get("state"):
            search_bits.append(str(loc_src["state"]))

    return {
        "npi": npi,
        "provider_id": str(pid),
        "display_name": display,
        "organization_name": (org or "").strip() or None,
        "person_name": person or None,
        "entity_type_code": etc,
        "entity_type_label": entity_label,
        "credential": (cred or "").strip() or None,
        "ein": None if not ein or str(ein).startswith("<") else str(ein),
        "enumeration_date": str(enum_dt)[:10] if enum_dt else None,
        "last_update_date": str(upd_dt)[:10] if upd_dt else None,
        "is_sole_proprietor": sole,
        "rollup": rollup,
        "total_paid": paid,
        "total_paid_fmt": fmt_money(paid) if paid else "—",
        "total_claims": int(rollup.get("total_claims") or 0),
        "total_beneficiaries": int(rollup.get("total_beneficiaries") or 0),
        "hcpcs_type_count": int(rollup.get("hcpcs_type_count") or len(hcpcs)),
        "first_month": rollup.get("first_month"),
        "last_month": rollup.get("last_month"),
        "top_hcpcs_code": rollup.get("top_hcpcs_code"),
        "top_hcpcs_label": format_hcpcs_label(
            rollup.get("top_hcpcs_code"), hcpcs_labels
        ),
        "top_hcpcs_paid_fmt": fmt_money(rollup.get("top_hcpcs_paid"))
        if rollup.get("top_hcpcs_paid")
        else "—",
        "hcpcs": hcpcs,
        "roles": roles,
        "as_servicing": as_servicing,
        "addresses": addresses,
        "google_search_url": google_search_url(*search_bits),
        "grok_search_url": grok_search_url(*search_bits),
        "nppes_registry_url": (
            f"https://npiregistry.cms.hhs.gov/provider-view/{npi}"
        ),
    }


def build_provider_tables(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    """TanStack table configs for provider detail (addresses, roles, HCPCS, servicing)."""
    from cluster_table_payload import rank_dot_html  # noqa: WPS433

    tables: list[dict[str, Any]] = []

    addr_rows = []
    for a in dossier.get("addresses") or []:
        street = a.get("canonical_address") or "—"
        maps = a.get("maps_url") or ""
        street_html = (
            f'<a href="{_esc(maps)}" target="_blank" rel="noopener">{_esc(street)}</a>'
            if maps
            else _esc(street)
        )
        addr_rows.append(
            {
                "type": a.get("address_type") or "—",
                "street": street,
                "street_html": street_html,
                "city": a.get("city") or "",
                "state": a.get("state") or "",
                "zip": a.get("zip_code") or "",
                "colocator": a.get("colocator") or "—",
            }
        )
    tables.append(
        {
            "rootId": "ts-addresses",
            "pageSize": 25,
            "initialSort": [{"id": "type", "desc": False}],
            "columns": [
                {"id": "type", "header": "Type"},
                {"id": "street", "header": "Address (Maps)"},
                {"id": "city", "header": "City"},
                {"id": "state", "header": "ST"},
                {"id": "zip", "header": "ZIP"},
                {"id": "colocator", "header": "Colocator"},
            ],
            "rows": addr_rows,
        }
    )

    role_rows = []
    for r in dossier.get("roles") or []:
        paid = float(r.get("paid") or 0)
        role_rows.append(
            {
                "role": r.get("role") or "—",
                "rows": int(r.get("rows") or 0),
                "claims": int(r.get("claims") or 0),
                "paid": paid,
                "paid_display": r.get("paid_fmt") or "—",
                "window": f"{r.get('first_month') or '—'} → {r.get('last_month') or '—'}",
            }
        )
    vmax_role = max((float(r["paid"]) for r in role_rows), default=0.0)
    for r in role_rows:
        r["paid_html"] = rank_dot_html(float(r["paid"]), vmax_role) + _esc(
            str(r.get("paid_display") or "—")
        )
    tables.append(
        {
            "rootId": "ts-roles",
            "pageSize": 10,
            "initialSort": [{"id": "paid", "desc": True}],
            "columns": [
                {"id": "role", "header": "Role"},
                {"id": "rows", "header": "Spend rows"},
                {"id": "claims", "header": "Claims"},
                {"id": "paid", "header": "Paid"},
                {"id": "window", "header": "Window"},
            ],
            "rows": role_rows,
        }
    )

    serv_rows = []
    for s in dossier.get("as_servicing") or []:
        paid = float(s.get("paid") or 0)
        label = s.get("hcpcs_label") or s.get("hcpcs_code") or "—"
        serv_rows.append(
            {
                "billing_npi": s.get("billing_npi") or "—",
                "billing_name": s.get("billing_name") or "—",
                "service": label,
                "hcpcs_code": s.get("hcpcs_code") or "—",
                "claims": int(s.get("claims") or 0),
                "paid": paid,
                "paid_display": s.get("paid_fmt") or "—",
                "window": f"{s.get('first_month') or '—'} → {s.get('last_month') or '—'}",
            }
        )
    vmax_s = max((float(r["paid"]) for r in serv_rows), default=0.0)
    for r in serv_rows:
        r["paid_html"] = rank_dot_html(float(r["paid"]), vmax_s) + _esc(
            str(r.get("paid_display") or "—")
        )
    if serv_rows:
        tables.append(
            {
                "rootId": "ts-servicing",
                "pageSize": 25,
                "initialSort": [{"id": "paid", "desc": True}],
                "columns": [
                    {"id": "billing_npi", "header": "Billing NPI"},
                    {"id": "billing_name", "header": "Billing name"},
                    {"id": "service", "header": "Service"},
                    {"id": "claims", "header": "Claims"},
                    {"id": "paid", "header": "Paid"},
                    {"id": "window", "header": "Window"},
                ],
                "rows": serv_rows,
            }
        )

    hcpcs_rows = []
    for h in dossier.get("hcpcs") or []:
        paid = float(h.get("paid") or 0)
        label = h.get("hcpcs_label") or h.get("hcpcs_code") or "—"
        hcpcs_rows.append(
            {
                "service": label,
                "hcpcs_code": h.get("hcpcs_code") or "—",
                "claims": int(h.get("claims") or 0),
                "beneficiaries": int(h.get("beneficiaries") or 0),
                "paid": paid,
                "paid_display": h.get("paid_fmt") or "—",
                "first": h.get("first_month") or "—",
                "last": h.get("last_month") or "—",
            }
        )
    vmax_h = max((float(r["paid"]) for r in hcpcs_rows), default=0.0)
    for r in hcpcs_rows:
        r["paid_html"] = rank_dot_html(float(r["paid"]), vmax_h) + _esc(
            str(r.get("paid_display") or "—")
        )
    tables.append(
        {
            "rootId": "ts-hcpcs",
            "pageSize": 50,
            "initialSort": [{"id": "paid", "desc": True}],
            "columns": [
                {"id": "service", "header": "Service"},
                {"id": "claims", "header": "Claims"},
                {"id": "beneficiaries", "header": "Benes"},
                {"id": "paid", "header": "Paid"},
                {"id": "first", "header": "First"},
                {"id": "last", "header": "Last"},
            ],
            "rows": hcpcs_rows,
        }
    )
    return tables


def render_provider_page(dossier: dict[str, Any], *, generated_at: str) -> str:
    from cluster_table_payload import dumps_table_json  # noqa: WPS433
    from mako.lookup import TemplateLookup

    tables = build_provider_tables(dossier)
    lookup = TemplateLookup(
        directories=[str(SCRIPT_DIR / "templates")],
        input_encoding="utf-8",
    )
    tpl = lookup.get_template("provider_detail.mako")
    return tpl.render(
        css=CSS,
        dossier=dossier,
        generated_at=generated_at,
        detail_tables_json=dumps_table_json(tables),
    )


def write_provider_page(
    conn: duckdb.DuckDBPyConnection,
    npi: str,
    providers_dir: Path,
    *,
    generated_at: str | None = None,
    write_json: bool = True,
    line_grain: bool = False,
) -> Path | None:
    """Fetch dossier and write HTML (+ optional JSON). Returns path or None."""
    dossier = fetch_provider_dossier(conn, npi, line_grain=line_grain)
    if not dossier:
        return None
    providers_dir = Path(providers_dir)
    providers_dir.mkdir(parents=True, exist_ok=True)
    gen = generated_at or datetime.now().isoformat(timespec="seconds")
    html_out = render_provider_page(dossier, generated_at=gen)
    out = providers_dir / f"{dossier['npi']}.html"
    out.write_text(html_out, encoding="utf-8")
    if write_json:
        data_dir = providers_dir / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / f"{dossier['npi']}.json").write_text(
            json.dumps(dossier, indent=2, default=str),
            encoding="utf-8",
        )
    return out


def write_provider_index(providers_dir: Path, dossiers: list[dict[str, Any]], *, generated_at: str) -> None:
    """Simple index of generated provider pages sorted by paid desc."""
    rows = sorted(dossiers, key=lambda d: float(d.get("total_paid") or 0), reverse=True)
    body = "".join(
        f"<tr>"
        f'<td><a href="{_esc(d["npi"])}.html"><code>{_esc(d["npi"])}</code></a></td>'
        f'<td><a href="{_esc(d["npi"])}.html">{_esc(d.get("display_name"))}</a></td>'
        f'<td class="num">{_esc(d.get("total_paid_fmt") or "—")}</td>'
        f'<td class="num">{int(d.get("hcpcs_type_count") or 0):,}</td>'
        f'<td class="num">{int(d.get("total_claims") or 0):,}</td>'
        f"</tr>"
        for d in rows
    )
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Medicare providers</title>
<style>{CSS}
td.num, th.num {{ text-align: right; }}
</style></head><body>
<header>
  <h1>Medicare / NPPES provider dossiers</h1>
  <p class="meta">{len(rows):,} pages · { _esc(generated_at) }</p>
</header>
<table>
<thead><tr><th>NPI</th><th>Name</th><th class="num">Paid</th><th class="num">HCPCS types</th><th class="num">Claims</th></tr></thead>
<tbody>{body or '<tr><td colspan="5">No providers.</td></tr>'}</tbody>
</table>
<footer><p><a href="../master_index.html">← Master index</a></p></footer>
</body></html>"""
    providers_dir.mkdir(parents=True, exist_ok=True)
    (providers_dir / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", default=DEFAULT_DB)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROVIDERS_DIR)
    p.add_argument("--npi", action="append", default=[], help="NPI(s) to generate (repeatable)")
    p.add_argument("--npis-file", type=Path, help="File with one NPI per line")
    p.add_argument("--min-paid", type=float, default=None, help="Generate top NPIs with rollup paid ≥ this")
    p.add_argument("--limit", type=int, default=2000, help="Max NPIs when using --min-paid")
    p.add_argument("--no-json", action="store_true")
    p.add_argument("--no-index", action="store_true", help="Do not rewrite providers/index.html")
    args = p.parse_args()

    npis: list[str] = []
    for n in args.npi:
        nn = normalize_npi(n)
        if nn:
            npis.append(nn)
    if args.npis_file and args.npis_file.is_file():
        for line in args.npis_file.read_text(encoding="utf-8").splitlines():
            nn = normalize_npi(line.split("#")[0].strip())
            if nn:
                npis.append(nn)

    conn = duckdb.connect(args.db_path, read_only=True)
    generated_at = datetime.now().isoformat(timespec="seconds")
    dossiers: list[dict[str, Any]] = []

    try:
        if args.min_paid is not None:
            ensure_medicare_rollup(conn)
            rows = conn.execute(
                """
                SELECT npi FROM medicare_provider_rollup
                WHERE coalesce(total_paid, 0) >= ?
                ORDER BY total_paid DESC NULLS LAST
                LIMIT ?
                """,
                [args.min_paid, args.limit],
            ).fetchall()
            npis.extend(str(r[0]) for r in rows if r[0])

        # de-dupe preserve order
        seen: set[str] = set()
        ordered: list[str] = []
        for n in npis:
            if n not in seen:
                seen.add(n)
                ordered.append(n)

        if not ordered:
            print("No NPIs specified. Use --npi, --npis-file, or --min-paid.", flush=True)
            return 1

        print(f"Writing {len(ordered)} provider pages → {args.output_dir}", flush=True)
        ok = 0
        for i, npi in enumerate(ordered, 1):
            path = write_provider_page(
                conn,
                npi,
                args.output_dir,
                generated_at=generated_at,
                write_json=not args.no_json,
                line_grain=False,
            )
            if path:
                ok += 1
                if not args.no_index:
                    d = fetch_provider_dossier(conn, npi, line_grain=False)
                    if d:
                        dossiers.append(d)
            if i == 1 or i % 100 == 0 or i == len(ordered):
                print(f"  {i}/{len(ordered)} (ok={ok})", flush=True)
        if not args.no_index:
            write_provider_index(args.output_dir, dossiers, generated_at=generated_at)
        print(f"Done. {ok} pages → {args.output_dir}", flush=True)
        return 0 if ok else 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
