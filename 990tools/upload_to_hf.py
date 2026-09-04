#!/usr/bin/env python3
"""
Export the live DuckDB to Parquet and upload piercewetter3/irs-990-parsed.

Discovers tables from the DB. Skips ops/scratch/raw leftovers. Casts UUID
columns to VARCHAR so the Hub dataset viewer can read them. Large tables
are written as a directory of ~256 MB ZSTD shards.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import duckdb
from huggingface_hub import HfApi, create_repo, upload_folder, upload_large_folder

DEFAULT_DB = "/Volumes/Data/final/irs990.duckdb"
DEFAULT_REPO = "piercewetter3/irs-990-parsed"
DEFAULT_OUT = "/Volumes/Data/final/parquet_export_990"
DEFAULT_SCHEMA = Path(__file__).resolve().parent / "schema_duckdb.sql"
SHARD_MIN_ROWS = 2_000_000
FILE_SIZE_BYTES = "256MB"
LARGE_FOLDER_BYTES = 2 * 1024 * 1024 * 1024

# Not public product. Override with --include.
SKIP_TABLES = {
    "PipelineProgress": "local pipeline job state",
    "PendingCanonicals": "empty address-dedup scratch",
    "_meta_clustering": "DuckDB clustering bookkeeping",
    "grant_update_map": "grant_match scratch",
    "temp_gin_batch": "grant_match scratch",
    "fec_raw_committees": "1-row ingest leftover; use fec_committees",
    "medicare_raw_spending": "238M raw CMS extract; use medicare_provider_spending",
    "Zips_raw": "source extract; use Zips",
}

TABLE_BLURBS = {
    "Addresses": "Normalized streets for every owner type (990, Medicare, DOT, OFAC, FEC)",
    "AuthoritativeEin": "Canonical name → EIN seeds used by grant matching",
    "BMF": "IRS EO Business Master File including street/city/state/ZIP",
    "Backfill": "Einless grantee backfill (recipient EIN resolved after ingest)",
    "Charities": "Parsed Form 990 / 990-EZ / 990-PF filer years",
    "Contractors": "Highest-paid independent contractors from 990 Part VII",
    "Contributions": "Incoming contribution rows (currently empty in this build)",
    "Geocoding": "Geocode attempts and rounded lat/lon for master addresses",
    "Grants": "Grants paid (Schedule I / PF grants)",
    "IrsBmf": "BMF without raw street fields (legacy export table)",
    "Officers": "Officer / key-employee compensation",
    "PoliticalContributions": "527 / political outlays from 990 (currently empty)",
    "XmlFiles": "One row per IRS XML filing ingested",
    "ZipFiles": "IRS annual ZIP archives fetched",
    "Zips": "US ZIP centroids used for zip-slice reports",
    "base_name_ein": "Distinct grantee-name → EIN rollup from grants",
    "dot_carriers": "FMCSA motor-carrier census",
    "fec_candidate_spendings": "FEC candidate spend (city/state/ZIP, not street)",
    "fec_committee_transactions": "FEC committee-to-committee transfers",
    "fec_committees": "FEC committees with a real line-1 street",
    "fec_individual_contributions": "FEC individual contributions (city/state/ZIP)",
    "fec_operating_expenditures": "FEC operating expenditures",
    "hcpcs_codes": "HCPCS procedure code lookup",
    "medicare_provider_hcpcs": "Medicare spend rolled up by NPI × HCPCS",
    "medicare_provider_rollup": "Medicare spend rolled up by billing NPI",
    "medicare_provider_spending": "Medicare T-MSIS line grain (billing × servicing × HCPCS × month)",
    "medicare_providers": "NPPES provider enumeration",
    "name_mapping": "Cleaned name → winning EIN from traditional matching",
    "noc_codes": "NOC code lookup",
    "nppes_code_values": "NPPES codebook (entity type, taxonomy, etc.)",
    "sanctioned_entities": "OFAC SDN entities",
    "sanctioned_identifiers": "OFAC identifiers (passport, tax id, …)",
    "sanctioned_names": "OFAC primary names and aliases",
    "sanctioned_programs": "OFAC program codes on each entity",
}


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()
    return [r[0] for r in rows]


def table_rows(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {qident(table)}").fetchone()[0])


def clean_select(con: duckdb.DuckDBPyConnection, table: str) -> str:
    columns = con.execute(f"DESCRIBE {qident(table)}").fetchall()
    parts = []
    for col_name, col_type, *_ in columns:
        ident = qident(col_name)
        if str(col_type).upper() == "UUID":
            parts.append(f"CAST({ident} AS VARCHAR) AS {ident}")
        else:
            parts.append(ident)
    return f"SELECT {', '.join(parts)} FROM {qident(table)}"


def dest_is_dir(rows: int) -> bool:
    return rows >= SHARD_MIN_ROWS


def table_dest(out_dir: Path, table: str, rows: int) -> Path:
    if dest_is_dir(rows):
        return out_dir / table
    return out_dir / f"{table}.parquet"


def export_table(con: duckdb.DuckDBPyConnection, table: str, dest: Path, rows: int) -> None:
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    select_sql = clean_select(con, table)
    if dest_is_dir(rows):
        dest.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"""
            COPY ({select_sql})
            TO '{dest.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, FILE_SIZE_BYTES '{FILE_SIZE_BYTES}', OVERWRITE_OR_IGNORE)
            """
        )
    else:
        con.execute(
            f"""
            COPY ({select_sql})
            TO '{dest.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )


