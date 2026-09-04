#!/usr/bin/env python3
"""Export a dollar-band DuckDB snapshot for /browse (PR1).

Nodes: latest-year Charities in the $T set, BMF-only 9-digit endpoints,
ghosts (GIN), per-org leftover stubs. Edges: all-year grants between in-set
keys. GINs stay graph keys; suggested_ein is phonebook only.

HIPAA / patient-redacted / see-attach grantee names (big_pharma_subsidy.json)
are rolled into one Patient Subsidies node (etc997777777), not per-GIN ghosts.

Does not write recipient_ein.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from dot_reporting.grant_suppress import is_suppressed_sql, subsidy_graph_key

DEFAULT_DB = Path(__file__).resolve().parent / "irs990.duckdb"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_T = 10_000_000
CHUNK = 10_000

CHARITY_HEADER = [
    "filer_ein",
    "filer_name",
    "xml_name",
    "receipt_amt",
    "govt_amt",
    "contrib_amt",
    "tax_year",
    "org_type",
    "total_assets",
    "form_type",
    "denominator",
    "street",
    "city",
    "state",
    "zip",
]
GRANT_HEADER = ["filer_ein", "grant_ein", "grant_amt", "inferred", "suggested_ein"]


SETUP_SQL = r"""
CREATE OR REPLACE TEMP TABLE charity_size AS
SELECT ein,
       MAX(COALESCE(receipt_amt, 0)) AS mx_receipt,
       MAX(COALESCE(govt_amt, 0)) AS mx_govt,
       MAX(COALESCE(contrib_amt, 0)) AS mx_contrib,
       MAX(COALESCE(total_assets, 0)) AS mx_assets,
       MAX(COALESCE(grants_to_others, 0)) AS mx_grants
FROM Charities
GROUP BY ein;

CREATE OR REPLACE TEMP TABLE inset_ein AS
SELECT ein FROM charity_size
WHERE (mx_receipt >= $T OR mx_govt >= $T OR mx_contrib >= $T
   OR mx_assets >= $T OR mx_grants >= $T)
  AND regexp_matches(ein, '^[0-9]{9}$')
  AND ein NOT IN ('000000000', '111111111', '999999999')
UNION
SELECT DISTINCT filer_ein FROM Grants
WHERE grant_amt >= $T AND regexp_matches(filer_ein, '^[0-9]{9}$')
  AND filer_ein NOT IN ('000000000', '111111111', '999999999')
UNION
SELECT DISTINCT recipient_ein FROM Grants
WHERE grant_amt >= $T
  AND regexp_matches(recipient_ein, '^[0-9]{9}$')
  AND recipient_ein NOT IN ('000000000', '111111111', '999999999');

CREATE OR REPLACE TEMP TABLE inset_gin AS
SELECT recipient_ein AS gin
FROM Grants
WHERE grant_amt >= $T
  AND (length(recipient_ein) = 66 OR length(recipient_ein) = 130)
  AND recipient_ein LIKE '70%'
GROUP BY 1
HAVING NOT (
  regexp_matches(
    upper(trim(regexp_replace(COALESCE(ANY_VALUE(grantee_name), ''), '[^A-Za-z0-9]+', ' ', 'g'))),
    '^(SEE|SEE ATTACH.*|SEE SCHEDULE.*|SEE STATEMENT.*|SCHEDULE ATTACHED|VARIOUS|NONE|UNKNOWN|REDACTED|DONOR ADVISED FUND|UNITED WAY)$'
  )
);

CREATE OR REPLACE TEMP TABLE latest_charity AS
SELECT * EXCLUDE (rn) FROM (
  SELECT ein, filer_name, xml_name, receipt_amt, govt_amt, contrib_amt,
         tax_year, org_type, total_assets, form_type, denominator,
         ROW_NUMBER() OVER (
           PARTITION BY ein
           ORDER BY
             CASE WHEN filer_name IS NOT NULL AND TRIM(filer_name) != '' THEN 0 ELSE 1 END,
             CASE WHEN form_type IN ('990', '990EZ', '990PF') THEN 0 ELSE 1 END,
             tax_year DESC NULLS LAST
         ) AS rn
  FROM Charities
) WHERE rn = 1;

