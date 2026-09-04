#!/usr/bin/env python3
"""Build Leaflet-friendly map features from cluster keys.

Resolves:
  LL:lat:lon           — tight colocator point
  LL:lat:lon (loose)   — 0.5° grid cell: center + min/max bounds rectangle
  5-digit zip          — zip centroid
  PO:box:zip           — PO Box colocator → zip centroid
  sample_address zip   — trailing ZIP fallback
"""

from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# Grid step used by generate_address_reports loose_colocator SQL (ROUND(x/0.5)*0.5)
LOOSE_STEP = 0.5

_LL_RE = re.compile(
    r"^LL:\s*([+-]?\d+(?:\.\d+)?)\s*:\s*([+-]?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
# PO:<box>:<zip5>  (zip is the last colon field)
_PO_RE = re.compile(r"^PO:\s*[^:]+:\s*(\d{5})\s*$", re.IGNORECASE)
# Bare zip cluster key ONLY — entire key is ZIP5 or ZIP+4.
# Do NOT use ^(\d{5})\b: street addresses like "32405 Diagonal Rd…, 97838"
# would wrongly take the house number as a Florida (etc.) zip centroid.
_ZIP_ONLY_RE = re.compile(r"^(\d{5})(?:-\d{4})?\s*$")
_ZIP_TRAIL_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")


def parse_ll(key: str | None) -> tuple[float, float] | None:
    if not key:
        return None
    m = _LL_RE.match(str(key).strip())
    if not m:
        return None
    try:
        lat, lon = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:
        return None
    return lat, lon


def parse_zip5(key: str | None) -> str | None:
    """Return ZIP5 only when *key* is a bare zip (or PO:box:zip), not a street address."""
    if not key:
        return None
    s = str(key).strip()
    m = _ZIP_ONLY_RE.match(s)
    if m:
        return m.group(1)
    m = _PO_RE.match(s)
    if m:
        return m.group(1)
    return None


def zip_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = _ZIP_TRAIL_RE.search(str(text).strip())
    return m.group(1) if m else None


def loose_cell_bounds(
    lat: float, lon: float, *, step: float = LOOSE_STEP
) -> dict[str, float]:
    """Bounds for a ROUND(x/step)*step grid cell (center ± step/2)."""
    half = step / 2.0
    return {
        "lat_min": lat - half,
        "lat_max": lat + half,
        "lon_min": lon - half,
        "lon_max": lon + half,
    }


@lru_cache(maxsize=1)
def load_zip_centroids(
    path: str | None = None,
) -> dict[str, tuple[float, float]]:
    """US_zips.txt.gz: tab-separated … zip … lat lon …"""
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.extend(
        [
            REPO_ROOT / "US_zips.txt.gz",
            Path("/Volumes/Data/final/US_zips.txt.gz"),
        ]
    )
    zpath = next((p for p in candidates if p.exists()), None)
    if not zpath:
        return {}
    out: dict[str, tuple[float, float]] = {}
    opener = gzip.open if zpath.suffix == ".gz" else open
    with opener(zpath, "rt", encoding="utf-8", errors="replace") as f:  # type: ignore[arg-type]
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 11:
                continue
            z = parts[1].strip()
            if len(z) != 5 or not z.isdigit():
                continue
            try:
                lat, lon = float(parts[9]), float(parts[10])
            except ValueError:
                continue
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                out[z] = (lat, lon)
    return out


def _valid_lat_lon(lat: float, lon: float) -> bool:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    if lat == 0 and lon == 0:
        return False
    return True


def resolve_geo(
    key: str | None,
    *,
    sample_address: str | None = None,
    slice_by: str | None = None,
    zip_centroids: dict[str, tuple[float, float]] | None = None,
    zip_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    colocator: str | None = None,
) -> dict[str, Any] | None:
    """Resolve geometry for a cluster.

    Preference order (structured Addresses fields first — no street parsing):
      1. latitude / longitude columns
      2. colocator when it is an LL:lat:lon token
      3. zip_code column → zip centroid
      4. cluster *key* when it is already LL: / bare ZIP / PO:box:zip
      5. trailing ZIP in sample_address (legacy fallback only)

    Returns dict with:
      kind: 'll' | 'loose' | 'zip' | 'po_zip'
      lat, lon: center
      bounds?: {lat_min, lat_max, lon_min, lon_max} for loose cells
      zip?: source zip when applicable
    """
    cents = zip_centroids if zip_centroids is not None else load_zip_centroids()
    raw = str(key or "").strip()
    sb = (slice_by or "").lower()

    # 1) Structured lat/lon from Addresses (or aggregated ANY_VALUE)
    if latitude is not None and longitude is not None:
        try:
            lat_f, lon_f = float(latitude), float(longitude)
        except (TypeError, ValueError):
            lat_f = lon_f = None  # type: ignore[assignment]
        if lat_f is not None and lon_f is not None and _valid_lat_lon(lat_f, lon_f):
            if sb in ("loose_colocator", "loose"):
                b = loose_cell_bounds(lat_f, lon_f)
                return {
                    "kind": "loose",
                    "lat": lat_f,
                    "lon": lon_f,
                    "bounds": b,
                }
            return {"kind": "ll", "lat": lat_f, "lon": lon_f}

    # 2) Structured colocator token (LL:… or PO:…)
    colo = str(colocator or "").strip()
    if colo:
        ll_c = parse_ll(colo)
        if ll_c:
            lat, lon = ll_c
            if sb in ("loose_colocator", "loose"):
                b = loose_cell_bounds(lat, lon)
                return {"kind": "loose", "lat": lat, "lon": lon, "bounds": b}
            return {"kind": "ll", "lat": lat, "lon": lon}
        po_c = _PO_RE.match(colo)
        if po_c:
            z = po_c.group(1)
            if z in cents:
                lat, lon = cents[z]
                return {"kind": "po_zip", "lat": lat, "lon": lon, "zip": z}

    # 3) Structured zip_code column (already ZIP5 from split_zip_code)
    z_col = parse_zip5(zip_code) if zip_code else None
    if z_col and z_col in cents:
        lat, lon = cents[z_col]
        return {"kind": "zip", "lat": lat, "lon": lon, "zip": z_col}

    # 4) Cluster key semantics (zipcode / colocator / loose slices)
    ll = parse_ll(raw)
    if ll:
        lat, lon = ll
        if sb in ("loose_colocator", "loose"):
            b = loose_cell_bounds(lat, lon)
            return {
                "kind": "loose",
                "lat": lat,
                "lon": lon,
                "bounds": b,
            }
        return {"kind": "ll", "lat": lat, "lon": lon}

    po = _PO_RE.match(raw)
    if po:
        z = po.group(1)
        if z in cents:
            lat, lon = cents[z]
            return {"kind": "po_zip", "lat": lat, "lon": lon, "zip": z}

    z = parse_zip5(raw)
    if z and z in cents:
        lat, lon = cents[z]
        return {"kind": "zip", "lat": lat, "lon": lon, "zip": z}

    # 5) Legacy: trailing ZIP in free-text sample only
    z2 = zip_from_text(sample_address)
    if z2 and z2 in cents:
        lat, lon = cents[z2]
        kind = "po_zip" if raw.upper().startswith("PO:") else "zip"
        return {"kind": kind, "lat": lat, "lon": lon, "zip": z2}

    return None


def point_from_cluster_key(
    key: str | None,
    *,
    slice_by: str | None = None,
    zip_centroids: dict[str, tuple[float, float]] | None = None,
    sample_address: str | None = None,
    zip_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    colocator: str | None = None,
) -> tuple[float, float] | None:
    g = resolve_geo(
        key,
        sample_address=sample_address,
        slice_by=slice_by,
        zip_centroids=zip_centroids,
        zip_code=zip_code,
        latitude=latitude,
        longitude=longitude,
        colocator=colocator,
    )
    if not g:
        return None
    return float(g["lat"]), float(g["lon"])


def clusters_to_map_points(
    clusters: list[dict[str, Any]],
    *,
    slice_by: str | None = None,
    max_points: int = 500,
) -> list[dict[str, Any]]:
    """Convert cluster dicts to Leaflet marker/rectangle payloads."""
    cents = load_zip_centroids()
    points: list[dict[str, Any]] = []
    for c in clusters:
        if len(points) >= max_points:
            break
        key = str(c.get("cluster_key") or c.get("canonical_address") or "")
        sample = c.get("sample_address") or ""
        geo = resolve_geo(
            key,
            sample_address=sample,
            slice_by=slice_by,
            zip_centroids=cents,
            zip_code=c.get("zip_code"),
            latitude=c.get("latitude"),
            longitude=c.get("longitude"),
            colocator=c.get("colocator"),
        )
        if not geo:
            continue
        lat, lon = float(geo["lat"]), float(geo["lon"])
        metric = c.get("rank_metric_value")
        if metric is None:
            metric = (
                c.get("dot_carrier_count")
                or c.get("focus_count")
                or c.get("focus_amount")
                or c.get("active_power_units")
                or c.get("dot_active_power_units")
                or 0
            )
        from html_format import linkify_zip_codes, zip_link_html  # local

        label = c.get("canonical_address") or key
        if str(key).isdigit() and len(str(key)) == 5:
            label_html = zip_link_html(str(key))
        else:
            label_html = linkify_zip_codes(label)
        if sample and sample != label and len(str(label)) < 40:
            popup = f"{label_html}<br><small>{linkify_zip_codes(sample)}</small>"
        else:
            popup = label_html
        kind = geo.get("kind") or "point"
        if kind == "loose" and geo.get("bounds"):
            b = geo["bounds"]
            popup += (
                f"<br><small>0.5° cell "
                f"[{b['lat_min']:.2f}…{b['lat_max']:.2f}, "
                f"{b['lon_min']:.2f}…{b['lon_max']:.2f}]</small>"
            )
        elif kind == "po_zip" and geo.get("zip"):
            popup += (
                f"<br><small>PO Box → zip {zip_link_html(str(geo['zip']))} centroid</small>"
            )
        elif kind == "zip" and geo.get("zip"):
            popup += f"<br><small>zip {zip_link_html(str(geo['zip']))} centroid</small>"
        metric_fmt = c.get("rank_metric_fmt") or c.get("focus_amount_fmt")
        if metric_fmt:
            popup += f"<br><strong>{metric_fmt}</strong>"
        href = c.get("detail_file")
        if href:
            popup += f'<br><a href="{href}">Detail →</a>'
        feat: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "label": str(label)[:120],
            "popup_html": popup,
            "metric": float(metric or 0),
            "href": href or "",
            "cluster_key": key,
            "kind": kind,
        }
        if geo.get("bounds"):
            b = geo["bounds"]
            feat["bounds"] = [
                [b["lat_min"], b["lon_min"]],
                [b["lat_max"], b["lon_max"]],
            ]
        if geo.get("zip"):
            feat["zip"] = geo["zip"]
        points.append(feat)
    return points