def local_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def write_readme(path: Path, catalog: list[dict], skipped: list[dict], repo_id: str) -> None:
    included = [c for c in catalog if c["action"] == "export"]
    total_rows = sum(c["rows"] for c in included)
    lines = [
        "---",
        "license: cc0-1.0",
        "task_categories:",
        "- tabular-classification",
        "- tabular-regression",
        "- question-answering",
        "tags:",
        '- "nonprofit"',
        '- "990"',
        '- "irs"',
        '- "medicare"',
        '- "dot"',
        '- "ofac"',
        '- "fec"',
        '- "philanthropy"',
        '- "finance"',
        '- "public-data"',
        '- "duckdb"',
        "---",
        "",
        "# IRS 990 Parsed Nonprofit Database",
        "",
        "Public relational extract of IRS Form 990 / 990-EZ / 990-PF filings, "
        "plus the colocated public files we join for address research: "
        "CMS NPPES + T-MSIS Medicare spend, FMCSA DOT carriers, OFAC SDN, "
        "FEC committees, and the IRS EO BMF.",
        "",
        f"**Generated:** {date.today().isoformat()}  ",
        f"**Tables:** {len(included)}  ",
        f"**Rows (sum):** {total_rows:,}  ",
        "**License:** CC0 / public domain — derived from U.S. government records  ",
        f"**Hub:** https://huggingface.co/datasets/{repo_id}",
        "",
        "## Layout",
        "",
        f"Tables with ≥ {SHARD_MIN_ROWS:,} rows are a directory of ZSTD Parquet "
        f"shards (~{FILE_SIZE_BYTES} each). Smaller tables are a single "
        "`Table.parquet`. UUID columns are exported as VARCHAR.",
        "",
        "```sql",
        "INSTALL parquet; LOAD parquet;",
        "SELECT * FROM 'Charities.parquet' LIMIT 5;",
        "SELECT COUNT(*) FROM 'medicare_provider_spending/*.parquet';",
        "```",
        "",
        "## Tables",
        "",
        "| Table | Rows | Files | What |",
        "|---|---:|---|---|",
    ]
    for c in included:
        blurb = TABLE_BLURBS.get(c["name"], "")
        files = "dir" if c["sharded"] else "1 parquet"
        lines.append(f"| `{c['name']}` | {c['rows']:,} | {files} | {blurb} |")
    lines.extend(
        [
            "",
            "## Not uploaded",
            "",
            "Ops / scratch / raw extracts stay local:",
            "",
            "| Table | Why |",
            "|---|---|",
        ]
    )
    for s in skipped:
        lines.append(f"| `{s['name']}` | {s['reason']} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `Addresses` is polymorphic (`owner_id` + `address_type`). "
            "Types include charity, officer, contractor, grant, medicare, "
            "dot_carrier, ofac_sanction, and fec_committee.",
            "- `medicare_provider_spending` is the line grain (~230M). "
            "Use `medicare_provider_rollup` / `medicare_provider_hcpcs` for cheap totals.",
            "- FEC contributor / spend / oppexp / candidate-spend rows are city+state+ZIP, "
            "not street. Only `fec_committees` has a real line 1.",
            "- `BMF` keeps IRS street fields; `IrsBmf` is the older street-stripped copy.",
            "- Full DDL: `schema_duckdb.sql`. Export inventory: `manifest.json`.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_tables(
    existing: list[str],
    include: set[str],
    exclude: set[str],
    only: list[str] | None,
) -> tuple[list[str], list[dict]]:
    skipped = []
    chosen = []
    if only:
        unknown = [t for t in only if t not in existing]
        if unknown:
            raise SystemExit(f"Unknown --tables: {', '.join(unknown)}")
        return only, skipped
    for name in existing:
        if name in exclude:
            skipped.append({"name": name, "reason": "excluded on CLI"})
            continue
        if name in SKIP_TABLES and name not in include:
            skipped.append({"name": name, "reason": SKIP_TABLES[name]})
            continue
        chosen.append(name)
    return chosen, skipped


