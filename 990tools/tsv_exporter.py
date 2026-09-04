#!/usr/bin/env python3
"""
tsv_exporter.py - TSV export functionality for IRS 990 data

This module handles exporting processed data to TSV files for analysis.
"""

from pathlib import Path
from typing import List, Tuple

from database_operations import DatabaseOperations


class TSVExporter:
    """Handles TSV export operations"""

    def __init__(self, db_ops: DatabaseOperations, final_dir: str):
        self.db_ops = db_ops
        self.final_dir = Path(final_dir)

    def export_final_tsvs(self):
        """Export final TSV files (step 11)"""
        print("Exporting final TSV files")

        # Ensure latest charities are selected
        self.db_ops.create_latest_charities_table()

        # Export charities
        self._export_charities_tsv()

        # Export grants
        self._export_grants_tsv()

        # Export contractors
        self._export_contractors_tsv()

        # Export political contributions
        self._export_political_contributions_tsv()

        print("TSV export complete")

    def _export_charities_tsv(self):
        """Export charities to TSV"""
        charities = self.db_ops.get_latest_charities_for_export()

        output_path = self.final_dir / "charities_latest.tsv"
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            header = [
                "tax_year", "filer_ein", "filer_name", "receipt_amt", "govt_amt", "contrib_amt",
                "org_type", "total_exp", "prog_exp", "travel_amt", "conferences_amt",
                "officer_comp", "comp_pct", "comp_ptile", "travel_pct", "travel_ptile",
                "conferences_pct", "conferences_ptile", "grants_pct", "grants_ptile",
                "foreign_expenses_pct", "foreign_expenses_ptile", "grift_ratio",
                "total_assets", "form_type", "denominator", "foreign_office", "foreign_expenses",
                "grants_to_others", "domestic_misrep_flag", "xml_name"
            ]
            f.write('\t'.join(header) + '\n')

            # Write data rows
            for row in charities:
                # Convert None to empty string and escape tabs/newlines
                safe_row = []
                for value in row:
                    if value is None:
                        safe_row.append('')
                    else:
                        # Escape tabs and newlines
                        str_value = str(value).replace('\t', '\\t').replace('\n', '\\n')
                        safe_row.append(str_value)
                f.write('\t'.join(safe_row) + '\n')

        print(f"Exported {len(charities)} charities to {output_path}")

    def _export_grants_tsv(self):
        """Export grants to TSV"""
        grants = self.db_ops.get_grants_for_export()

        output_path = self.final_dir / "grants_latest.tsv"
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            header = [
                "filer_ein", "filer_name", "grant_ein", "grant_amt", "tax_year",
                "filer_colocator", "grantee_colocator"
            ]
            f.write('\t'.join(header) + '\n')

            # Write data rows
            for row in grants:
                # Convert None to empty string and escape tabs/newlines
                safe_row = []
                for value in row:
                    if value is None:
                        safe_row.append('')
                    else:
                        # Escape tabs and newlines
                        str_value = str(value).replace('\t', '\\t').replace('\n', '\\n')
                        safe_row.append(str_value)
                f.write('\t'.join(safe_row) + '\n')

        print(f"Exported {len(grants)} grants to {output_path}")

    def _export_contractors_tsv(self):
        """Export contractors to TSV"""
        contractors = self.db_ops.get_contractors_for_export()

        output_path = self.final_dir / "contractors_latest.tsv"
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            header = [
                "filer_ein", "name", "amount", "ein", "address", "zip_code",
                "po_box", "tax_year", "colocator"
            ]
            f.write('\t'.join(header) + '\n')

            # Write data rows
            for row in contractors:
                # Convert None to empty string and escape tabs/newlines
                safe_row = []
                for value in row:
                    if value is None:
                        safe_row.append('')
                    else:
                        # Escape tabs and newlines
                        str_value = str(value).replace('\t', '\\t').replace('\n', '\\n')
                        safe_row.append(str_value)
                f.write('\t'.join(safe_row) + '\n')

        print(f"Exported {len(contractors)} contractors to {output_path}")

    def _export_political_contributions_tsv(self):
        """Export political contributions to TSV"""
        contributions = self.db_ops.get_political_contributions_for_export()

        output_path = self.final_dir / "political_contributions_latest.tsv"
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            header = [
                "filer_ein", "recipient", "amount", "recipient_address",
                "recipient_zip", "recipient_po_box", "tax_year", "colocator"
            ]
            f.write('\t'.join(header) + '\n')

            # Write data rows
            for row in contributions:
                # Convert None to empty string and escape tabs/newlines
                safe_row = []
                for value in row:
                    if value is None:
                        safe_row.append('')
                    else:
                        # Escape tabs and newlines
                        str_value = str(value).replace('\t', '\\t').replace('\n', '\\n')
                        safe_row.append(str_value)
                f.write('\t'.join(safe_row) + '\n')

        print(f"Exported {len(contributions)} political contributions to {output_path}")