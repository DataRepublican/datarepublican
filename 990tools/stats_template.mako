<%!
# stats_template.mako - Template for database statistics reports
%>
${'#'} Database Statistics Report - ${step_name}

Generated: ${timestamp}

${'##'} Summary

Total records across all tables: ${total_records}

${'##'} Table Counts

| Table | Count |
|-------|-------|
% for table_name, count in table_counts.items():
| ${table_name} | ${count} |
% endfor

${'##'} XmlFiles Group Counts

${'###'} Tax Year Distribution
| Tax Year | Count |
|----------|-------|
% for tax_year, count in xml_group_counts['tax_year']:
| ${tax_year} | ${count} |
% endfor

${'###'} Form Type Distribution
| Form Type | Count |
|-----------|-------|
% for form_type, count in xml_group_counts['form_type']:
| ${form_type} | ${count} |
% endfor

${'###'} Processing Status Distribution
| Processed | Count |
|-----------|-------|
% for processed, count in xml_group_counts['processed']:
| ${processed} | ${count} |
% endfor

${'###'} Processing Version Distribution
| Processing Version | Count |
|-------------------|-------|
% for version, count in xml_group_counts['processing_version']:
| ${version} | ${count} |
% endfor

${'###'} Error Message Prefix Distribution (Top 10)
| Error Message Prefix | Count |
|---------------------|-------|
% for error_prefix, count in xml_group_counts['error_message_prefix'][:10]:
| ${error_prefix} | ${count} |
% endfor

${'##'} XmlFiles File Size Histogram

% if xml_histogram:
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% for bin in xml_histogram:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available (no file_size data or histogram function failed).
% endif

${'##'} Table Summaries

% for table_name, summary_data in table_summaries.items():
${'###'} Summary ${table_name}

| Column Name | Type | Min | Max | Approx Unique | Avg | Std | Q25 | Q50 | Q75 | Count | Null % |
|-------------|------|-----|-----|--------------|-----|-----|-----|-----|-----|-------|--------|
% for row in summary_data:
| ${table_name}.${row[0]} | ${row[1]} | ${row[2] if row[2] is not None else ''} | ${row[3] if row[3] is not None else ''} | ${row[4] if row[4] is not None else ''} | ${row[5] if row[5] is not None else ''} | ${row[6] if row[6] is not None else ''} | ${row[7] if row[7] is not None else ''} | ${row[8] if row[8] is not None else ''} | ${row[9] if row[9] is not None else ''} | ${row[10] if row[10] is not None else ''} | ${row[11] if row[11] is not None else ''} |
% endfor

% endfor

${'##'} Charities Details

${'####'} Tax Year Distribution
| Tax Year | Count |
|----------|-------|
% for tax_year, count in charities_analysis['tax_year_counts']:
| ${tax_year} | ${count} |
% endfor

${'####'} Organization Type Distribution
| Org Type | Count |
|----------|-------|
% for org_type, count in charities_analysis['org_type_counts']:
| ${org_type} | ${count} |
% endfor

${'####'} Form Type Distribution
| Form Type | Count |
|-----------|-------|
% for form_type, count in charities_analysis['form_type_counts']:
| ${form_type} | ${count} |
% endfor

${'###'} charities receipt_amt Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'receipt_amt' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['receipt_amt']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities govt_amt Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'govt_amt' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['govt_amt']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities contrib_amt Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'contrib_amt' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['contrib_amt']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities total_exp Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'total_exp' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['total_exp']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities prog_exp Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'prog_exp' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['prog_exp']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities travel_amt Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'travel_amt' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['travel_amt']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities conferences_amt Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'conferences_amt' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['conferences_amt']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities officer_comp Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'officer_comp' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['officer_comp']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} charities total_assets Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% if 'total_assets' in charities_analysis['histograms']:
% for bin in charities_analysis['histograms']['total_assets']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No histogram data available.
% endif

${'###'} Officers Analysis

${'####'} Top 10 Last Names
| Last Name | Count |
|-----------|-------|
% for last_name, count in officers_analysis['top_last_names']:
| ${last_name} | ${count} |
% endfor

${'###'} Grants Analysis

% if 'grant_amt_histogram' in grants_analysis:
${'####'} Grant Amount Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% for bin in grants_analysis['grant_amt_histogram']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No grant amount histogram (min == max or no data).
% endif

${'###'} Contractors Analysis

% if 'amount_histogram' in contractors_analysis:
${'####'} Contractor Amount Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% for bin in contractors_analysis['amount_histogram']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No contractor amount histogram (min == max or no data).
% endif

${'###'} Political Contributions Analysis

% if 'amount_histogram' in political_contributions_analysis:
${'####'} Political Contribution Amount Histogram
| Bin Width | Bin Lower | Bin Upper | Count | Pct | Bar |
|-----------|-----------|-----------|-------|-----|-----|
% for bin in political_contributions_analysis['amount_histogram']:
| ${"%.2f" % bin['bin_width']} | ${"%.2f" % bin['bin_lower']} | ${"%.2f" % bin['bin_upper']} | ${bin['count']} | ${"%.1f" % bin['pct']}% | ${"█" * int(bin['pct'] / 2)} |
% endfor
% else:
No political contribution amount histogram (min == max or no data).
% endif

