#!/usr/bin/env python3
"""DOT matching policy for cluster reports.

Physical (`dot_carrier_phy`) is the operational footprint: yards, shops, homes
that should support real carrier duties. Mailing (`dot_carrier_mail`) is
paperwork — UPS Stores, PMBs, virtual offices — and is **not** used for
DOT stack ranking, thresholds, or carrier tables.

Mail rows may still appear in multi-type type lists when co-located with
other domains; they do not increment `dot_carrier_count` / focus DOT metrics.

See domain_briefing.FOCUS_BRIEFINGS["dot"]["carrier_duties"] for the
FMCSR-oriented list of carrier obligations (bold = needs more than a
computer and a printer). Key cites: 49 CFR Parts 382–396, 390.29, 385 Subpart D.
"""

from __future__ import annotations

# Single source of truth for SQL fragments
DOT_PHY_TYPE = "dot_carrier_phy"
DOT_MAIL_TYPE = "dot_carrier_mail"  # documented; not used for matching

DOT_PHY_SQL = f"address_type = '{DOT_PHY_TYPE}'"
# Prefer this in CASE/SUM (alias-safe: bare address_type)
DOT_PHY_CASE = f"address_type = '{DOT_PHY_TYPE}'"
# JOIN filter with table alias `a` or `k` or `m`
def dot_phy_sql(col: str = "address_type") -> str:
    return f"{col} = '{DOT_PHY_TYPE}'"
