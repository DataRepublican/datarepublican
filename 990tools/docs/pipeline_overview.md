# Pipeline Overview for IRS 990 Name Matching

## Source TSV Generation SQL (from /Volumes/Data/final/irs990.duckdb.hermesex)

**distinct_grantee_names.tsv** (full version — the "source of truth" extract):
- Contains `grantee_name`, `grant_count`, `total_dollars`, and `recipient_ein` (when present).
- Produced from the Grants table (sometimes via joins that pull in BMF EINs).
- This is the file used by EIN-based resolvers such as `university_ein_resolver.py` (universities and some other well-covered entities have usable `recipient_ein` values from the BMF data).

```sql
COPY (
  SELECT 
    recipient_name as grantee_name,
    count(*) as grant_count,
    sum(amount) as total_dollars,
    recipient_ein
  FROM grants 
  WHERE recipient_name IS NOT NULL
  GROUP BY recipient_name, recipient_ein
  ORDER BY total_dollars DESC
) TO 'distinct_grantee_names.tsv' (DELIMITER '\t', HEADER);
```

**distinct_grantee_names_clean.tsv** (the practical daily driver):
- A reduced 3-column version (`grantee_name`, `grant_count`, `total_dollars`) with the EIN column dropped.
- Used for fast iteration with `splink_pattern_miner.py --use-clean-tsv`, `review_suggestions_tui.py`, `category_splitter.py`, and name-only resolvers (churches, most school districts, high schools, etc.).
- This is what almost all the 2026 Splink + TUI + category bucket work defaults to.

**bmf_analysis.tsv** (EIN, name, city, state, grant totals from BMF):
```sql
COPY (
  SELECT 
    ein,
    filer_name as name,
    city,
    state,
    sum(amount) as total_dollars
  FROM grants g
  JOIN irs_bmf b ON g.recipient_ein = b.ein
  GROUP BY ein, filer_name, city, state
) TO 'bmf_analysis.tsv' (DELIMITER '\t', HEADER);
```

**ein_name_variants.tsv** (authoritative charity names from IRS):
```sql
COPY (
  SELECT ein, name, sum(amount) as total_dollars
  FROM charities 
  GROUP BY ein, name
  ORDER BY total_dollars DESC
) TO 'ein_name_variants.tsv' (DELIMITER '\t', HEADER);
```

## Main Pipeline Step Order (`irs990processor.py`)

```
irsfetch → zip → bmf → xml → fec → medicare → sanctions → dot → address → einless → match
  → geolocate_prev → geolocate_census → geolocate_api → geolocate_grok → geolocate_archive
  → grant_match → backfill → photos → ratios → percentiles → export
```

**Geolocate trilogy:**
| Step | Role |
|------|------|
| `geolocate_prev` | Load archive TSV; lat/lon + loose_colocator on Addresses/owners; drop empty shells |
| `geolocate_new` / census+api | Free-API geocoding (Grok deferred) |
| `geolocate_grok` | xAI batch for hard tail |
| `geolocate_archive` | Export `canonical_address` + colocator + geocoding_status TSV |

After archive: **`grant_match`** (colocator + loose_colocator hail-mary) → **`backfill`** → **`photos`** (officer KG; after backfill so EIN graph is stable).

**`fec` step** (`fec_processor.py`): after XML, before medicare. Downloads FEC bulk files per cycle (`FEC_CYCLES` env, default even years 2000–2026), fixes pipe-delimited rows, streams into `fec_*` tables + `Addresses` via model `build_address()` factories. Data under `{final_dir}/cms_data/fec/`.

Run standalone: `FEC_CYCLES=2024 python -u irs990processor.py --step fec --nostats -v`

**`medicare` step** (`medicare_processor.py`): CMS NPPES + Medicaid provider spending (Parquet from opendata.hhs.gov). Promotes to `medicare_providers`, `medicare_provider_spending`, code lookups. Data under `{final_dir}/cms_data/medicare/`.

Run standalone: `python -u irs990processor.py --step medicare --nostats -v`

**`sanctions` step** (`sanctions_processor.py`): Treasury OFAC SDN list (advanced XML). Promotes to `sanctioned_entities`, `sanctioned_names`, `sanctioned_identifiers`, `sanctioned_programs`, plus street addresses in `Addresses` (`address_type=ofac_sanction`). Data under `{final_dir}/cms_data/treasury/`. Ingest only — grant-match flagging is a later consumer.

Run standalone (use `nohup` for CLI crash resilience):
```bash
nohup python -u irs990processor.py --step sanctions --nostats -v > sanctions_step.log 2>&1 &
```

Country-only OFAC locations use `FA:<iso>` colocators; blank/`undetermined` rows are skipped (not promoted to `Addresses`).