${'###'} Addresses Analysis

${'####'} Top 10 States
| State | Count |
|-------|-------|
% for state, count in addresses_analysis['top_states']:
| ${state} | ${count} |
% endfor

${'####'} Top 10 ZIP Codes
| ZIP Code | Count |
|----------|-------|
% for zip_code, count in addresses_analysis['top_zip_codes']:
| ${zip_code} | ${count} |
% endfor

${'###'} Address Deduplication Progress

| Metric | Count |
|--------|-------|
| Total addresses with canonical_address | ${addresses_deduplication_analysis['total_canonical_addresses']} |
| Distinct canonical addresses | ${addresses_deduplication_analysis['distinct_canonical_addresses']} |
| Child addresses (deduplicated) | ${addresses_deduplication_analysis['child_addresses']} |
| Master addresses (with children) | ${addresses_deduplication_analysis['master_addresses']} |
| Still need deduplication | ${addresses_deduplication_analysis['still_need_deduplication']} |
| Unique addresses (no duplicates) | ${addresses_deduplication_analysis['unique_addresses_no_duplicates']} |

${'###'} Address Colocator Analysis

| Category | Count |
|----------|-------|
| Distinct colocator values | ${addresses_colocator_analysis.get('distinct_colocators', 0)} |
| Post Office (PO%) | ${addresses_colocator_analysis.get('po_count', 0)} |
| Foreign Address (FA%) | ${addresses_colocator_analysis.get('fa_count', 0)} |
| Geocoded (LL%) | ${addresses_colocator_analysis.get('ll_count', 0)} |
| Institution Codes | ${addresses_colocator_analysis.get('institution_count', 0)} |
| Other/Unknown | ${addresses_colocator_analysis.get('neither_count', 0)} |

${'####'} Colocator Type Breakdown
| Type | Count |
|------|-------|
% for colocator_type, count in addresses_colocator_analysis.get('colocator_type_breakdown', []):
| ${colocator_type} | ${count} |
% endfor

${'####'} Colocator by Address Type
| Address Type | Count |
|--------------|-------|
% for address_type, count in addresses_colocator_analysis.get('colocator_by_address_type', []):
| ${address_type} | ${count} |
% endfor

${'####'} Top 10 Institution Prefixes
| Prefix | Count |
|--------|-------|
% for prefix, count in addresses_colocator_analysis.get('top_institution_prefixes', []):
| ${prefix} | ${count} |
% endfor

${'###'} Geocoding Status Analysis

| Geocoding Status | Count |
|------------------|-------|
% for status, count in geocoding_status_analysis['geocoding_status_counts']:
| ${status if status else 'NULL'} | ${count} |
% endfor

| Metric | Count |
|--------|-------|
| Total geocoding records | ${geocoding_status_analysis['total_geocoding_records']} |
| Records with coordinates | ${geocoding_status_analysis['geocoded_with_coords']} |
| Records with API attempts | ${geocoding_status_analysis['attempted_records']} |

${'###'} External Reference Tables (FEC / Medicare / Sanctions / DOT)

| Source | Ingested | Tables |
|--------|----------|--------|
% for group_name, counts in external_reference_analysis['groups'].items():
| ${group_name} | ${'yes' if external_reference_analysis['ingested'][group_name] else 'no'} | ${', '.join(f"{t}={counts[t]:,}" for t in counts)} |
% endfor

${'###'} Address Type Breakdown

| Address Type | Count |
|--------------|-------|
% for address_type, count in address_type_analysis.get('by_type', []):
| ${address_type if address_type else 'NULL'} | ${count} |
% endfor

% if address_type_analysis.get('new_source_types'):
${'####'} New-Source Address Types (FEC / OFAC / DOT)
| Address Type | Count |
|--------------|-------|
% for address_type, count in address_type_analysis['new_source_types']:
| ${address_type} | ${count} |
% endfor
% endif

${'###'} Shared Canonical / Colocation Signals

| Metric | Count |
|--------|-------|
| Canonical addresses shared across multiple address_types | ${shared_canonical_analysis.get('multi_type_canonicals', 0)} |

% if shared_canonical_analysis.get('top_multi_type'):
${'####'} Top Multi-Type Canonical Addresses
| Canonical Address | Address Types | Rows | Type Count |
|-------------------|---------------|------|------------|
% for canon, types, rows, type_count in shared_canonical_analysis['top_multi_type']:
| ${canon} | ${types} | ${rows} | ${type_count} |
% endfor
% endif

% if shared_canonical_analysis.get('top_dot_stacked'):
${'####'} Top DOT-Stacked Addresses (5+ carrier rows)
| Canonical Address | Carrier Rows |
|-------------------|--------------|
% for canon, carrier_rows in shared_canonical_analysis['top_dot_stacked']:
| ${canon} | ${carrier_rows} |
% endfor
% endif

${'##'} Processing Details

- **Step**: ${step_name}
- **Database**: ${db_path}
- **Timestamp**: ${timestamp}

${'##'} Notes

${notes}