#!/usr/bin/env python3
"""
stats_processor.py - Statistics generation and reporting for IRS 990 data processing

This module handles all statistics generation, analysis, and reporting functionality
for the IRS 990 processor.
"""

import os
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from mako.template import Template
from base_processor import BaseProducer
from pending_database_context import PendingDatabaseContext
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType

# Tables the stats report knows about. Missing tables show count 0 (not an error).
KNOWN_TABLES = (
    'ZipFiles', 'XmlFiles', 'Charities', 'Officers', 'Grants',
    'Contractors', 'PoliticalContributions', 'Addresses', 'Geocoding',
    'BMF', 'IrsBmf', 'Backfill', 'Zips',
    'fec_committees', 'fec_individual_contributions', 'fec_committee_transactions',
    'fec_candidate_spendings', 'fec_operating_expenditures',
    'medicare_providers', 'medicare_provider_spending',
    'sanctioned_entities', 'sanctioned_names', 'sanctioned_identifiers', 'sanctioned_programs',
    'dot_carriers',
)


def escape_newlines(data):
    """Recursively escape newlines in all strings within data structures"""
    if isinstance(data, str):
        return data.replace('\n', '\\n').replace('|','\\|')
    elif isinstance(data, (list, tuple)):
        return type(data)(escape_newlines(item) for item in data)
    elif isinstance(data, dict):
        return {key: escape_newlines(value) for key, value in data.items()}
    else:
        return data


