# Pharma Subsidy Context and BIG PHARMA SUBSIDY Rollup

## The $1B First-Pill Reality
Big pharmaceutical companies spend ~$1B to develop and get the first pill of a new med approved. After that, marginal cost is ~$0.10 per pill.

To recoup the $1B they charge high prices initially. For poor patients they subsidize the cost through "charity" patient assistance programs. This lets them take a tax deduction while still recovering the R&D cost.

These are not "real" charities with normal EINs — they are tax-advantaged subsidy flows. We use a synthetic EIN (99-7777777) and single canonical "BIG PHARMA SUBSIDY" so:
- Dollar volume is preserved in grant visualizations.
- Fraud detection can flag unusual patterns around these rows.
- We don't pollute real charity EIN graphs.

## How the Siding Works
- Generator loads big_pharma_subsidy.json early in STAGE 1 (before the STAGE 3 rubicon).
- Patterns use re.search (searches anywhere in the name, equivalent to .*HIPPA.*).
- Matching names are sided out of the main grantee_names loop (avoids expensive scanning/fuzzy/dedup on noise).
- All sided names are aggregated as variants under one BIG PHARMA SUBSIDY canonical with the synthetic EIN before output.

This is the clean architecture you requested. No real EINs will ever exist for these rows.

## Current Patterns (from big_pharma_subsidy.json)
- SEE[ .]*(ATTACHMENT|SCHEDULE|ATTACHED|ATTACH)
- HIPPA, HIPAA, PATIENT, PATIENTS, ELIGIBLE[ .]*PATIENTS?
- PATIENT[ .]*(ASSISTANCE|PROGRAM|PROGRAMS?)
- DRUGS?[ .&]*MEDICINES?
- VARIOUS[ .]*NEEDY[ .]*PATIENTS, etc.

The [ .]* addition handles punctuation and extra spaces ("SEE. ATTACHMENT", "Drugs. & Medicines").

## Analyzer Handling
The v2 analyzer now factors in the pharma patterns and returns the special reason:
"Covered by BIG PHARMA SUBSIDY (synthetic EIN for patient subsidy/tax deduction after $1B first-pill cost - no real EIN expected)"

These rows no longer appear as "uncovered".

See pipeline_overview.md for the SQL that generates the source TSVs and how this fits into the full grant matching pipeline.

Updated 2026-05-06 per your feedback.