def single_point_from_key(
    key: str,
    *,
    label: str = "",
    href: str = "",
    slice_by: str | None = None,
    sample_address: str | None = None,
    zip_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    colocator: str | None = None,
) -> list[dict[str, Any]]:
    geo = resolve_geo(
        key,
        sample_address=sample_address,
        slice_by=slice_by,
        zip_code=zip_code,
        latitude=latitude,
        longitude=longitude,
        colocator=colocator,
    )
    if not geo:
        return []
    lat, lon = float(geo["lat"]), float(geo["lon"])
    lab = label or key
    popup = lab
    if geo.get("kind") == "loose" and geo.get("bounds"):
        b = geo["bounds"]
        popup += (
            f"<br><small>0.5° cell "
            f"[{b['lat_min']:.2f}…{b['lat_max']:.2f}, "
            f"{b['lon_min']:.2f}…{b['lon_max']:.2f}]</small>"
        )
    if geo.get("kind") == "po_zip" and geo.get("zip"):
        popup += f"<br><small>PO Box → zip {geo['zip']}</small>"
    if href:
        popup += f'<br><a href="{href}">Open</a>'
    feat: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "label": lab,
        "popup_html": popup,
        "metric": 0,
        "href": href,
        "cluster_key": key,
        "kind": geo.get("kind") or "ll",
    }
    if geo.get("bounds"):
        b = geo["bounds"]
        feat["bounds"] = [
            [b["lat_min"], b["lon_min"]],
            [b["lat_max"], b["lon_max"]],
        ]
    return [feat]
