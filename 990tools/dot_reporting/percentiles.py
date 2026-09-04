#!/usr/bin/env python3
"""Fast percentile helpers (in-memory + DuckDB quantile_cont).

Use cases:
  1. Rank dots / map colors: empirical percentile within the *current* series
     (e.g. top-100 clusters on a page) instead of value/max tertiles.
  2. Threshold design: population quantiles from the full DB so min_focus /
     min_dot_carriers can be set as "≈p99" rather than gut feel.

DuckDB:
  quantile_cont(col, 0.95)
  quantile_cont(col, [0.5, 0.9, 0.95, 0.99])
  approx_quantile(col, 0.95)   -- faster sketch on huge tables
  percent_rank() OVER (ORDER BY col)
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


DEFAULT_PROBS = (0.5, 0.75, 0.9, 0.95, 0.99, 0.999)


def _finite_floats(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f:  # not NaN
            out.append(f)
    return out


def quantile_sorted(sorted_vals: Sequence[float], p: float) -> float | None:
    """Linear-interpolated quantile on a pre-sorted finite list (p in [0,1])."""
    if not sorted_vals:
        return None
    if p <= 0:
        return float(sorted_vals[0])
    if p >= 1:
        return float(sorted_vals[-1])
    n = len(sorted_vals)
    idx = (n - 1) * p
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return float(sorted_vals[lo]) * (1 - frac) + float(sorted_vals[hi]) * frac


def quantiles(
    values: Iterable[Any],
    probs: Sequence[float] = DEFAULT_PROBS,
) -> dict[float, float]:
    """Return {probability: value} for finite samples (in-memory)."""
    s = sorted(_finite_floats(values))
    out: dict[float, float] = {}
    for p in probs:
        q = quantile_sorted(s, float(p))
        if q is not None:
            out[float(p)] = q
    return out


def empirical_percentile(sorted_vals: Sequence[float], value: float) -> float:
    """Percent of values strictly below `value` (0–100). Ties → midrank-ish via bisect."""
    if not sorted_vals:
        return 0.0
    # fraction of samples <= value (inclusive CDF) mapped to 0–100
    i = bisect.bisect_right(sorted_vals, value)
    return 100.0 * i / len(sorted_vals)


@dataclass
class MetricScale:
    """Percentile scale for a numeric series (usually one page / one table)."""

    sorted_vals: list[float]
    vmax: float
    quantiles: dict[float, float]

    @classmethod
    def from_values(
        cls,
        values: Iterable[Any],
        *,
        probs: Sequence[float] = (0.5, 0.9, 0.95, 0.99),
    ) -> "MetricScale":
        s = sorted(_finite_floats(values))
        vmax = float(s[-1]) if s else 0.0
        qs = {float(p): quantile_sorted(s, float(p)) for p in probs}
        qs = {p: v for p, v in qs.items() if v is not None}
        return cls(sorted_vals=s, vmax=vmax, quantiles=qs)

    def percentile(self, value: Any) -> float | None:
        if value is None or not self.sorted_vals:
            return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f:
            return None
        return empirical_percentile(self.sorted_vals, f)

    def tier(self, value: Any) -> str:
        """Map value → CSS tier using empirical percentile (not value/max).

        Bands (within the series):
          none   — missing / empty series
          low    — < p50
          mid    — p50–p90
          high   — p90–p99
          top    — ≥ p99  (extreme tail within this list)
        """
        pct = self.percentile(value)
        if pct is None:
            return "none"
        if pct >= 99:
            return "top"
        if pct >= 90:
            return "high"
        if pct >= 50:
            return "mid"
        return "low"

    def tier_title(self, value: Any, *, label: str = "metric") -> str:
        pct = self.percentile(value)
        if pct is None:
            return "No metric"
        tier = self.tier(value)
        return f"{label}: p{pct:.0f} within this list ({tier})"


def duckdb_quantiles(
    conn,
    sql: str,
    *,
    probs: Sequence[float] = DEFAULT_PROBS,
    approx: bool = False,
) -> dict[str, Any]:
    """Run a 1-column SQL and return count + quantiles.

    `sql` must select a single numeric column, e.g.
      SELECT total_paid FROM medicare_provider_rollup WHERE total_paid > 0
    """
    probs = [float(p) for p in probs]
    if approx and len(probs) == 1:
        # approx_quantile is single-p only in older DuckDB
        row = conn.execute(
            f"""
            SELECT count(*)::BIGINT,
                   approx_quantile(v, {probs[0]})
            FROM ({sql}) AS _q(v)
            WHERE v IS NOT NULL
            """
        ).fetchone()
        return {
            "count": int(row[0] or 0),
            "quantiles": {probs[0]: float(row[1])} if row[1] is not None else {},
            "approx": True,
        }

    # quantile_cont accepts a list of probabilities
    prob_lit = "[" + ", ".join(str(p) for p in probs) + "]"
    row = conn.execute(
        f"""
        SELECT count(*)::BIGINT AS n,
               quantile_cont(v, {prob_lit}) AS qs,
               min(v) AS mn,
               max(v) AS mx
        FROM ({sql}) AS _q(v)
        WHERE v IS NOT NULL
        """
    ).fetchone()
    n, qs, mn, mx = row
    qmap: dict[float, float] = {}
    if qs is not None:
        # DuckDB may return list/tuple
        seq = list(qs) if not isinstance(qs, (int, float)) else [qs]
        for p, val in zip(probs, seq):
            if val is not None:
                qmap[float(p)] = float(val)
    return {
        "count": int(n or 0),
        "quantiles": qmap,
        "min": float(mn) if mn is not None else None,
        "max": float(mx) if mx is not None else None,
        "approx": False,
    }


def format_quantile_table(result: dict[str, Any], *, money: bool = False) -> str:
    """Human-readable multi-line summary."""

    def fmt(v: float | None) -> str:
        if v is None:
            return "—"
        if money:
            if abs(v) >= 1e9:
                return f"${v/1e9:.2f}B"
            if abs(v) >= 1e6:
                return f"${v/1e6:.2f}M"
            if abs(v) >= 1e3:
                return f"${v/1e3:.1f}K"
            return f"${v:,.0f}"
        if abs(v) >= 1000:
            return f"{v:,.1f}"
        if float(v).is_integer():
            return f"{int(v):,}"
        return f"{v:.3g}"

    lines = [f"n={result.get('count', 0):,}"]
    if result.get("min") is not None:
        lines.append(f"min={fmt(result['min'])}  max={fmt(result.get('max'))}")
    for p, v in sorted((result.get("quantiles") or {}).items()):
        pct = int(round(p * 100)) if p <= 1 else int(p)
        # p=0.999 → show p99.9
        if abs(p * 100 - pct) > 0.05:
            label = f"p{p*100:.1f}"
        else:
            label = f"p{pct}"
        lines.append(f"  {label:>6} = {fmt(v)}")
    return "\n".join(lines)


# --- Domain queries for threshold design (population, not page-local) ---

DOMAIN_METRIC_SQL: dict[str, dict[str, Any]] = {
    "dot_carriers_per_address": {
        "label": "DOT physical rows per canonical_address (phy only)",
        "money": False,
        "sql": """
            SELECT count(*)::DOUBLE
            FROM Addresses
            WHERE address_type = 'dot_carrier_phy'
            GROUP BY canonical_address
        """,
        "note": "min_dot_carriers ≈ high percentile of physical stacks; mail ignored",
    },
    "medicare_paid_per_npi": {
        "label": "Medicare total_paid per billing NPI (rollup)",
        "money": True,
        "sql": """
            SELECT total_paid::DOUBLE
            FROM medicare_provider_rollup
            WHERE total_paid > 0
        """,
        "note": "raw $ — hospitals dominate the tail",
    },
    "medicare_hcpcs_types": {
        "label": "HCPCS type count per NPI (rollup)",
        "money": False,
        "sql": """
            SELECT hcpcs_type_count::DOUBLE
            FROM medicare_provider_rollup
            WHERE total_paid > 0
        """,
        "note": "narrow mix ≈ low percentile; mills often low types + high paid",
    },
    "medicare_paid_per_hcpcs_type": {
        "label": "paid / hcpcs_type_count (narrow-code intensity)",
        "money": True,
        "sql": """
            SELECT CASE
                     WHEN hcpcs_type_count > 0
                     THEN total_paid::DOUBLE / hcpcs_type_count
                   END
            FROM medicare_provider_rollup
            WHERE total_paid > 0 AND hcpcs_type_count > 0
        """,
        "note": "candidate mill-score component",
    },
}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import duckdb

    p = argparse.ArgumentParser(
        description="Population percentiles for DOT/Medicare threshold design"
    )
    p.add_argument(
        "--db-path",
        default=os.environ.get("IRS990_DB_PATH", "/Volumes/Data/final/irs990.duckdb"),
    )
    p.add_argument(
        "--metric",
        choices=["all", *DOMAIN_METRIC_SQL.keys()],
        default="all",
    )
    p.add_argument(
        "--probs",
        default="0.5,0.75,0.9,0.95,0.99,0.999",
        help="Comma-separated probabilities in [0,1]",
    )
    args = p.parse_args(argv)
    probs = [float(x.strip()) for x in args.probs.split(",") if x.strip()]

    con = duckdb.connect(args.db_path, read_only=True)
    keys = (
        list(DOMAIN_METRIC_SQL.keys())
        if args.metric == "all"
        else [args.metric]
    )
    for key in keys:
        cfg = DOMAIN_METRIC_SQL[key]
        print(f"\n=== {key} ===")
        print(cfg["label"])
        if cfg.get("note"):
            print(f"  ({cfg['note']})")
        try:
            res = duckdb_quantiles(con, cfg["sql"].strip(), probs=probs)
            print(format_quantile_table(res, money=bool(cfg.get("money"))))
        except Exception as e:
            print(f"  ERROR: {e}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
