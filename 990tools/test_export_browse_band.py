#!/usr/bin/env python3
"""In-memory DuckDB tests for browse-band subsidy rollup."""

from __future__ import annotations

import duckdb

from export_browse_band import build_band_tables
from dot_reporting.grant_suppress import subsidy_graph_key

HIPAA_GIN = "70" + "ab" * 32
WELVISTA_GIN = "70" + "cd" * 32
ATCH_GIN = "70" + "ef" * 32
PAP = "261437283"
MIT = "042103594"


def _schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE Charities (
          ein VARCHAR, filer_name VARCHAR, xml_name VARCHAR,
          receipt_amt BIGINT, govt_amt BIGINT, contrib_amt BIGINT,
          tax_year INTEGER, org_type VARCHAR, total_assets BIGINT,
          form_type VARCHAR, denominator BIGINT, grants_to_others BIGINT
        );
        CREATE TABLE Grants (
          filer_ein VARCHAR, recipient_ein VARCHAR, grant_amt BIGINT,
          tax_year INTEGER, grantee_name VARCHAR, recipient_ein_backfilled VARCHAR
        );
        CREATE TABLE BMF (
          EIN VARCHAR, NAME VARCHAR,
          STREET VARCHAR, CITY VARCHAR, STATE VARCHAR, ZIP VARCHAR
        );
        """
    )
    con.execute(
        """
        INSERT INTO Charities VALUES
          (?, 'Pfizer Patient Assistance Foundation Inc', '2024_public.xml',
           1000000000, 0, 0, 2024, '501(c)(3)', 1, '990', 1, 500000000),
          (?, 'Massachusetts Institute of Technology', '2024_public.xml',
           2000000000, 0, 0, 2024, '501(c)(3)', 1, '990', 1, 0)
        """,
        [PAP, MIT],
    )
    con.execute(
        """
        INSERT INTO Grants VALUES
          (?, ?, 20000000000, 2024, 'Individual Patient Programs', ''),
          (?, ?, 12000000, 2024, 'Atch 4', ''),
          (?, ?, 5000000, 2024, 'Welvista', ''),
          (?, ?, 15000000, 2024, 'Massachusetts Institute of Technology', '')
        """,
        [PAP, HIPAA_GIN, PAP, ATCH_GIN, PAP, WELVISTA_GIN, PAP, MIT],
    )


def test_subsidy_names_share_one_sink():
    con = duckdb.connect(":memory:")
    _schema(con)
    stats = build_band_tables(con, 10_000_000)
    sink = subsidy_graph_key()
    assert stats["sink"] == sink
    assert stats["subsidy_edges"] == 1

    ghosts = [r[0] for r in con.execute(
        "SELECT filer_ein FROM band_nodes WHERE kind = 'ghost'"
    ).fetchall()]
    assert HIPAA_GIN not in ghosts
    assert ATCH_GIN not in ghosts

    names = [r[0] for r in con.execute("SELECT filer_name FROM band_nodes").fetchall()]
    assert "Patient Subsidies" in names
    assert "Individual Patient Programs" not in names

    to_sink = con.execute(
        "SELECT amt FROM subsidy_edges WHERE from_key = ? AND to_key = ?",
        [PAP, sink],
    ).fetchone()
    assert to_sink is not None
    # HIPAA 20B + Atch 12M + Welvista 5M (below band, name is not subsidy)
    # Welvista should NOT be in subsidy_named
    assert to_sink[0] == 20_000_000_000 + 12_000_000

    mit = con.execute(
        "SELECT amt FROM band_edges WHERE from_key = ? AND to_key = ?",
        [PAP, MIT],
    ).fetchone()
    assert mit and mit[0] == 15_000_000


if __name__ == "__main__":
    test_subsidy_names_share_one_sink()
    print("ok")
