#!/usr/bin/env python3
"""
phone_book_cream_extractor.py

Fast, pure-traditional 100% exact-core "phone book" cream skimmer for no-EIN grantee names.

- Loads good sources (BMF + charity/ein variants).
- Deduplicates good names **BY NAME** (not by EIN) so that multiple canonical variants
  for the *same* EIN are kept as independent match targets (e.g. "BILL & MELINDA GATES FOUNDATION"
  and "GATES FOUNDATION" both stay, so queries using either short or long form can exact-match).
- Builds a phone book of sig-seq tuples (after clean_name_for_matching + get_sig_seq).
- For each no-EIN name in the input TSV:
  - Clean it.
  - Compute its sig seq.
  - If the sig seq has an exact good sig as a contiguous **prefix** (trailing crap/junk) or
    **suffix** (leading crap/junk), this is a 100% confident traditional match to that EIN.
    The core good name is literally present as a block of significant tokens.
- No RapidFuzz, no inverted index, no neighbor scan, no AI. Just sig extraction + set lookup.
- This skins the "cream" at the top (very high hit rate on real data). Life-changing volume of direct 100% easy assignments.

Usage examples:
  # Broad distinct list
  python phone_book_cream_extractor.py \
      --no-ein distinct_grantee_names_clean.tsv \
      --output cream_distinct_exact.tsv \
      --report-stats

  # The active by_dollars list (the one being chunk-rebuilt)
  python phone_book_cream_extractor.py \
      --no-ein pure_no_ein_by_dollars.tsv \
      --output cream_by_dollars_exact.tsv

  # A high-value list
  python phone_book_cream_extractor.py \
      --no-ein pure_no_ein_high_value_1M.tsv \
      --output cream_1M_exact.tsv

Output TSV has all original columns + matched_ein + matched_good_name (the core that matched).

You can then use the output to pre-assign in your cleaned_easy or for other pipelines.
The remaining non-cream rows still need the full traditional (RF + neighbor) or AI path.

See also: the integration of find_perfect_core_ein into rebuild_einless_cleaned.py
for using this as an ultra-fast pre-filter inside the normal rebuild (most rows become
instant 100-score easy; only the real tail does the heavy retrieve).

Correct dedup-by-name fix applied per user note (2026-06).
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, ".")

from bmf_fuzzy_candidate_matcher import (
    load_bmf,
    get_phonebook_sig_seq,
    clean_name_for_matching,
    build_exact_core_phonebook,
    find_perfect_core_ein,
    is_big_pharmaish,
    is_plausible_org_name,
)


def main():
    parser = argparse.ArgumentParser(
        description="Phone-book exact-core cream extractor for 100 percent traditional no-EIN matches."
    )
    parser.add_argument("--bmf", default="bmf_analysis.tsv", help="BMF source of truth")
    parser.add_argument(
        "--variants", default="ein_name_variants.tsv", help="Charity / EIN variants source"
    )
    parser.add_argument(
        "--no-ein",
        required=True,
        help="No-EIN input TSV (e.g. pure_no_ein_by_dollars.tsv or distinct_grantee_names_clean.tsv). First column or 'grantee_name' is used as the name.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output TSV for the exact 100 percent cream matches (original cols + matched_ein + matched_good_name)",
    )
    parser.add_argument(
        "--report-stats", action="store_true", help="Print final stats at end"
    )
    args = parser.parse_args()

    print("Loading good sources (BMF + variants)...")
    bmf = load_bmf(args.bmf)
    variants = []
    if Path(args.variants).exists():
        variants = load_bmf(args.variants)
    print(f"  BMF records: {len(bmf):,}")
    print(f"  Variant records: {len(variants):,}")

    sig_to_ein = build_exact_core_phonebook(bmf, variants)
    print(f"  Phone book: {len(sig_to_ein):,} unique good sig-seqs (deduped by name)")

    # Also keep a sig -> good_name map for the output (the core that was matched)
    # Rebuild a minimal name->ein and then sig->name (using the same dedup-by-name logic)
    name_to_ein = {}
    for rec in bmf + variants:
        ein = rec.get("ein", "").strip()
        nm = rec.get("name", "").strip()
        if ein and nm and nm not in name_to_ein:
            name_to_ein[nm] = ein

    sig_to_good_name = {}
    for nm, ein in name_to_ein.items():
        cleaned = clean_name_for_matching(nm)
        seq = tuple(get_phonebook_sig_seq(cleaned or nm))
        if seq and seq not in sig_to_good_name:
            sig_to_good_name[seq] = nm

    print(f"  Sig->good_name map: {len(sig_to_good_name):,} entries")

    print(f"Processing no-EIN file: {args.no_ein} ...")
    total = 0
    cream = 0

    # Determine name column
    with open(args.no_ein, newline="", encoding="utf-8") as inf:
        reader = csv.DictReader(inf, delimiter="\t")
        if not reader.fieldnames:
            print("ERROR: no header in no-ein file")
            sys.exit(1)
        name_col = (
            "grantee_name"
            if "grantee_name" in reader.fieldnames
            else reader.fieldnames[0]
        )
        out_fieldnames = list(reader.fieldnames) + ["matched_ein", "matched_good_name"]

        with open(args.output, "w", newline="", encoding="utf-8") as outf:
            writer = csv.DictWriter(
                outf, fieldnames=out_fieldnames, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()

            for row in reader:
                total += 1
                if total % 100000 == 0:
                    pct = 100 * cream / total if total else 0
                    print(f"  {total:,} processed, cream so far {cream:,} ({pct:.2f}%)")

                name = row.get(name_col, "").strip()
                if not name:
                    writer.writerow({**row, "matched_ein": "", "matched_good_name": ""})
                    continue

                # Filter big_pharma/redaction and non-plausible *before* cream.
                # This prevents never-ein redaction names (SCHEDULE, VARIOUS, SUBRECIPIENTS, etc.)
                # from ever "creaming" to a real org EIN. They should stay unmapped or go to synthetic.
                # Check big on *cleaned* (after stripping Attn/SEE junk etc) so that "Real Foundation Attn person"
                # still creams its core; pure redaction names stay blocked.
                cleaned = clean_name_for_matching(name)
                if is_big_pharmaish(cleaned) or not is_plausible_org_name(cleaned or name):
                    row["matched_ein"] = ""
                    row["matched_good_name"] = ""
                    writer.writerow(row)
                    continue

                ein = find_perfect_core_ein(name, sig_to_ein)
                if ein:
                    cream += 1
                    qsig = tuple(get_phonebook_sig_seq(cleaned or name))
                    good_nm = sig_to_good_name.get(qsig, "")
                    if not good_nm:
                        # Hygiene: for prefix/suffix hits (qsig longer than the core good sig),
                        # walk the same subs find_perfect did and pick the first good name whose
                        # sig matched (so "SEE ATTACHMENT C" gets good="See attachment" etc.).
                        for i in range(len(qsig), 0, -1):
                            sub = tuple(qsig[:i])
                            if sub in sig_to_good_name:
                                good_nm = sig_to_good_name[sub]
                                break
                        if not good_nm:
                            for i in range(len(qsig)):
                                sub = tuple(qsig[i:])
                                if sub in sig_to_good_name:
                                    good_nm = sig_to_good_name[sub]
                                    break
                    row["matched_ein"] = ein
                    row["matched_good_name"] = good_nm
                    writer.writerow(row)
                else:
                    # non-cream: we still write the row with empty match fields
                    # (or you can choose to only output cream; here we output all for traceability)
                    row["matched_ein"] = ""
                    row["matched_good_name"] = ""
                    writer.writerow(row)

    print(f"\n=== DONE ===")
    print(f"Total rows in {args.no_ein}: {total:,}")
    print(f"100% exact core cream matches: {cream:,} ({100*cream/total:.2f}%)")
    print(f"Wrote full output (cream + non-cream rows with match columns) to: {args.output}")

    if args.report_stats:
        print("\nStats:")
        print(f"  Cream rate: {100*cream/total:.2f}%")
        print(f"  Non-cream that will need full traditional/AI: {total - cream:,}")


if __name__ == "__main__":
    main()