CREATE OR REPLACE TEMP TABLE filer_pf AS
SELECT ein, tax_year, BOOL_OR(form_type = '990PF') AS is_pf
FROM Charities
GROUP BY ein, tax_year;
"""

EDGES_SQL = r"""
CREATE OR REPLACE TEMP TABLE band_edges AS
SELECT
  g.filer_ein AS from_key,
  g.recipient_ein AS to_key,
  SUM(g.grant_amt)::BIGINT AS amt,
  MAX(CASE
        WHEN COALESCE(fp.is_pf, FALSE) THEN 1
        WHEN g.recipient_ein LIKE '70%' THEN 1
        WHEN NOT regexp_matches(COALESCE(g.recipient_ein, ''), '^[0-9]{9}$')
         AND regexp_matches(COALESCE(g.recipient_ein_backfilled, ''), '^[0-9]{9}$') THEN 1
        ELSE 0
      END)::INTEGER AS inferred,
  ANY_VALUE(g.recipient_ein_backfilled) FILTER (
    WHERE regexp_matches(COALESCE(g.recipient_ein_backfilled, ''), '^[0-9]{9}$')
  ) AS suggested_ein
FROM Grants g
LEFT JOIN filer_pf fp
  ON fp.ein = g.filer_ein AND fp.tax_year = g.tax_year
WHERE g.filer_ein IN (SELECT ein FROM inset_ein)
  AND (
    g.recipient_ein IN (SELECT ein FROM inset_ein)
    OR g.recipient_ein IN (SELECT gin FROM inset_gin)
  )
  AND g.filer_ein IS DISTINCT FROM g.recipient_ein
  AND g.grant_amt IS NOT NULL
GROUP BY 1, 2
HAVING SUM(g.grant_amt) > 0;
"""

LEFTOVER_SQL = r"""
CREATE OR REPLACE TEMP TABLE leftovers AS
SELECT
  g.filer_ein,
  SUM(g.grant_amt)::BIGINT AS leftover_amt,
  COUNT(DISTINCT g.recipient_ein)::BIGINT AS leftover_n
FROM Grants g
WHERE g.filer_ein IN (SELECT ein FROM inset_ein)
  AND g.filer_ein IS DISTINCT FROM g.recipient_ein
  AND g.grant_amt IS NOT NULL
  AND NOT (
    g.recipient_ein IN (SELECT ein FROM inset_ein)
    OR g.recipient_ein IN (SELECT gin FROM inset_gin)
  )
  AND NOT EXISTS (
    SELECT 1 FROM subsidy_named s
    WHERE s.filer_ein = g.filer_ein AND s.recipient_ein = g.recipient_ein
  )
GROUP BY 1
HAVING SUM(g.grant_amt) > 0;
"""

NODES_SQL = r"""
CREATE OR REPLACE TEMP TABLE band_nodes AS
SELECT
  l.ein AS filer_ein,
  COALESCE(
    NULLIF(TRIM(l.filer_name), ''),
    NULLIF(TRIM(b.NAME), ''),
    NULLIF(TRIM(gn.grantee_name), ''),
    l.ein
  ) AS filer_name,
  COALESCE(l.xml_name, '') AS xml_name,
  COALESCE(l.receipt_amt, 0)::BIGINT AS receipt_amt,
  COALESCE(l.govt_amt, 0)::BIGINT AS govt_amt,
  COALESCE(l.contrib_amt, 0)::BIGINT AS contrib_amt,
  l.tax_year,
  COALESCE(l.org_type, '') AS org_type,
  COALESCE(l.total_assets, 0) AS total_assets,
  COALESCE(l.form_type, '') AS form_type,
  COALESCE(l.denominator, 0) AS denominator,
  COALESCE(NULLIF(TRIM(b.STREET), ''), '') AS street,
  COALESCE(NULLIF(TRIM(b.CITY), ''), '') AS city,
  COALESCE(NULLIF(TRIM(b.STATE), ''), '') AS state,
  COALESCE(NULLIF(TRIM(b.ZIP), ''), '') AS zip,
  'charity' AS kind
