#!/usr/bin/env python3
"""
consolidate_for_dot.py

Combines:
  - reviewed_state.json (exported from the browser review tool)
  - data/<slug>.json files (generated during report creation)

Into a flat carrier-level TSV suitable for DOT/insurance consumption.

Also computes key aggregates (cluster_count, total_carriers, power units)
that can be used to render cover letters.
"""

import argparse
import json
import csv
from pathlib import Path
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser(description="Consolidate reviewed clusters into DOT-ready carrier list")
    parser.add_argument("--data-dir", type=Path, required=True,
                        help="Path to the data/ folder containing <slug>.json files")
    parser.add_argument("--reviewed-json", type=Path, required=True,
                        help="Path to reviewed_state.json exported from the index page")
    parser.add_argument("--template-dir", type=Path, default=Path("templates"),
                        help="Directory containing the .mako cover letter templates")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="Where to write the output files")
    parser.add_argument("--output-tsv", type=Path, default=None,
                        help="Output TSV filename (default: dot_carrier_lookup_<date>.tsv)")
    args = parser.parse_args()

    if not args.reviewed_json.exists():
        print(f"ERROR: {args.reviewed_json} not found")
        return

    reviewed = json.loads(args.reviewed_json.read_text(encoding="utf-8"))

    all_rows = []
    cluster_count = 0
    total_carriers = 0
    total_active_pu = 0
    total_pu = 0

    for slug, review_info in reviewed.items():
        review_status = review_info.get("status")

        # Only include clusters marked as Sus (sus-dot or sus-ins)
        if review_status not in ("sus-dot", "sus-ins"):
            continue

        cluster_file = args.data_dir / f"{slug}.json"
        if not cluster_file.exists():
            print(f"Warning: {cluster_file} not found, skipping")
            continue

        cluster = json.loads(cluster_file.read_text(encoding="utf-8"))
        cluster_count += 1

        active_pu = cluster.get("active_power_units") or 0
        inactive_pu = cluster.get("inactive_power_units") or 0

        total_active_pu += active_pu
        total_pu += active_pu + inactive_pu

        # Flatten phone groups into individual carrier rows
        for pg in cluster.get("phone_groups", []):
            phone = pg.get("phone", "No Phone")

            for carrier in pg.get("active", []):
                total_carriers += 1
                dot = carrier.get("dot_number")
                all_rows.append({
                    "cluster_address": cluster.get("canonical_address"),
                    "slug": slug,
                    "dot_number": dot,
                    "searchcarriers_url": f"https://searchcarriers.com/company/{dot}" if dot else "",
                    "searchcarriers_map_url": f"https://searchcarriers.com/map/company/{dot}" if dot else "",
                    "motus_url": f"https://motus.dot.gov/customer/{dot}/account" if dot else "",
                    "legal_name": carrier.get("legal_name"),
                    "status_code": "A",
                    "power_units": carrier.get("power_units") or 0,
                    "phone": phone,
                    "review_status": review_info.get("status"),
                    "review_notes": review_info.get("notes", ""),
                    "maps_url": f"https://www.google.com/maps/search/?api=1&query={cluster.get('canonical_address', '').replace(' ', '+')}&zoom=17"
                })

            for carrier in pg.get("inactive", []):
                total_carriers += 1
                dot = carrier.get("dot_number")
                all_rows.append({
                    "cluster_address": cluster.get("canonical_address"),
                    "slug": slug,
                    "dot_number": dot,
                    "searchcarriers_url": f"https://searchcarriers.com/company/{dot}" if dot else "",
                    "searchcarriers_map_url": f"https://searchcarriers.com/map/company/{dot}" if dot else "",
                    "motus_url": f"https://motus.dot.gov/customer/{dot}/account" if dot else "",
                    "legal_name": carrier.get("legal_name"),
                    "status_code": "I",
                    "power_units": carrier.get("power_units") or 0,
                    "phone": phone,
                    "review_status": review_info.get("status"),
                    "review_notes": review_info.get("notes", ""),
                    "maps_url": f"https://www.google.com/maps/search/?api=1&query={cluster.get('canonical_address', '').replace(' ', '+')}&zoom=17"
                })

    if not all_rows:
        print("No carriers found in reviewed clusters.")
        return

    # Write flat carrier-level TSV
    if args.output_tsv is None:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        args.output_tsv = args.output_dir / f"dot_carrier_lookup_{date_str}.tsv"

    fieldnames = [
        "cluster_address", "slug", "dot_number",
        "searchcarriers_url", "searchcarriers_map_url", "motus_url",
        "legal_name", "status_code", "power_units", "phone",
        "review_status", "review_notes", "maps_url"
    ]

    with args.output_tsv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"✓ Wrote {len(all_rows)} carrier rows to {args.output_tsv}")

    # === Render cover letters using Mako ===
    try:
        from mako.lookup import TemplateLookup

        lookup = TemplateLookup(directories=[str(args.template_dir)], output_encoding="utf-8")

        context = {
            "cluster_count": cluster_count,
            "total_carriers": total_carriers,
            "total_active_power_units": total_active_pu,
            "total_power_units": total_pu,
        }

        # DOT cover letter
        dot_template = lookup.get_template("DOT_Cover_Note.md.mako")
        dot_rendered = dot_template.render(**context)
        dot_out = args.output_dir / "DOT_Cover_Note.txt"
        dot_out.write_bytes(dot_rendered)
        print(f"✓ Wrote {dot_out}")

        # Insurance cover letter
        ins_template = lookup.get_template("Insurance_Cover_Note.md.mako")
        ins_rendered = ins_template.render(**context)
        ins_out = args.output_dir / "Insurance_Cover_Note.txt"
        ins_out.write_bytes(ins_rendered)
        print(f"✓ Wrote {ins_out}")

    except Exception as e:
        print(f"Warning: Could not render cover letters: {e}")

    # Print summary
    print("\n=== Summary ===")
    print(f"  Clusters reviewed      : {cluster_count}")
    print(f"  Total carriers         : {total_carriers:,}")
    print(f"  Active power units     : {total_active_pu:,}")
    print(f"  Total power units      : {total_pu:,}")


if __name__ == "__main__":
    main()