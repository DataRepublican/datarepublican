${'##'} Grift Report for ${org_type} - ${year}

${'###'} Grift Report
${'####'} Top 100 Organizations by Grift Ratio
Total organizations: ${'$'}{total_orgs}

% if len(high_grift) > 0:
**Note**: Entries with denominator < 1000 may indicate data issues. Please verify input data.

| **grift_ratio** | grift | denominator | filer_ein | filer_name | tax_year | total_exp | officer_comp | comp_pct | comp_ptile | travel_amt | travel_pct | travel_ptile | conferences_amt | conferences_pct | conferences_ptile | grants_to_others | grants_pct | grants_ptile | foreign_expenses | foreign_expenses_pct | foreign_expenses_ptile | total_assets |
|-----------------|-------|-------------|-----------|------------|----------|-----------|--------------|----------|------------|------------|------------|--------------|-----------------|-----------------|------------------|------------|--------------|------------------|---------------------|-----------------------|--------------|
% for row in high_grift.itertuples():
| **${row.grift_ratio}** | ${row.grift} | ${row.denominator} | ${row.filer_ein} | ${row.filer_name} | ${row.tax_year} | ${row.total_exp} | ${row.officer_comp} | ${row.comp_pct} | ${row.comp_ptile} | ${row.travel_amt} | ${row.travel_pct} | ${row.travel_ptile} | ${row.conferences_amt} | ${row.conferences_pct} | ${row.conferences_ptile} | ${row.grants_to_others} | ${row.grants_pct} | ${row.grants_ptile} | ${row.foreign_expenses} | ${row.foreign_expenses_pct} | ${row.foreign_expenses_ptile} | ${row.total_assets} |
% endfor

${'##'} Calculation Explanations
- **Grift Ratio (%)**: Percentage of total expenses spent on officer compensation, travel, and conferences, indicating potential self-dealing. Calculated as: `(officer_comp + travel_amt + conferences_amt) / total_exp * 100`. Clamped to 0–100.
- **Grift Ratio Percentile**: Percentile of grift ratio within the organization’s 501(c) type, where higher percentiles indicate higher domestic spending relative to peers. Ratings: A (80–100), B (60–79), C (40–59), D (20–39), F (0–19).
- **Grants to Others (%) (Informational)**: Percentage of total expenses allocated to grants to others, calculated as: `grants_to_others / total_exp * 100`. Provided for context, not a direct grift indicator.
- **Domestic Misrepresentation (%) (Informational)**: Same as grift ratio if flagged (grift ratio > 10 and foreign expenses < 10% of total expenses). Indicates potential misrepresentation of domestic focus.
- **Foreign Expenses (%) (Informational)**: Percentage of total expenses spent on foreign activities, calculated as: `foreign_expenses / total_exp * 100`. Notable for international charities (e.g., CHAI, Amnesty) if low grift ratio (< 10%) and high foreign expenses (> 10%), suggesting minimal domestic spending.% else:
No organizations with grift ratio data.
% endif