FROM latest_charity l
LEFT JOIN BMF b ON b.EIN = l.ein
LEFT JOIN (
  SELECT recipient_ein, ANY_VALUE(grantee_name) AS grantee_name
  FROM Grants
  WHERE regexp_matches(recipient_ein, '^[0-9]{9}$')
  GROUP BY 1
) gn ON gn.recipient_ein = l.ein
WHERE l.ein IN (SELECT ein FROM inset_ein)

UNION ALL

SELECT
  i.ein AS filer_ein,
  COALESCE(
    NULLIF(TRIM(b.NAME), ''),
    NULLIF(TRIM(gn.grantee_name), ''),
    i.ein
  ) AS filer_name,
  'backfill' AS xml_name,
  0, 0, 0, NULL,
  'backfill' AS org_type,
  0, '', 0,
  COALESCE(NULLIF(TRIM(b.STREET), ''), ''),
  COALESCE(NULLIF(TRIM(b.CITY), ''), ''),
  COALESCE(NULLIF(TRIM(b.STATE), ''), ''),
  COALESCE(NULLIF(TRIM(b.ZIP), ''), ''),
  'bmf' AS kind
FROM inset_ein i
LEFT JOIN latest_charity l ON l.ein = i.ein
LEFT JOIN BMF b ON b.EIN = i.ein
LEFT JOIN (
  SELECT recipient_ein, ANY_VALUE(grantee_name) AS grantee_name
  FROM Grants
  WHERE regexp_matches(recipient_ein, '^[0-9]{9}$')
  GROUP BY 1
) gn ON gn.recipient_ein = i.ein
WHERE l.ein IS NULL

UNION ALL

SELECT
  ig.gin AS filer_ein,
  COALESCE(NULLIF(TRIM(ANY_VALUE(g.grantee_name)), ''), 'Unknown grantee') AS filer_name,
  'ghost' AS xml_name,
  0, 0, 0, NULL,
  'ghost' AS org_type,
  0, '', 0,
  '', '', '', '',
  'ghost' AS kind
FROM inset_gin ig
JOIN Grants g ON g.recipient_ein = ig.gin
GROUP BY ig.gin

UNION ALL

SELECT
  'etc' || lo.filer_ein AS filer_ein,
  'see more' AS filer_name,
  'leftover' AS xml_name,
  0, 0, 0, NULL,
  'leftover' AS org_type,
  0, '', 0,
  '', '', '', '',
  'leftover' AS kind