def upload_path(
    api: HfApi,
    repo_id: str,
    out_dir: Path,
    local: Path,
    repo_path: str,
    token: str,
) -> None:
    """Upload one table. Sharded dirs must keep their table/ prefix on the Hub."""
    size = local_bytes(local)
    print(f"  ↑ {repo_path}  ({size / 1e9:.2f} GB)")
    if local.is_file():
        api.upload_file(
            path_or_fileobj=str(local),
            path_in_repo=repo_path,
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            commit_message=f"Add {repo_path}",
        )
        return
    if size >= LARGE_FOLDER_BYTES:
        upload_large_folder(
            repo_id=repo_id,
            folder_path=str(out_dir),
            repo_type="dataset",
            revision="main",
            num_workers=4,
            allow_patterns=[f"{local.name}/**"],
            print_report=False,
        )
        return
    upload_folder(
        folder_path=str(local),
        path_in_repo=repo_path,
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        commit_message=f"Add {repo_path}/",
    )


def prune_stale_remote(
    api: HfApi,
    repo_id: str,
    token: str,
    exported: list[dict],
    skipped: list[dict],
) -> None:
    try:
        info = api.dataset_info(repo_id)
    except Exception as exc:  # noqa: BLE001 — first upload has no repo files yet
        print(f"  skip prune ({exc})")
        return
    remote = {s.rfilename for s in (info.siblings or [])}
    keep_exact = {"README.md", "schema_duckdb.sql", "manifest.json", ".gitattributes"}
    keep_prefix = tuple(
        f"{c['name']}/" for c in exported if c.get("sharded")
    )
    keep_files = {
        f"{c['name']}.parquet" for c in exported if not c.get("sharded")
    }
    stale = []
    skip_names = {s["name"] for s in skipped}
    for path in sorted(remote):
        if path in keep_exact or path in keep_files:
            continue
        if any(path.startswith(p) for p in keep_prefix):
            continue
        if not path.endswith(".parquet"):
            continue
        stem = path.split("/", 1)[0].removesuffix(".parquet")
        # Drop old single-file copies of now-sharded tables, plus skipped tables.
        if stem in skip_names or any(c["name"] == stem and c.get("sharded") for c in exported):
            stale.append(path)
    if not stale:
        print("  no stale parquet to prune")
        return
    print(f"  prune {len(stale)} stale remote parquet")
    api.delete_files(
        repo_id=repo_id,
        repo_type="dataset",
        delete_patterns=stale,
        token=token,
        commit_message="Drop stale parquet replaced by shards / skipped tables",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=os.environ.get("IRS990_DB", DEFAULT_DB))
    p.add_argument("--out", default=DEFAULT_OUT, help="Local parquet directory")
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    p.add_argument("--tables", help="Comma-separated table list (skip discovery filter)")
    p.add_argument("--include", default="", help="Comma-separated SKIP_TABLES to force in")
    p.add_argument("--exclude", default="", help="Comma-separated extra tables to drop")
    p.add_argument("--dry-run", action="store_true", help="Print the plan and exit")
    p.add_argument("--export-only", action="store_true", help="Write parquet, do not upload")
    p.add_argument("--upload-only", action="store_true", help="Upload existing --out, no COPY")
    p.add_argument(
        "--keep-local",
        action="store_true",
        help="Do not delete a table's parquet after a successful upload",
    )
    return p.parse_args()