**`dot` step** (`dot_processor.py`): FMCSA Motor Carrier Census (4.45M carriers; CSV ~1.6 GB) from [data.transportation.gov](https://data.transportation.gov/Trucking-and-Motorcoaches/Company-Census-File/az4n-8mr2). Promotes to `dot_carriers` + `Addresses` (`dot_carrier_phy`, `dot_carrier_mail`). Data under `{final_dir}/cms_data/dot/`. FEC-style resume on interrupt; idempotent `.dot_census_ingest.json` marker. Production-validated 2026-06-20: 4,454,157 carriers; 4,450,675 phy + 977,160 mail addresses. Ingest only — same-building colocation is a later consumer (`grant_match` / `geolocate1`).

Run standalone (use `nohup` — long-running on large DBs):
```bash
nohup python -u irs990processor.py --step dot --nostats -v > dot_step.log 2>&1 &
```

**Production resume point (June 2026):** `--start-step match` (address dedup complete; `einless` already run — skip unless re-hygiene needed).

**Data separation on Grants:**
- `recipient_ein` — parsed from 990 XML (never overwritten)
- `recipient_ein_backfilled` — inferred EIN from einless phonebook, BMF pre-backfill, address/name match
- Effective EIN: `COALESCE(recipient_ein_backfilled, recipient_ein)`

**`einless` step** (`einless_processor.py`): runs after address dedup, before match.
1. Exports einless input TSVs via DuckDB COPY (see SQL below).
2. Builds exact-core phonebook from `bmf_analysis.tsv` + `ein_name_variants.tsv`.
3. Resolves no-EIN grantee names (DAF → skip big_pharma/implausible → phonebook cream).
4. Writes `recipient_ein_backfilled` + `Backfill` rows (`einless_phonebook`, `einless_daf`).

Run standalone: `python -u irs990processor.py --step einless --nostats -v`

**`pure_no_ein_by_dollars.tsv`** (names that never have a real EIN in source data):
```sql
SELECT grantee_name, COUNT(*)::BIGINT AS grant_count, SUM(grant_amt)::DOUBLE AS dollars, CAST(NULL AS VARCHAR) AS recipient_ein
FROM Grants
WHERE grantee_name IS NOT NULL AND TRIM(grantee_name) != ''
GROUP BY grantee_name
HAVING NOT BOOL_OR(recipient_ein IS NOT NULL AND TRIM(recipient_ein) != '' AND recipient_ein != '8686')
ORDER BY dollars DESC;
```

Offline hygiene (rebuild/rebucket/Grok on hard tail) lives in `einless/` — see `issue_bootstrap.md` and `docs/einless_grantee_resolution_architecture.md`.

## Overall Flow
1. Edit name_rule_constants.py (SIMPLES, GOOD_SINGLE_WORD_PRIORITIES, PROBLEM_SUFFIXES).
2. Run generator (clears cache for full run, uses pharma_siding for subsidy rows, outputs dict with variants).
3. v2 analyzer + reverse_coverage for diagnostics (raw/cleaned/best_canonical/similarity/reason).
4. Pipeline `einless` step phonebook-backfills no-EIN grantees; then `match` (address_matcher.py) and grant_match_processor.py apply name rules + address matching.
5. Visualization and fraud detection in DuckDB use the synthetic EIN for BIG PHARMA SUBSIDY rows.

## Fraud / Cross-Pollination Research (June 2026)

Ultimate goal: surface reportable fraud signals for USG review. Early ingest-only sources now in DB:

| Signal | Tables / join key | When useful |
|--------|-----------------|-------------|
| Same-building colocation | `Addresses.canonical_address` across `address_type` | Now (stats report `shared_canonical`) |
| Charity as contractor | `Charities`/`IrsBmf` ↔ `Contractors` (name/EIN) | After `match` |
| Grants to sanctioned entity | `Grants` ↔ `sanctioned_names` | After `match` + name rules |
| FEC ↔ NGO | `fec_*` ↔ `Charities` at shared address or EIN | After geolocate trilogy |
| Medicare provider grants | `medicare_providers` ↔ `Grants` (NPI/name) | After `match`; Planned Parenthood-class providers |
| DOT shell offices | Many `dot_carrier_*` rows per `canonical_address` | Standalone script + post-`loose_colocator` |

Stats report (`stats_processor.py`) now includes FEC/Medicare/sanctions/DOT table counts (0 if missing), address-type breakdown, and top multi-type canonicals + DOT-stacked addresses.

Pharma subsidy rows ($1B first-pill cost, tax deduction "charity") use synthetic EIN 99-7777777 to preserve $ volume without pretending they are normal charities.

See how_to_run_tools.md and pharma_subsidy.md for details.