FROM leftovers lo;
"""


SINK_NAME = "Patient Subsidies"


def map_subsidy_grants(con) -> tuple[str, int]:
    """Roll name-suppressed GIN / leftover grantees into one Patient Subsidies node.

    9-digit EIN counterparties stay as themselves even if the name matches.
    """
    sink = subsidy_graph_key()
    is_sub = is_suppressed_sql("g.grantee_name")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE subsidy_named AS
        SELECT g.filer_ein, g.recipient_ein, g.grant_amt
        FROM Grants g
        WHERE g.filer_ein IN (SELECT ein FROM inset_ein)
          AND g.filer_ein IS DISTINCT FROM g.recipient_ein
          AND g.grant_amt IS NOT NULL
          AND NOT regexp_matches(COALESCE(g.recipient_ein, ''), '^[0-9]{{9}}$')
          AND {is_sub}
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE subsidy_gin AS
        SELECT DISTINCT recipient_ein AS gin FROM subsidy_named
        WHERE (length(recipient_ein) = 66 OR length(recipient_ein) = 130)
          AND recipient_ein LIKE '70%'
        """
    )
    con.execute("DELETE FROM inset_gin WHERE gin IN (SELECT gin FROM subsidy_gin)")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE subsidy_edges AS
        SELECT
          filer_ein AS from_key,
          '{sink}' AS to_key,
          SUM(grant_amt)::BIGINT AS amt,
          1 AS inferred,
          '' AS suggested_ein
        FROM subsidy_named
        GROUP BY 1
        HAVING SUM(grant_amt) > 0
        """
    )
    n = con.execute("SELECT COUNT(*) FROM subsidy_edges").fetchone()[0]
    return sink, n


def build_band_tables(con, T: int) -> dict:
    """Populate inset_*, band_edges, leftovers, band_nodes, subsidy_* on con."""
    con.execute(SETUP_SQL.replace("$T", str(T)))
    sink, n_sub = map_subsidy_grants(con)
    n_ein = con.execute("SELECT COUNT(*) FROM inset_ein").fetchone()[0]
    n_gin = con.execute("SELECT COUNT(*) FROM inset_gin").fetchone()[0]
    con.execute(EDGES_SQL)
    n_edge = con.execute("SELECT COUNT(*) FROM band_edges").fetchone()[0]
    con.execute(LEFTOVER_SQL)
    n_lo = con.execute("SELECT COUNT(*) FROM leftovers").fetchone()[0]
    con.execute(NODES_SQL)
    insert_sink_node(con, sink)
    kinds = con.execute(
        "SELECT kind, COUNT(*) FROM band_nodes GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {
        "inset_ein": n_ein,
        "inset_gin": n_gin,
        "subsidy_edges": n_sub,
        "sink": sink,
        "edges": n_edge,
        "leftovers": n_lo,
        "kinds": kinds,
    }


def insert_sink_node(con, sink: str) -> None:
    con.execute(
        f"""
        INSERT INTO band_nodes
        SELECT
          '{sink}', '{SINK_NAME}', 'leftover',
          0, 0, 0, NULL, 'leftover', 0, '', 0,
          '', '', '', '',
          'leftover'
        WHERE EXISTS (SELECT 1 FROM subsidy_edges)
          AND NOT EXISTS (SELECT 1 FROM band_nodes WHERE filer_ein = '{sink}')
        """
    )


def _iter_query(con, sql: str, batch: int = CHUNK):
    res = con.execute(sql)
    while True:
        chunk = res.fetchmany(batch)
        if not chunk:
            break
        for row in chunk:
            yield row


def _write_chunks(rows, header, prefix: Path, zip_dir: Path) -> int:
    zip_dir.mkdir(parents=True, exist_ok=True)
    n_chunks = 0
    buf = []
    idx = 0

    def flush():
        nonlocal n_chunks, buf, idx
        if not buf:
            return
        tsv_name = f"{prefix.name}_{n_chunks}.tsv"
        zip_path = zip_dir / f"{tsv_name}.zip"
        body = "\t".join(header) + "\n" + "\n".join(buf) + "\n"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(tsv_name, body)
        n_chunks += 1
        buf = []
        idx = 0

    for row in rows:
        cells = []
        for v in row:
            if v is None:
                cells.append("")
            else:
                cells.append(str(v).replace("\t", " ").replace("\n", " "))
        buf.append("\t".join(cells))
        idx += 1
        if idx >= CHUNK:
            flush()
    flush()
    return n_chunks


def _write_data_files(
    path: Path,
    db_version: str,
    n_char: int,
    n_grant: int,
    stats: dict | None = None,
) -> None:
    """Rewrite $10M chunk counts; keep $1M / All file lists from the previous manifest."""
    files_10m = [
        {
            "status": "Loading Charities",
            "baseFile": "/browse/tsv_chunks/charities_chunk_",
            "tsvFilePrefix": "charities_chunk_",
            "type": "charities",
            "chunkCount": n_char,
        },
        {
            "status": "Loading Grants",
            "baseFile": "/browse/tsv_chunks/grants_final_chunk_",
            "tsvFilePrefix": "grants_final_chunk_",
            "type": "grants",
            "chunkCount": n_grant,
            "grantType": "regular",
        },
    ]
    s = stats or {}
    body = f"""const FILES_10M = {json.dumps(files_10m, indent=2)};