def csv_set(raw: str) -> set[str]:
    return {p.strip() for p in raw.split(",") if p.strip()}


def main() -> int:
    args = parse_args()
    token = os.getenv("HF_TOKEN")
    out_dir = Path(args.out)
    only = [t.strip() for t in args.tables.split(",")] if args.tables else None

    if not Path(args.db).exists():
        raise SystemExit(f"DB not found: {args.db}")

    print(f"DB  {args.db}")
    print(f"OUT {out_dir}")
    print(f"HF  {args.repo}")

    con = duckdb.connect(args.db, read_only=True)
    existing = list_tables(con)
    chosen, skipped = resolve_tables(
        existing, csv_set(args.include), csv_set(args.exclude), only
    )

    catalog = []
    print("\nPlan:")
    for name in existing:
        if name not in chosen:
            reason = next((s["reason"] for s in skipped if s["name"] == name), "skipped")
            print(f"  skip  {name:32} {reason}")
            continue
        rows = table_rows(con, name)
        sharded = dest_is_dir(rows)
        dest = table_dest(out_dir, name, rows)
        catalog.append(
            {
                "name": name,
                "rows": rows,
                "sharded": sharded,
                "dest": str(dest),
                "action": "export",
            }
        )
        kind = "dir " if sharded else "file"
        print(f"  {kind}  {name:32} {rows:>14,}  → {dest.name}")

    if args.dry_run:
        print(f"\n{len(catalog)} tables to export, {len(skipped)} skipped. Dry run.")
        return 0

    if args.upload_only and not args.export_only:
        if not token:
            raise SystemExit("HF_TOKEN is required for upload")
        create_repo(args.repo, repo_type="dataset", exist_ok=True, token=token)
        api = HfApi(token=token)
        upload_large_folder(
            repo_id=args.repo,
            folder_path=str(out_dir),
            repo_type="dataset",
            revision="main",
            num_workers=4,
        )
        print(f"Uploaded {out_dir} → https://huggingface.co/datasets/{args.repo}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    schema_src = Path(args.schema)
    if schema_src.exists():
        shutil.copy(schema_src, out_dir / "schema_duckdb.sql")
    write_readme(out_dir / "README.md", catalog, skipped, args.repo)
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "db": args.db,
                "generated": date.today().isoformat(),
                "tables": catalog,
                "skipped": skipped,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    api = None
    if not args.export_only:
        if not token:
            raise SystemExit("HF_TOKEN is required for upload (or pass --export-only)")
        create_repo(args.repo, repo_type="dataset", exist_ok=True, token=token)
        api = HfApi(token=token)
        for sidecar in ("README.md", "schema_duckdb.sql", "manifest.json"):
            api.upload_file(
                path_or_fileobj=str(out_dir / sidecar),
                path_in_repo=sidecar,
                repo_id=args.repo,
                repo_type="dataset",
                token=token,
                commit_message=f"Update {sidecar}",
            )

    for item in catalog:
        name = item["name"]
        dest = Path(item["dest"])
        print(f"\n→ {name} ({item['rows']:,})")
        export_table(con, name, dest, item["rows"])
        print(f"  wrote {local_bytes(dest) / 1e9:.2f} GB")
        if api is not None:
            repo_path = name if item["sharded"] else dest.name
            upload_path(api, args.repo, out_dir, dest, repo_path, token)
            if not args.keep_local:
                if dest.is_dir():
                    shutil.rmtree(dest)
                elif dest.exists():
                    dest.unlink()
                print("  released local copy")

    if api is not None:
        prune_stale_remote(api, args.repo, token, catalog, skipped)

    print(f"\nDone. https://huggingface.co/datasets/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