class StatsProcessor:
    """Handles statistics generation and reporting for IRS 990 data"""

    def __init__(self, db_ops):
        """
        Initialize StatsProcessor with database operations instance

        Args:
            db_ops: DatabaseOperations instance for database access
        """
        self.db_ops = db_ops

    def _table_exists(self, table: str) -> bool:
        try:
            row = self.db_ops.execute_query(
                "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1",
                (table,),
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def _safe_scalar(self, sql: str, params: tuple = (), default: Any = 0) -> Any:
        try:
            row = self.db_ops.execute_query(sql, params).fetchone()
            return row[0] if row and row[0] is not None else default
        except Exception:
            return default

    def _safe_fetchall(self, sql: str, params: tuple = ()) -> list:
        try:
            return self.db_ops.execute_query(sql, params).fetchall()
        except Exception:
            return []

    def generate_stats_report(self, step_name: str, notes: str = "") -> str:
        """Generate a statistics report for the current database state"""
        from datetime import datetime
        from mako.template import Template
        import os
        from logging_utils import log_info, log_error, log_warning

        log_info(f"Starting stats report generation for step: {step_name}")

        try:
            # Check if template file exists and is readable
            template_path = os.path.join(os.path.dirname(__file__), 'stats_template.mako')
            if not os.path.exists(template_path):
                log_error(f"Stats template file not found: {template_path}")
                raise FileNotFoundError(f"Template file missing: {template_path}")

            if not os.access(template_path, os.R_OK):
                log_error(f"Stats template file not readable: {template_path}")
                raise PermissionError(f"Template file not readable: {template_path}")

            log_info(f"Template file verified: {template_path}")

            # Get table counts and summaries
            log_info("Getting table counts...")
            table_counts = self.get_table_counts()
            log_info(f"Table counts retrieved: {len(table_counts)} tables")

            log_info("Getting table summaries...")
            table_summaries = self.get_table_summaries()
            log_info(f"Table summaries retrieved: {len(table_summaries)} tables")

            total_records = sum(table_counts.values())
            log_info(f"Total records across all tables: {total_records}")

            # Get XmlFiles specific statistics
            log_info("Getting XML files group counts...")
            xml_group_counts = self.get_xml_files_group_counts()
            log_info("Getting XML files histogram...")
            xml_histogram = self.get_xml_files_histogram()

            # Get comprehensive analysis for each major table
            log_info("Getting charities analysis...")
            charities_analysis = self.get_charities_analysis()
            log_info("Getting officers analysis...")
            officers_analysis = self.get_officers_analysis()
            log_info("Getting grants analysis...")
            grants_analysis = self.get_grants_analysis()
            log_info("Getting contractors analysis...")
            contractors_analysis = self.get_contractors_analysis()
            log_info("Getting political contributions analysis...")
            political_contributions_analysis = self.get_political_contributions_analysis()
            log_info("Getting addresses analysis...")
            addresses_analysis = self.get_addresses_analysis()
            log_info("Getting addresses deduplication analysis...")
            addresses_deduplication_analysis = self.get_addresses_deduplication_analysis()
            log_info("Getting addresses colocator analysis...")
            addresses_colocator_analysis = self.get_addresses_colocator_analysis()
            log_info("Getting geocoding status analysis...")
            geocoding_status_analysis = self.get_geocoding_status_analysis()
            log_info("Getting external reference analysis...")
            external_reference_analysis = self.get_external_reference_analysis()
            log_info("Getting address type breakdown...")
            address_type_analysis = self.get_address_type_analysis()
            log_info("Getting shared-canonical (colocation) analysis...")
            shared_canonical_analysis = self.get_shared_canonical_analysis()

            # Prepare template data
            template_data = {
                'step_name': step_name,
                'timestamp': datetime.now().isoformat(),
                'db_path': self.db_ops.db_path,
                'table_counts': table_counts,
                'table_summaries': table_summaries,
                'total_records': total_records,
                'xml_group_counts': xml_group_counts,
                'xml_histogram': xml_histogram,
                'charities_analysis': charities_analysis,
                'officers_analysis': officers_analysis,
                'grants_analysis': grants_analysis,
                'contractors_analysis': contractors_analysis,
                'political_contributions_analysis': political_contributions_analysis,
                'addresses_analysis': addresses_analysis,
                'addresses_deduplication_analysis': addresses_deduplication_analysis,
                'addresses_colocator_analysis': addresses_colocator_analysis,
                'geocoding_status_analysis': geocoding_status_analysis,
                'external_reference_analysis': external_reference_analysis,
                'address_type_analysis': address_type_analysis,
                'shared_canonical_analysis': shared_canonical_analysis,
                'notes': notes or "No additional notes."
            }

            # Escape newlines in all string data to prevent markdown confusion
            template_data = escape_newlines(template_data)

            # Load and render template
            log_info("Loading and rendering template...")
            with open(template_path, 'r') as f:
                template_content = f.read()

            template = Template(template_content)
            report_content = template.render(**template_data)
            log_info("Template rendered successfully")

            # Write report to file
            report_filename = f"stats_{step_name}.md"
            log_info(f"Writing report to file: {report_filename}")
            with open(report_filename, 'w') as f:
                f.write(report_content)

            log_info(f"Stats report generation completed successfully: {report_filename}")
            return report_filename  # type: ignore

        except Exception as e:
            log_error(f"Failed to generate stats report for step {step_name}: {e}", exc_info=True)
            raise

    def get_table_counts(self) -> dict:
        """Get row counts for known tables; missing tables report 0."""
        counts = {}
        for table in KNOWN_TABLES:
            if self._table_exists(table):
                counts[table] = int(self._safe_scalar(f"SELECT COUNT(*) FROM {table}", default=0))
            else:
                counts[table] = 0
        return counts

    def get_table_summaries(self) -> dict:
        """Get SUMMARIZE data for tables that exist."""
        summaries = {}
        for table in KNOWN_TABLES:
            if not self._table_exists(table):
                summaries[table] = []
                continue
            try:
                result = self.db_ops.execute_query(f"SUMMARIZE {table}")
                summaries[table] = result.fetchall()
            except Exception:
                summaries[table] = []
        return summaries

    def get_xml_files_group_counts(self) -> Dict[str, List[Tuple]]:
        """Get group by counts for XmlFiles columns"""
        empty = {
            'tax_year': [], 'form_type': [], 'processed': [],
            'processing_version': [], 'error_message_prefix': [],
        }
        if not self._table_exists('XmlFiles'):
            return empty

        group_counts = {}

        # Group by tax_year
        result = self.db_ops.execute_query("""
            SELECT tax_year, COUNT(*) as count
            FROM XmlFiles
            GROUP BY tax_year
            ORDER BY tax_year
        """).fetchall()
        group_counts['tax_year'] = result

        # Group by form_type
        result = self.db_ops.execute_query("""
            SELECT form_type, COUNT(*) as count
            FROM XmlFiles
            GROUP BY form_type
            ORDER BY form_type
        """).fetchall()
        group_counts['form_type'] = result

        # Group by processed
        result = self.db_ops.execute_query("""
            SELECT processed, COUNT(*) as count
            FROM XmlFiles
            GROUP BY processed
            ORDER BY processed
        """).fetchall()
        group_counts['processed'] = result

        # Group by processing_version
        result = self.db_ops.execute_query("""
            SELECT processing_version, COUNT(*) as count
            FROM XmlFiles
            GROUP BY processing_version
            ORDER BY processing_version
        """).fetchall()
        group_counts['processing_version'] = result

        # Group by error_message prefix (first 50 characters)
        result = self.db_ops.execute_query("""
            SELECT
                CASE
                    WHEN error_message IS NULL THEN 'NULL'
                    WHEN LENGTH(error_message) <= 50 THEN error_message
                    ELSE SUBSTRING(error_message, 1, 50) || '...'
                END as error_prefix,
                COUNT(*) as count
            FROM XmlFiles
            GROUP BY error_prefix
            ORDER BY count DESC
        """).fetchall()
        group_counts['error_message_prefix'] = result
        # Note: Newlines are now escaped globally in template_data

        return group_counts

    def get_quartile_bins(self, table: str, column: str) -> Tuple[List[float], float]:
        """Calculate variable-width bin edges for histogram with 5 equal-width sub-bins per quartile"""
        try:
            # Get quartiles and min/max
            result = self.db_ops.execute_query(f"""
                SELECT
                    MIN({column}) as min_val,
                    quantile_disc({column}, 0.25) as q1,
                    quantile_disc({column}, 0.5) as q2,
                    quantile_disc({column}, 0.75) as q3,
                    MAX({column}) as max_val
                FROM {table}
                WHERE {column} IS NOT NULL
            """).fetchone()

            if result and len(result) >= 5:
                min_val, q1, q2, q3, max_val = result
                # Create 20 bins: 5 equal-width sub-bins within each quartile range
                bins = []
                ranges = [(min_val, q1), (q1, q2), (q2, q3), (q3, max_val)]
                for start, end in ranges:
                    if start < end:  # Avoid division by zero if start == end
                        width = (end - start) / 5
                        for i in range(5):
                            bin_upper = start + (i + 1) * width
                            bins.append(bin_upper)
                # Remove duplicates to avoid empty bins
                bins = list(dict.fromkeys(bins))
                return bins, min_val
        except Exception:
            pass
        return [], 0.0

    def get_xml_files_histogram(self) -> List[Dict]:
        """Get histogram data for XmlFiles.file_size using quartile-based bins"""
        try:
            bins, min_val = self.get_quartile_bins('XmlFiles', 'file_size')
            if len(bins) >= 2:
                # Create histogram with quartile bins and get total count
                hist_result = self.db_ops.execute_query("""
                    SELECT histogram(file_size, ?) as hist,
                           (SELECT COUNT(*) FROM XmlFiles WHERE file_size IS NOT NULL) as total
                    FROM XmlFiles WHERE file_size IS NOT NULL
                """, (bins,)).fetchone()
                if hist_result and hist_result[0]:
                    hist_map = hist_result[0]
                    total = hist_result[1]
                    # Create bin data with bin_lower, bin_upper, bin_width
                    bin_data = []
                    prev_upper = min_val
                    for bin_upper in sorted(hist_map.keys()):
                        count = hist_map[bin_upper]
                        bin_lower = prev_upper
                        bin_width = bin_upper - bin_lower
                        bin_data.append({
                            'bin_lower': bin_lower,
                            'bin_upper': bin_upper,
                            'bin_width': bin_width,
                            'count': count,
                            'pct': (count / total * 100) if total > 0 else 0
                        })
                        prev_upper = bin_upper
                    return bin_data
            return []
        except Exception:
            # Fallback if histogram fails
            return []

    def get_charities_analysis(self) -> Dict[str, Any]:
        """Get comprehensive analysis for Charities table"""
        if not self._table_exists('Charities'):
            return {
                'tax_year_counts': [], 'org_type_counts': [], 'form_type_counts': [],
                'histograms': {},
            }

        analysis = {}

        # Tax year group by
        result = self.db_ops.execute_query("""
            SELECT tax_year, COUNT(*) as count
            FROM Charities
            GROUP BY tax_year
            ORDER BY tax_year
        """).fetchall()
        analysis['tax_year_counts'] = result

        # Org type counts
        result = self.db_ops.execute_query("""
            SELECT org_type, COUNT(*) as count
            FROM Charities
            GROUP BY org_type
            ORDER BY count DESC
        """).fetchall()
        analysis['org_type_counts'] = result

        # Form type counts
        result = self.db_ops.execute_query("""
            SELECT form_type, COUNT(*) as count
            FROM Charities
            GROUP BY form_type
            ORDER BY count DESC
        """).fetchall()
        analysis['form_type_counts'] = result

        # Histograms for Double columns (only when min != max)
        double_columns = ['receipt_amt', 'govt_amt', 'contrib_amt', 'total_exp', 'prog_exp',
                          'travel_amt', 'conferences_amt', 'officer_comp', 'comp_pct', 'comp_ptile',
                          'comp_ptile_value', 'travel_pct', 'travel_ptile', 'travel_ptile_value',
                          'conferences_pct', 'conferences_ptile', 'conferences_ptile_value',
                          'grants_pct', 'grants_ptile', 'grants_ptile_value', 'foreign_expenses_pct',
                          'foreign_expenses_ptile', 'foreign_expenses_ptile_value', 'grift_ratio',
                          'total_assets', 'denominator', 'foreign_expenses', 'grants_to_others', 'grift']
        analysis['histograms'] = {}

        for col in double_columns:
            bins, min_val = self.get_quartile_bins('Charities', col)
            if len(bins) >= 2:
                # Create histogram with quartile bins and get total count
                hist_result = self.db_ops.execute_query(f"""
                    SELECT histogram({col}, ?) as hist,
                           (SELECT COUNT(*) FROM Charities WHERE {col} IS NOT NULL) as total
                    FROM Charities WHERE {col} IS NOT NULL
                """, (bins,)).fetchone()
                if hist_result and hist_result[0]:
                    hist_map = hist_result[0]
                    total = hist_result[1]
                    # Create bin data with bin_lower, bin_upper, bin_width
                    bin_data = []
                    prev_upper = min_val
                    for bin_upper in sorted(hist_map.keys()):
                        count = hist_map[bin_upper]
                        bin_lower = prev_upper
                        bin_width = bin_upper - bin_lower
                        bin_data.append({
                            'bin_lower': bin_lower,
                            'bin_upper': bin_upper,
                            'bin_width': bin_width,
                            'count': count,
                            'pct': (count / total * 100) if total > 0 else 0
                        })
                        prev_upper = bin_upper
                    analysis['histograms'][col] = bin_data

        return analysis

    def get_officers_analysis(self) -> Dict[str, Any]:
        """Get analysis for Officers table"""
        if not self._table_exists('Officers'):
            return {'top_last_names': []}

        analysis = {}

        # Top 10 last names
        result = self.db_ops.execute_query("""
            SELECT last_name, COUNT(*) as count
            FROM Officers
            GROUP BY last_name
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        analysis['top_last_names'] = result

        return analysis

    def get_grants_analysis(self) -> Dict[str, Any]:
        """Get analysis for Grants table"""
        if not self._table_exists('Grants'):
            return {}

        analysis = {}

        # Grant amount histogram using quartile bins
        bins, min_val = self.get_quartile_bins('Grants', 'grant_amt')
        if len(bins) >= 2:
            hist_result = self.db_ops.execute_query("""
                SELECT histogram(grant_amt, ?) as hist,
                       (SELECT COUNT(*) FROM Grants WHERE grant_amt IS NOT NULL) as total
                FROM Grants WHERE grant_amt IS NOT NULL
            """, (bins,)).fetchone()
            if hist_result and hist_result[0]:
                hist_map = hist_result[0]
                total = hist_result[1]
                # Create bin data with bin_lower, bin_upper, bin_width
                bin_data = []
                prev_upper = min_val
                for bin_upper in sorted(hist_map.keys()):
                    count = hist_map[bin_upper]
                    bin_lower = prev_upper
                    bin_width = bin_upper - bin_lower
                    bin_data.append({
                        'bin_lower': bin_lower,
                        'bin_upper': bin_upper,
                        'bin_width': bin_width,
                        'count': count,
                        'pct': (count / total * 100) if total > 0 else 0
                    })
                    prev_upper = bin_upper
                analysis['grant_amt_histogram'] = bin_data

        return analysis

    def get_contractors_analysis(self) -> Dict[str, Any]:
        """Get analysis for Contractors table"""
        if not self._table_exists('Contractors'):
            return {}

        analysis = {}

        # Amount histogram using quartile bins
        bins, min_val = self.get_quartile_bins('Contractors', 'amount')
        if len(bins) >= 2:
            hist_result = self.db_ops.execute_query("""
                SELECT histogram(amount, ?) as hist,
                       (SELECT COUNT(*) FROM Contractors WHERE amount IS NOT NULL) as total
                FROM Contractors WHERE amount IS NOT NULL
            """, (bins,)).fetchone()
            if hist_result and hist_result[0]:
                hist_map = hist_result[0]
                total = hist_result[1]
                # Create bin data with bin_lower, bin_upper, bin_width
                bin_data = []
                prev_upper = min_val
                for bin_upper in sorted(hist_map.keys()):
                    count = hist_map[bin_upper]
                    bin_lower = prev_upper
                    bin_width = bin_upper - bin_lower
                    bin_data.append({
                        'bin_lower': bin_lower,
                        'bin_upper': bin_upper,
                        'bin_width': bin_width,
                        'count': count,
                        'pct': (count / total * 100) if total > 0 else 0
                    })
                    prev_upper = bin_upper
                analysis['amount_histogram'] = bin_data

        return analysis

    def get_political_contributions_analysis(self) -> Dict[str, Any]:
        """Get analysis for PoliticalContributions table"""
        if not self._table_exists('PoliticalContributions'):
            return {}

        analysis = {}

        # Amount histogram using quartile bins
        bins, min_val = self.get_quartile_bins('PoliticalContributions', 'amount')
        if len(bins) >= 2:
            hist_result = self.db_ops.execute_query("""
                SELECT histogram(amount, ?) as hist,
                       (SELECT COUNT(*) FROM PoliticalContributions WHERE amount IS NOT NULL) as total
                FROM PoliticalContributions WHERE amount IS NOT NULL
            """, (bins,)).fetchone()
            if hist_result and hist_result[0]:
                hist_map = hist_result[0]
                total = hist_result[1]
                # Create bin data with bin_lower, bin_upper, bin_width
                bin_data = []
                prev_upper = min_val
                for bin_upper in sorted(hist_map.keys()):
                    count = hist_map[bin_upper]
                    bin_lower = prev_upper
                    bin_width = bin_upper - bin_lower
                    bin_data.append({
                        'bin_lower': bin_lower,
                        'bin_upper': bin_upper,
                        'bin_width': bin_width,
                        'count': count,
                        'pct': (count / total * 100) if total > 0 else 0
                    })
                    prev_upper = bin_upper
                analysis['amount_histogram'] = bin_data

        return analysis

    def get_addresses_analysis(self) -> Dict[str, Any]:
        """Get analysis for Addresses table"""
        if not self._table_exists('Addresses'):
            return {'top_states': [], 'top_zip_codes': []}

        analysis = {}

        # Top 10 states
        result = self.db_ops.execute_query("""
            SELECT state, COUNT(*) as count
            FROM Addresses
            WHERE state IS NOT NULL AND state != ''
            GROUP BY state
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        analysis['top_states'] = result

        # Top 10 zip codes
        result = self.db_ops.execute_query("""
            SELECT zip_code, COUNT(*) as count
            FROM Addresses
            WHERE zip_code IS NOT NULL AND zip_code != ''
            GROUP BY zip_code
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        analysis['top_zip_codes'] = result

        return analysis

    def get_addresses_deduplication_analysis(self) -> Dict[str, Any]:
        """Get analysis for address deduplication progress"""
        empty = {
            'total_canonical_addresses': 0, 'distinct_canonical_addresses': 0,
            'child_addresses': 0, 'master_addresses': 0, 'still_need_deduplication': 0,
            'total_addresses_processed': 0, 'unique_addresses_no_duplicates': 0,
        }
        if not self._table_exists('Addresses'):
            return empty

        analysis = {}

        # Total addresses with canonical_address
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as total_canonical
            FROM Addresses
            WHERE canonical_address IS NOT NULL AND canonical_address != ''
        """).fetchone()
        total_canonical = result[0] if result else 0
        analysis['total_canonical_addresses'] = total_canonical

        # Distinct canonical addresses
        result = self.db_ops.execute_query("""
            SELECT COUNT(DISTINCT canonical_address) as distinct_canonical
            FROM Addresses
            WHERE canonical_address IS NOT NULL AND canonical_address != ''
        """).fetchone()
        distinct_canonical = result[0] if result else 0
        analysis['distinct_canonical_addresses'] = distinct_canonical

        # Child addresses (those with master_id set)
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as child_addresses
            FROM Addresses
            WHERE master_id IS NOT NULL
        """).fetchone()
        child_addresses = result[0] if result else 0
        analysis['child_addresses'] = child_addresses

        # Master addresses (those without master_id that have at least one child)
        result = self.db_ops.execute_query("""
            SELECT COUNT(DISTINCT master_id) as master_addresses_with_children
            FROM Addresses
            WHERE master_id IS NOT NULL
        """).fetchone()
        master_addresses_with_children = result[0] if result else 0
        analysis['master_addresses'] = master_addresses_with_children

        # Still need to be done (canonical addresses that have duplicates but haven't been deduplicated)
        # This is the count of canonical addresses where there are multiple addresses with the same canonical_address
        # and at least one of them still has master_id IS NULL
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as still_need_deduplication
            FROM (
                SELECT canonical_address
                FROM Addresses
                WHERE canonical_address IS NOT NULL AND canonical_address != ''
                GROUP BY canonical_address
                HAVING COUNT(*) > 1
                    AND SUM(CASE WHEN master_id IS NULL THEN 1 ELSE 0 END) > 1
            )
        """).fetchone()
        still_need_done = result[0] if result else 0
        analysis['still_need_deduplication'] = still_need_done

        # Let's also add some validation metrics
        # Total addresses that have been processed (have canonical_address)
        analysis['total_addresses_processed'] = total_canonical

        # Addresses that are still unique (no duplicates to deduplicate)
        unique_addresses = distinct_canonical - still_need_done
        analysis['unique_addresses_no_duplicates'] = unique_addresses

        return analysis

    def get_addresses_colocator_analysis(self) -> Dict[str, Any]:
        """Get analysis for Address colocator field"""
        analysis = {}

        if not self._table_exists('Addresses'):
            analysis.update({
                'distinct_colocators': 0, 'po_count': 0, 'fa_count': 0, 'll_count': 0,
                'institution_count': 0, 'total_with_colocator': 0, 'neither_count': 0,
                'colocator_by_address_type': [], 'colocator_type_breakdown': [],
                'top_institution_prefixes': [],
            })
            return analysis

        try:
            # Distinct colocator values
            result = self.db_ops.execute_query("""
                SELECT COUNT(DISTINCT colocator) as distinct_colocators
                FROM Addresses
                WHERE colocator IS NOT NULL AND colocator != ''
            """).fetchone()
            distinct_colocators = result[0] if result else 0
            analysis['distinct_colocators'] = distinct_colocators

            # Count with 'PO%' prefix (Post Office)
            result = self.db_ops.execute_query("""
                SELECT COUNT(*) as po_count
                FROM Addresses
                WHERE colocator LIKE 'PO%'
            """).fetchone()
            po_count = result[0] if result else 0
            analysis['po_count'] = po_count

            # Count with 'FA%' prefix (Foreign Address)
            result = self.db_ops.execute_query("""
                SELECT COUNT(*) as fa_count
                FROM Addresses
                WHERE colocator LIKE 'FA%'
            """).fetchone()
            fa_count = result[0] if result else 0
            analysis['fa_count'] = fa_count

            # Count with 'LL%' prefix (Latitude/Longitude)
            result = self.db_ops.execute_query("""
                SELECT COUNT(*) as ll_count
                FROM Addresses
                WHERE colocator LIKE 'LL%'
            """).fetchone()
            ll_count = result[0] if result else 0
            analysis['ll_count'] = ll_count

            # Count with institution codes (STJUDE:, MET:, etc.)
            result = self.db_ops.execute_query("""
                SELECT COUNT(*) as institution_count
                FROM Addresses
                WHERE colocator LIKE '%:%' AND colocator NOT LIKE 'PO:%' AND colocator NOT LIKE 'FA:%' AND colocator NOT LIKE 'LL:%'
            """).fetchone()
            institution_count = result[0] if result else 0
            analysis['institution_count'] = institution_count

            # Top 10 institution prefixes
            result = self.db_ops.execute_query("""
                SELECT
                    SUBSTRING(colocator, 1, POSITION(':' IN colocator)) as prefix,
                    COUNT(*) as count
                FROM Addresses
                WHERE colocator LIKE '%:%' AND colocator NOT LIKE 'PO:%' AND colocator NOT LIKE 'FA:%' AND colocator NOT LIKE 'LL:%'
                GROUP BY prefix
                ORDER BY count DESC
                LIMIT 10
            """).fetchall()
            analysis['top_institution_prefixes'] = result or []

            # Total with colocator
            result = self.db_ops.execute_query("""
                SELECT COUNT(*) as total_with_colocator
                FROM Addresses
                WHERE colocator IS NOT NULL AND colocator != ''
            """).fetchone()
            total_with_colocator = result[0] if result else 0
            analysis['total_with_colocator'] = total_with_colocator

            # Neither (addresses with colocator but not matching any known pattern)
            neither_count = total_with_colocator - po_count - fa_count - ll_count - institution_count
            analysis['neither_count'] = neither_count

            # Add address type breakdown for colocator
            result = self.db_ops.execute_query("""
                SELECT address_type, COUNT(*) as count
                FROM Addresses
                WHERE colocator IS NOT NULL AND colocator != ''
                GROUP BY address_type
                ORDER BY count DESC
            """).fetchall()
            analysis['colocator_by_address_type'] = result or []

            # Top colocator patterns for analysis
            result = self.db_ops.execute_query("""
                SELECT
                    CASE
                        WHEN colocator LIKE 'PO%' THEN 'Post Office'
                        WHEN colocator LIKE 'FA%' THEN 'Foreign Address'
                        WHEN colocator LIKE 'LL%' THEN 'Geocoded (Lat/Long)'
                        WHEN colocator LIKE '%:%' THEN 'Institution Code'
                        ELSE 'Other'
                    END as colocator_type,
                    COUNT(*) as count
                FROM Addresses
                WHERE colocator IS NOT NULL AND colocator != ''
                GROUP BY colocator_type
                ORDER BY count DESC
            """).fetchall()
            analysis['colocator_type_breakdown'] = result or []

        except Exception as e:
            # If any query fails, set default values to prevent template errors
            analysis.update({
                'distinct_colocators': 0,
                'po_count': 0,
                'fa_count': 0,
                'll_count': 0,
                'institution_count': 0,
                'total_with_colocator': 0,
                'neither_count': 0,
                'colocator_by_address_type': [],
                'colocator_type_breakdown': []
            })

        return analysis

    def get_geocoding_status_analysis(self) -> Dict[str, Any]:
        """Get analysis for Geocoding table status distribution"""
        empty = {
            'geocoding_status_counts': [], 'total_geocoding_records': 0,
            'geocoded_with_coords': 0, 'attempted_records': 0,
        }
        if not self._table_exists('Geocoding'):
            return empty

        analysis = {}

        # Group by geocoding_status
        result = self.db_ops.execute_query("""
            SELECT geocoding_status, COUNT(*) as count
            FROM Geocoding
            GROUP BY geocoding_status
            ORDER BY count DESC
        """).fetchall()
        analysis['geocoding_status_counts'] = result

        # Total geocoding records
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as total_geocoding_records
            FROM Geocoding
        """).fetchone()
        analysis['total_geocoding_records'] = result[0] if result else 0

        # Records with latitude/longitude
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as geocoded_with_coords
            FROM Geocoding
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """).fetchone()
        analysis['geocoded_with_coords'] = result[0] if result else 0

        # Records with attempt_count > 0
        result = self.db_ops.execute_query("""
            SELECT COUNT(*) as attempted_records
            FROM Geocoding
            WHERE attempt_count > 0
        """).fetchone()
        analysis['attempted_records'] = result[0] if result else 0

        return analysis

    def get_external_reference_analysis(self) -> Dict[str, Any]:
        """Counts for FEC, Medicare, sanctions, and DOT tables (0 if not ingested yet)."""
        groups = {
            'fec': (
                'fec_committees', 'fec_individual_contributions', 'fec_committee_transactions',
                'fec_candidate_spendings', 'fec_operating_expenditures',
            ),
            'medicare': ('medicare_providers', 'medicare_provider_spending'),
            'sanctions': (
                'sanctioned_entities', 'sanctioned_names',
                'sanctioned_identifiers', 'sanctioned_programs',
            ),
            'dot': ('dot_carriers',),
        }
        analysis: Dict[str, Any] = {'groups': {}, 'ingested': {}}
        for group, tables in groups.items():
            counts = {}
            for table in tables:
                counts[table] = (
                    int(self._safe_scalar(f"SELECT COUNT(*) FROM {table}", default=0))
                    if self._table_exists(table) else 0
                )
            analysis['groups'][group] = counts
            analysis['ingested'][group] = any(v > 0 for v in counts.values())
        return analysis

    def get_address_type_analysis(self) -> Dict[str, Any]:
        """Breakdown of Addresses by address_type (includes new FEC/sanctions/DOT rows)."""
        if not self._table_exists('Addresses'):
            return {'by_type': [], 'new_source_types': []}

        by_type = self._safe_fetchall("""
            SELECT address_type, COUNT(*) AS count
            FROM Addresses
            GROUP BY address_type
            ORDER BY count DESC
        """)
        new_types = {
            'fec_committee', 'fec_individual_contribution', 'fec_committee_transaction',
            'fec_candidate_spending', 'fec_operating_expenditure',
            'ofac_sanction', 'dot_carrier_phy', 'dot_carrier_mail',
        }
        new_source_types = [(t, c) for t, c in by_type if t in new_types]
        return {'by_type': by_type, 'new_source_types': new_source_types}

    def get_shared_canonical_analysis(self) -> Dict[str, Any]:
        """Early fraud/colocation signals: shared canonicals across address types."""
        if not self._table_exists('Addresses'):
            return {
                'multi_type_canonicals': 0,
                'top_multi_type': [],
                'top_dot_stacked': [],
            }

        multi_type_count = int(self._safe_scalar("""
            SELECT COUNT(*) FROM (
                SELECT canonical_address
                FROM Addresses
                WHERE canonical_address IS NOT NULL AND TRIM(canonical_address) != ''
                GROUP BY canonical_address
                HAVING COUNT(DISTINCT address_type) > 1
            )
        """, default=0))

        top_multi_type = self._safe_fetchall("""
            SELECT
                canonical_address,
                LIST(DISTINCT address_type ORDER BY address_type) AS address_types,
                COUNT(*) AS address_rows,
                COUNT(DISTINCT address_type) AS type_count
            FROM Addresses
            WHERE canonical_address IS NOT NULL AND TRIM(canonical_address) != ''
            GROUP BY canonical_address
            HAVING COUNT(DISTINCT address_type) > 1
            ORDER BY type_count DESC, address_rows DESC
            LIMIT 25
        """)

        top_dot_stacked = self._safe_fetchall("""
            SELECT canonical_address, COUNT(*) AS carrier_rows
            FROM Addresses
            WHERE address_type IN ('dot_carrier_phy', 'dot_carrier_mail')
            GROUP BY canonical_address
            HAVING COUNT(*) >= 5
            ORDER BY carrier_rows DESC
            LIMIT 25
        """)

        return {
            'multi_type_canonicals': multi_type_count,
            'top_multi_type': top_multi_type,
            'top_dot_stacked': top_dot_stacked,
        }

    # Analytics methods for DuckDB
    def get_charity_summary_stats(self, tax_year: int = None) -> Dict[str, Any]:
        """Get summary statistics for charities"""
        where_clause = f"WHERE tax_year = {tax_year}" if tax_year else ""

        query = f"""
            SELECT
                COUNT(*) as total_charities,
                AVG(total_exp) as avg_expenses,
                SUM(total_exp) as total_expenses,
                AVG(officer_comp) as avg_officer_comp,
                COUNT(CASE WHEN foreign_office = 'Y' THEN 1 END) as foreign_offices
            FROM Charities
            {where_clause}
        """

        result = self.db_ops.execute_query(query).fetchone()
        if result:
            return {
                'total_charities': result[0],
                'avg_expenses': result[1],
                'total_expenses': result[2],
                'avg_officer_comp': result[3],
                'foreign_offices': result[4]
            }
        return {}

    def get_top_grant_recipients(self, limit: int = 10) -> List[Tuple]:
        """Get top grant recipients by total amount"""
        result = self.db_ops.execute_query("""
            SELECT recipient_ein, SUM(grant_amt) as total_grants, COUNT(*) as grant_count
            FROM Grants
            WHERE recipient_ein IS NOT NULL AND recipient_ein != ''
            GROUP BY recipient_ein
            ORDER BY total_grants DESC
            LIMIT ?
        """, (limit,))
        return result.fetchall()

    def get_geocoding_stats(self) -> Dict[str, int]:
        """Get geocoding completion statistics"""
        result = self.db_ops.execute_query("""
            SELECT
                COUNT(*) as total_addresses,
                COUNT(CASE WHEN geocoding_id IS NOT NULL THEN 1 END) as geocoded,
                COUNT(CASE WHEN geocoding_id IS NULL THEN 1 END) as pending
            FROM Addresses
        """).fetchone()
        if result:
            return {
                'total_addresses': result[0],
                'geocoded': result[1],
                'pending': result[2]
            }
        return {}

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get database performance statistics"""
        stats = {}

        # Get table sizes
        table_sizes = self.db_ops.execute_query("""
            SELECT table_name,
                    estimated_size as size_bytes,
                    ROUND(estimated_size / 1024.0 / 1024.0, 2) as size_mb
            FROM duckdb_tables()
            WHERE table_name IN ('Charities', 'Grants', 'Addresses', 'Officers', 'Geocoding')
        """).fetchall()

        stats['table_sizes'] = {row[0]: {'bytes': row[1], 'mb': row[2]} for row in table_sizes}

        # Get basic stats
        stats['memory_usage'] = self.db_ops.memory_limit
        stats['threads'] = self.db_ops.threads or 'auto'

        return stats

    def get_latest_charities_for_export(self) -> List[Tuple]:
        """Get latest charities for export"""
        # Ensure LatestCharities table exists
        self.db_ops.create_latest_charities_table()

        result = self.db_ops.execute_query("""
            SELECT tax_year, ein, filer_name, receipt_amt, govt_amt, contrib_amt,
                   org_type, total_exp, prog_exp, travel_amt, conferences_amt,
                   officer_comp, comp_pct, comp_ptile, travel_pct, travel_ptile,
                   conferences_pct, conferences_ptile, grants_pct, grants_ptile,
                   foreign_expenses_pct, foreign_expenses_ptile, grift_ratio,
                   total_assets, form_type, denominator, foreign_office, foreign_expenses,
                   grants_to_others, domestic_misrep_flag, xml_name
            FROM LatestCharities
            ORDER BY ein, tax_year
        """)
        return result.fetchall()

    def get_grants_for_export(self) -> List[Tuple]:
        """Get grants for export"""
        result = self.db_ops.execute_query("""
            SELECT filer_ein, filer_name, grant_ein, grant_amt, tax_year,
                   colocator, colocator
            FROM Grants
            ORDER BY filer_ein, tax_year
        """)
        return result.fetchall()

    def get_contractors_for_export(self) -> List[Tuple]:
        """Get contractors for export"""
        result = self.db_ops.execute_query("""
            SELECT filer_ein, name, amount, ein, address, zip_code,
                   po_box, tax_year, colocator
            FROM Contractors
            ORDER BY filer_ein, tax_year
        """)
        return result.fetchall()

    def get_political_contributions_for_export(self) -> List[Tuple]:
        """Get political contributions for export"""
        result = self.db_ops.execute_query("""
            SELECT filer_ein, recipient, amount, recipient_address,
                   recipient_zip, recipient_po_box, tax_year, colocator
            FROM PoliticalContributions
            ORDER BY filer_ein, tax_year
        """)
        return result.fetchall()


class StatsProducer(BaseProducer):
    """
    Producer for stats generation tasks, fetching batches of charities for partial stats computation
    using key-value paging on the 'id' primary key to ensure concurrent safety.
    """
 
    def __init__(self, db_ops: DatabaseOperations, batch_size: int = 1000):
        super().__init__(db_ops, batch_size)
        self.stats_computed = 0

    def _get_custom_metrics(self) -> Dict[str, Any]:
        """Custom metrics for stats producer."""
        return {'stats_computed': self.stats_computed}

    def _get_work_batch(self, last_pk: Optional[int] = None) -> Tuple[List[Tuple], Optional[int]]:
        """
        Get a batch of charities for stats processing using key-value paging on 'id'.
         
        Args:
            last_pk: The last primary key from the previous batch (None for first batch)
         
        Returns:
            Tuple of (batch: List of charity rows, max_pk: The maximum id in this batch or None if empty)
        """
        if self.exit_processing:
            return [], None
        pk_field = 'id'
        query = f"""
            SELECT * FROM Charities
            WHERE {pk_field} > ?
            ORDER BY {pk_field} ASC
            LIMIT ?
        """
        params = (last_pk if last_pk is not None else 0, self.batch_size)
        batch = self.db_ops.execute_query(query, params).fetchall()
       
        if batch:
            max_pk = max(row[0] for row in batch)  # Assuming 'id' is the first column
        else:
            max_pk = None
       
        return batch, max_pk

    def _process_work_batch_to_context(self, batch: List[Tuple]) -> PendingDatabaseContext:
        """
        Process a batch of charities to compute partial stats and add operations to context.
          
        For aggregate stats like histograms and group counts, partial results are computed here
        and can be merged later. For now, adds a progress update operation to track batch processing.
          
        Args:
            batch: List of charity rows from the database
              
        Returns:
            PendingDatabaseContext with operations for partial stats processing
        """
        context = PendingDatabaseContext()
          
        if batch:
            for row in batch:
                if self.shutdown_event.is_set() or self.exit_processing:
                    break
            # Add progress update for this batch
            progress_op = DatabaseOperation(
                DatabaseOperationType.PROGRESS_UPDATE,
                data={'count': len(batch)}
            )
            context.addOperationToDatabase(progress_op)
            self.stats_computed += len(batch)
              
            # TODO: Compute partial aggregates (e.g., count per tax_year in batch, bin counts for histograms)
            # These partial results would be added as custom operations to update temporary stats tables
            # or stored in context.data for merging after collection in collect_contexts
              
            # Example partial group by (tax_year counts):
            # from collections import Counter
            # partial_tax_year_counts = Counter(row[some_index] for row in batch)  # Adjust index for tax_year
            # Then add operation to merge these counts
              
        return context

    def collect_contexts(self) -> PendingDatabaseContext:
        """
        Override to call super and integrate with stats-specific logic if needed.
        Ensures compatibility with BaseProducer's paging and profiling.
        """
        self.setup_status_gauges(interval=10.0)
        context = super().collect_contexts()
        # Post-process if needed for stats-specific merging of partial aggregates
        return context

    def _collect_contexts_with_profiling(self) -> PendingDatabaseContext:
        """
        Override to call super for profiling integration.
        """
        context = super()._collect_contexts_with_profiling()
        # Post-process if needed
        return context