export const DATA_FILES = {{
  dbVersion: {json.dumps(db_version)},
  defaultBand: "10M",
  bands: [
    {{
      id: "10M",
      label: "$10M",
      threshold: 10000000,
      nodes: {s.get("nodes", "null")},
      grants: {s.get("grants", "null")},
      dollars: {s.get("dollars", "null")},
      edges: {s.get("edges", "null")},
      files: FILES_10M,
    }},
    {{
      id: "1M",
      label: "$1M",
      threshold: 1000000,
      nodes: 371236,
      grants: 1698597,
      dollars: 2574763247168,
      edges: 1618824,
      files: [
        {{
          status: "Loading Charities ($1M)",
          baseFile: "/browse/tsv_chunks/1m/charities_chunk_",
          tsvFilePrefix: "charities_chunk_",
          type: "charities",
          chunkCount: 38,
        }},
        {{
          status: "Loading Grants ($1M)",
          baseFile: "/browse/tsv_chunks/1m/grants_final_chunk_",
          tsvFilePrefix: "grants_final_chunk_",
          type: "grants",
          chunkCount: 170,
          grantType: "regular",
        }},
      ],
    }},
    {{
      id: "all",
      label: "All",
      threshold: 1,
      nodes: 2641709,
      grants: 5627968,
      dollars: 2600747385432,
      edges: 5604343,
      files: [
        {{
          status: "Loading Charities (All)",
          baseFile: "/browse/tsv_chunks/all/charities_chunk_",
          tsvFilePrefix: "charities_chunk_",
          type: "charities",
          chunkCount: 265,
        }},
        {{
          status: "Loading Grants (All)",
          baseFile: "/browse/tsv_chunks/all/grants_final_chunk_",
          tsvFilePrefix: "grants_final_chunk_",
          type: "grants",
          chunkCount: 563,
          grantType: "regular",
        }},
      ],
    }},
  ],
  files: FILES_10M,
}};
"""
    path.write_text(body)


def _copy_dest_to_docs(dest: Path) -> Path:
    """Copy dest into docs/browse at the same relative path. Never rmtree tsv_chunks/."""
    browse_root = (ROOT / "browse").resolve()
    dest_res = dest.resolve()
    try:
        rel = dest_res.relative_to(browse_root)
    except ValueError:
        rel = Path(dest.name)
    docs_dest = ROOT / "docs" / "browse" / rel
    docs_dest.mkdir(parents=True, exist_ok=True)
    for old in docs_dest.glob("*.tsv.zip"):
        old.unlink()
    for src in dest_res.glob("*.tsv.zip"):
        shutil.copy2(src, docs_dest / src.name)
    return docs_dest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    p.add_argument("--threshold", type=int, default=DEFAULT_T)
    p.add_argument("--dest", type=Path, default=ROOT / "browse" / "tsv_chunks")
    p.add_argument("--also-docs", action="store_true", default=True)
    p.add_argument(
        "--skip-manifest",
        action="store_true",
        help="Do not rewrite data_files.js (keep $10M dbVersion / IndexedDB).",
    )
    args = p.parse_args()
    db = args.db_path.expanduser().resolve()
    dest = args.dest
    T = args.threshold
    print(f"DB {db} T=${T:,} dest={dest}", flush=True)

    con = duckdb.connect(str(db), read_only=True)
    con.execute("SET threads TO 8")
    stats = build_band_tables(con, T)
    n_ein, n_gin, n_sub, sink, n_edge, n_lo, kinds = (
        stats["inset_ein"],
        stats["inset_gin"],
        stats["subsidy_edges"],
        stats["sink"],
        stats["edges"],
        stats["leftovers"],
        stats["kinds"],
    )
    print(f"inset EIN {n_ein:,}; inset GIN {n_gin:,}", flush=True)
    print(f"subsidy edges {n_sub:,} → {sink}", flush=True)
    print(f"edges {n_edge:,}", flush=True)
    print(f"leftover stubs {n_lo:,}", flush=True)
    print("nodes", kinds, flush=True)

    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.tsv.zip"):
        old.unlink()

    node_rows = _iter_query(
        con,
        """
        SELECT filer_ein, filer_name, xml_name, receipt_amt, govt_amt, contrib_amt,
               tax_year, org_type, total_assets, form_type, denominator,
               street, city, state, zip
        FROM band_nodes
        ORDER BY kind, filer_ein
        """,
    )
    grant_rows = _iter_query(
        con,
        """
        SELECT from_key, to_key, amt, inferred, COALESCE(suggested_ein, '')
        FROM band_edges
        UNION ALL
        SELECT from_key, to_key, amt, inferred, suggested_ein
        FROM subsidy_edges
        UNION ALL
        SELECT filer_ein, 'etc' || filer_ein, leftover_amt, 1, ''
        FROM leftovers
        """,
    )

    n_char_chunks = _write_chunks(node_rows, CHARITY_HEADER, dest / "charities_chunk", dest)
    n_grant_chunks = _write_chunks(grant_rows, GRANT_HEADER, dest / "grants_final_chunk", dest)
    print(f"chunks charities={n_char_chunks} grants={n_grant_chunks}", flush=True)

    zip_bytes = sum(f.stat().st_size for f in dest.glob("*.tsv.zip"))
    print(f"zip bytes {zip_bytes:,} ({zip_bytes/1e6:.1f} MB)", flush=True)

    db_version = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.skip_manifest:
        print("skip-manifest: not rewriting data_files.js", flush=True)
    else:
        n_nodes = con.execute("SELECT COUNT(*) FROM band_nodes").fetchone()[0]
        n_grant_rows = n_edge + n_lo + n_sub
        dollars = con.execute(
            """
            SELECT COALESCE(SUM(amt), 0) FROM (
              SELECT amt FROM band_edges
              UNION ALL SELECT amt FROM subsidy_edges
              UNION ALL SELECT leftover_amt FROM leftovers
            )
            """
        ).fetchone()[0]
        _write_data_files(
            ROOT / "browse" / "data_files.js",
            db_version,
            n_char_chunks,
            n_grant_chunks,
            stats={
                "nodes": n_nodes,
                "grants": n_grant_rows,
                "dollars": int(dollars or 0),
                "edges": n_edge + n_sub,
            },
        )

    gates = con.execute(
        """
        SELECT from_key, to_key, amt, inferred, suggested_ein
        FROM band_edges
        WHERE from_key = '911663695'
        ORDER BY amt DESC
        LIMIT 8
        """
    ).fetchall()
    print("Gates Trust outgoing sample:", flush=True)
    for row in gates:
        print(f"  {row}", flush=True)

    if args.also_docs:
        docs_dest = _copy_dest_to_docs(dest)
        print(f"copied zips to {docs_dest}", flush=True)
        if not args.skip_manifest:
            shutil.copy2(ROOT / "browse" / "data_files.js", ROOT / "docs" / "browse" / "data_files.js")
            print("copied data_files.js to docs/browse", flush=True)

    print(
        json.dumps(
            {
                "threshold": T,
                "inset_ein": n_ein,
                "inset_gin": n_gin,
                "nodes": {k: v for k, v in kinds},
                "edges": n_edge,
                "leftovers": n_lo,
                "subsidy_edges": n_sub,
                "sink": sink,
                "charity_chunks": n_char_chunks,
                "grant_chunks": n_grant_chunks,
                "zip_mb": round(zip_bytes / 1e6, 2),
                "dbVersion": db_version,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
