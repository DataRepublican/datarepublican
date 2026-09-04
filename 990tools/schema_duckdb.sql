-- DuckDB Schema for IRS 990 Database
-- Comprehensive DuckDB database to replace SQLite-based data storage
-- Note: UUID extension not available on all platforms, using VARCHAR for now
-- INSTALL uuid;
-- LOAD uuid;
-- Charities table - Core charity data from IRS 990 filings
CREATE TABLE IF NOT EXISTS Charities (
    charity_id UUID DEFAULT uuidv7() PRIMARY KEY,
    ein VARCHAR(9) NOT NULL,
    -- Employer Identification Number (3/9 digits)
    tax_year INTEGER NOT NULL,
    -- Tax year of filing
    filer_name VARCHAR NOT NULL,
    -- Organization name (concatenated from business_name_line1 and business_name_line2)
    sndx VARCHAR,
    -- Precomputed double metaphone for fuzzy matching
    receipt_amt DOUBLE,
    -- Total receipts
    govt_amt DOUBLE,
    -- Government grants received
    contrib_amt DOUBLE,
    -- Contributions received
    org_type VARCHAR,
    -- Organization type (501(c)(3), etc.)
    total_exp DOUBLE,
    -- Total expenses
    prog_exp DOUBLE,
    -- Program expenses
    travel_amt DOUBLE,
    -- Travel expenses
    conferences_amt DOUBLE,
    -- Conference expenses
    officer_comp DOUBLE,
    -- Officer compensation
    comp_pct DOUBLE,
    -- Compensation as percentage
    comp_ptile DOUBLE,
    -- Compensation percentile
    comp_ptile_value DOUBLE,
    -- Compensation percentile value
    travel_pct DOUBLE,
    -- Travel as percentage
    travel_ptile DOUBLE,
    -- Travel percentile
    travel_ptile_value DOUBLE,
    -- Travel percentile value
    conferences_pct DOUBLE,
    -- Conferences as percentage
    conferences_ptile DOUBLE,
    -- Conferences percentile
    conferences_ptile_value DOUBLE,
    -- Conferences percentile value
    grants_pct DOUBLE,
    -- Grants to others as percentage
    grants_ptile DOUBLE,
    -- Grants to others percentile
    grants_ptile_value DOUBLE,
    -- Grants to others percentile value
    foreign_expenses_pct DOUBLE,
    -- Foreign expenses as percentage
    foreign_expenses_ptile DOUBLE,
    -- Foreign expenses percentile
    foreign_expenses_ptile_value DOUBLE,
    -- Foreign expenses percentile value
    grift_ratio DOUBLE,
    -- Grift ratio calculation
    total_assets DOUBLE,
    -- Total assets
    form_type VARCHAR,
    -- Form type (990, 990EZ, 990PF)
    denominator DOUBLE,
    -- Denominator for calculations
    foreign_office VARCHAR,
    -- Foreign office indicator
    foreign_expenses DOUBLE,
    -- Foreign expenses amount
    grants_to_others DOUBLE,
    -- Grants to other organizations
    domestic_misrep_flag VARCHAR,
    -- Domestic misrepresentation flag
    xml_name VARCHAR UNIQUE,
    -- XML filename reference
    colocator VARCHAR,
    -- Colocator data: LL:lat:lon, PO:box:zip, FA:country_code (tight, ~10-35ft / same building or PO)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator (same town/metro) for Splink blocking and name matching when recipient_ein is missing
    grift DOUBLE,
    -- Grift amount
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(xml_name) -- Prevent duplicate charity records per EIN per year
);
-- Grants table - Grant data from charity filings
CREATE TABLE IF NOT EXISTS Grants (
    grant_id UUID DEFAULT uuidv7() PRIMARY KEY,
    filer_ein VARCHAR(9) NOT NULL,
    -- Filer EIN (foreign key to Charities with tax_year)
    filer_name VARCHAR NOT NULL,
    -- Grantee EIN (foreign key to Charities)
    grantee_name VARCHAR NOT NULL,
    grantee_sndx VARCHAR,
    -- Precomputed soundex for fuzzy matching
    -- Filer name
    recipient_ein VARCHAR(9),
    -- Grantee EIN from 990 XML (source of truth; never overwritten by processing)
    recipient_ein_backfilled VARCHAR(9),
    -- Inferred EIN (einless phonebook, BMF pre-backfill, address/name match)
    grantee_name_bmf VARCHAR,
    -- Official BMF name when grant has or matches an EIN
    grantee_name_geo VARCHAR,
    -- Geo-aware normalized name (name rules)
    grantee_name_conc VARCHAR,
    -- Fully consolidated canonical name
    grant_amt DOUBLE NOT NULL,
    -- Grant amount
    tax_year INTEGER NOT NULL,
    -- Tax year
    colocator VARCHAR,
    -- Grantee colocator data (tight)
    filer_colocator VARCHAR,
    -- Filer colocator data
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator (same town) for Splink + grant matching when recipient_ein missing
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (filer_ein, tax_year) REFERENCES Charities(ein, tax_year) -- DuckDB doesn't support CASCADE
);
-- Contributions table - Contribution data from filings
CREATE TABLE IF NOT EXISTS Contributions (
    contribution_id UUID DEFAULT uuidv7() PRIMARY KEY,
    filer_ein CHAR(9) NOT NULL,
    -- Filer EIN
    filer_name VARCHAR NOT NULL,
    -- Filer name
    recipient_ein CHAR(9),
    -- Recipient EIN
    amount DOUBLE NOT NULL,
    -- Contribution amount
    tax_year INTEGER NOT NULL,
    -- Tax year
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (filer_ein, tax_year) REFERENCES Charities(ein, tax_year) -- DuckDB doesn't support CASCADE
);
-- Addresses table - Address data for charities and grantees
CREATE TABLE IF NOT EXISTS Addresses (
    address_id UUID DEFAULT uuidv7() PRIMARY KEY,
    ein CHAR(9),
    -- EIN this address belongs to if Charity
    owner_id UUID,
    -- Owner ID for loose foreign key relationships (NULL for standalone addresses)
    master_id UUID,
    -- Master address ID for deduplication (NULL for root addresses of the tree)
    name VARCHAR NOT NULL,
    -- Organization name
    address_line1 VARCHAR,
    -- First line of street address
    address_line2 VARCHAR,
    -- Second line of street address
    city VARCHAR,
    -- City
    state VARCHAR,
    -- State
    zip_code VARCHAR,
    -- ZIP code (first 5 digits)
    zip4 VARCHAR,
    -- ZIP+4 code (last 4 digits)
    po_box VARCHAR,
    -- PO Box if applicable
    canonical_address VARCHAR,
    -- Standardized address built from components
    address_type VARCHAR NOT NULL,
    -- Address type
    geocoding_id UUID,
    -- Reference to geocoding cache
    latitude DOUBLE,
    -- Latitude coordinate
    longitude DOUBLE,
    -- Longitude coordinate
    colocator VARCHAR,
    -- Colocator data: LL:lat:lon, PO:box:zip, FA:country_code (tight)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator for town-level blocking and matching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- FOREIGN KEY (geocoding_id) REFERENCES Geocoding(geocoding_id) -- DuckDB doesn't support SET NULL
);
-- Geocoding table - Cached geocoding results
CREATE TABLE IF NOT EXISTS Geocoding (
    geocoding_id UUID DEFAULT uuidv7() PRIMARY KEY,
    canonical_address VARCHAR,
    -- Canonical address this geocoding represents
    normalized_address VARCHAR NOT NULL,
    -- Normalized address string for API calls
    latitude DOUBLE,
    -- Latitude coordinate
    longitude DOUBLE,
    -- Longitude coordinate
    geocoding_status VARCHAR DEFAULT 'pending',
    geocoding_stage VARCHAR DEFAULT 'tier1',
    -- Current geocoding stage (tier1, tier2, tier3, tier4)
    last_attempt TIMESTAMP,
    -- Last geocoding attempt
    attempt_count INTEGER DEFAULT 0,
    -- Number of attempts
    address_count INTEGER DEFAULT 0,
    -- Number of addresses affected
    matched_address VARCHAR,
    -- Matched address returned by geocoding API
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- ZipFiles table - ZIP file metadata
CREATE TABLE IF NOT EXISTS ZipFiles (
    zip_id UUID PRIMARY KEY,
    filename VARCHAR NOT NULL UNIQUE,
    -- ZIP filename
    file_path VARCHAR NOT NULL,
    -- Full path to ZIP file
    tax_year INTEGER NOT NULL,
    -- Tax year
    file_size BIGINT,
    -- File size in bytes
    checksum VARCHAR,
    -- File checksum for integrity
    download_date TIMESTAMP,
    -- When file was downloaded
    processed_date TIMESTAMP,
    -- When file was processed
    status VARCHAR DEFAULT 'downloaded' CHECK(status IN ('downloaded', 'processed', 'error')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- XmlFiles table - XML file metadata within ZIPs
CREATE TABLE IF NOT EXISTS XmlFiles (
    xml_id UUID DEFAULT uuidv7() PRIMARY KEY,
    zip_id UUID NOT NULL,
    -- Reference to ZIP file
    filename VARCHAR NOT NULL,
    -- XML filename within ZIP
    internal_path VARCHAR NOT NULL,
    -- Path within ZIP archive
    file_size BIGINT,
    -- Size of XML file in bytes
    ein CHAR(9),
    -- EIN extracted from XML, starts as NULL
    tax_year INTEGER,
    -- Tax year from XML
    form_type VARCHAR,
    -- Form type (990, 990EZ, 990PF)
    processed BOOLEAN DEFAULT FALSE,
    -- Whether XML has been processed
    org_type VARCHAR,
    -- Organization type determined during parsing
    processed_at TIMESTAMP,
    -- Timestamp when processed flag was set to TRUE
    processing_version INTEGER DEFAULT 0,
    -- Version of processing pipeline used (for incremental updates)
    error_message VARCHAR,
    -- Error message if processing failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (zip_id) REFERENCES ZipFiles(zip_id) -- DuckDB doesn't support CASCADE
    UNIQUE(zip_id, filename) -- Unique within each ZIP
);
-- Backfill table - Additional grantee data for unknown EINs
CREATE TABLE IF NOT EXISTS Backfill (
    backfill_id UUID DEFAULT uuidv7() PRIMARY KEY,
    grant_id UUID,
    -- Grant originator
    recipient_ein VARCHAR(9) NOT NULL,
    -- Grantee EIN
    name VARCHAR NOT NULL,
    -- Organization name
    colocator VARCHAR,
    -- Colocator data (tight)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator for town-level matching
    source VARCHAR DEFAULT 'xml',
    -- Source of backfill data
    zip_code VARCHAR,
    -- ZIP code for uniqueness
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
);
-- PendingCanonicals table - Pre-computed canonical address groups for deduplication
CREATE TABLE IF NOT EXISTS PendingCanonicals (
    canonical_address VARCHAR PRIMARY KEY,
    -- Canonical address string (primary key)
    root_id UUID NOT NULL,
    -- Root address ID (smallest address_id for this canonical group)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- When this canonical group was created
);
-- PipelineProgress table - Track processing pipeline status
CREATE TABLE IF NOT EXISTS PipelineProgress (
    progress_id UUID DEFAULT uuidv7() PRIMARY KEY,
    step_name VARCHAR NOT NULL,
    -- Pipeline step name
    start_year INTEGER NOT NULL,
    -- Start year being processed
    end_year INTEGER NOT NULL,
    -- End year being processed
    status VARCHAR NOT NULL CHECK(
        status IN ('pending', 'running', 'completed', 'failed')
    ),
    started_at TIMESTAMP,
    -- When step started
    completed_at TIMESTAMP,
    -- When step completed
    records_processed BIGINT DEFAULT 0,
    -- Records processed
    error_message VARCHAR,
    -- Error details if failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(step_name, start_year, end_year) -- One entry per step per year range
);
-- Officers table - Officer compensation data
CREATE TABLE IF NOT EXISTS Officers (
    officer_id UUID DEFAULT uuidv7() PRIMARY KEY,
    charity_id UUID NOT NULL,
    -- Reference to Charities
    master_id UUID,
    -- Master officer ID for deduplication (NULL for master officers)
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    full_name VARCHAR,
    -- Full name as it appears in the filing (for photo lookup)
    compensation DOUBLE NOT NULL,
    tax_year INTEGER NOT NULL,
    photo_url VARCHAR,
    -- URL to officer photo from Google Knowledge Graph API
    colocator VARCHAR,
    -- Colocator data: LL:lat:lon, PO:box:zip, FA:country_code (tight)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator for town-level blocking
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (charity_id) REFERENCES Charities(charity_id) -- DuckDB doesn't support CASCADE
);
-- Contractors table - Contractor payment data
CREATE TABLE IF NOT EXISTS Contractors (
    contractor_id UUID DEFAULT uuidv7() PRIMARY KEY,
    charity_id UUID NOT NULL,
    -- owning charity
    filer_ein CHAR(9) NOT NULL,
    -- Filer EIN
    name VARCHAR NOT NULL,
    -- Contractor name
    amount DOUBLE NOT NULL,
    -- Payment amount
    ein CHAR(9),
    -- Contractor EIN if available
    tax_year INTEGER NOT NULL,
    -- Tax year
    colocator VARCHAR,
    -- Colocator data (tight)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator for town-level matching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (filer_ein) REFERENCES Charities(ein) -- DuckDB doesn't support CASCADE
);
-- PoliticalContributions table - Political contribution data
CREATE TABLE IF NOT EXISTS PoliticalContributions (
    political_id UUID DEFAULT uuidv7() PRIMARY KEY,
    charity_id UUID NOT NULL,
    -- owning charity
    filer_ein CHAR(9) NOT NULL,
    -- Filer EIN
    recipient VARCHAR NOT NULL,
    -- Recipient name
    amount DOUBLE NOT NULL,
    -- Contribution amount
    recipient_ein CHAR(9),
    -- EIN if it exists
    tax_year INTEGER NOT NULL,
    -- Tax year
    colocator VARCHAR,
    -- Colocator data (tight)
    loose_colocator VARCHAR,
    -- Coarse 0.5° grid colocator for town-level matching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- FOREIGN KEY (filer_ein) REFERENCES Charities(ein) -- DuckDB doesn't support CASCADE
);
CREATE TABLE IF NOT EXISTS _meta_clustering (
    table_name VARCHAR,
    clustered_column VARCHAR,
    clustered_at TIMESTAMP,
    PRIMARY KEY (table_name)
);

-- AuthoritativeEin table - Canonical name -> EIN mappings with colocator support
-- Used for high-quality name-to-EIN resolution during grant matching and Splink seed generation.
-- Populated by grant_match_processor.build_authoritative_ein_table()
CREATE TABLE IF NOT EXISTS AuthoritativeEin (
    name            VARCHAR NOT NULL,
    colocator       VARCHAR,           -- tight colocator or 'NULL' for global rows
    loose_colocator VARCHAR,           -- 0.5° coarse grid or 'NULL' for global rows
    ein             VARCHAR(9) NOT NULL,
    count           INTEGER,
    PRIMARY KEY (name, colocator, loose_colocator)
);
-- Indexes for performance optimization
-- Charities indexes
CREATE INDEX IF NOT EXISTS idx_charities_ein ON Charities(ein);
CREATE INDEX IF NOT EXISTS idx_charities_tax_year ON Charities(tax_year);
CREATE INDEX IF NOT EXISTS idx_charities_org_type ON Charities(org_type);
CREATE INDEX IF NOT EXISTS idx_charities_form_type ON Charities(form_type);
CREATE INDEX IF NOT EXISTS idx_charities_denominator ON Charities(denominator);
-- Grants indexes
CREATE INDEX IF NOT EXISTS idx_grants_filer_ein ON Grants(filer_ein);
CREATE INDEX IF NOT EXISTS idx_grants_recipient_ein ON Grants(recipient_ein);
CREATE INDEX IF NOT EXISTS idx_grants_tax_year ON Grants(tax_year);
CREATE INDEX IF NOT EXISTS idx_grants_colocator ON Grants(colocator);
CREATE INDEX IF NOT EXISTS idx_grants_filer_colocator ON Grants(filer_colocator);
CREATE INDEX IF NOT EXISTS idx_grants_loose_colocator ON Grants(loose_colocator);
--CREATE INDEX IF NOT EXISTS idx_grants_filer_ein_year ON Grants(filer_ein, tax_year);
-- Contributions indexes
CREATE INDEX IF NOT EXISTS idx_contributions_filer_ein ON Contributions(filer_ein);
CREATE INDEX IF NOT EXISTS idx_contributions_recipient_ein ON Contributions(recipient_ein);
CREATE INDEX IF NOT EXISTS idx_contributions_tax_year ON Contributions(tax_year);
-- Addresses indexes
CREATE INDEX IF NOT EXISTS idx_addresses_ein ON Addresses(ein);
CREATE INDEX IF NOT EXISTS idx_addresses_zip_code ON Addresses(zip_code);
CREATE INDEX IF NOT EXISTS idx_addresses_type ON Addresses(address_type);
CREATE INDEX IF NOT EXISTS idx_addresses_geocoding ON Addresses(geocoding_id);
CREATE INDEX IF NOT EXISTS idx_addresses_master_id ON Addresses(master_id);
CREATE INDEX IF NOT EXISTS idx_addresses_canonical ON Addresses(canonical_address);
CREATE INDEX IF NOT EXISTS idx_dedup_canon_groups ON Addresses (canonical_address, address_id);
create index IF NOT EXISTS idx_addresses_colocator on Addresses (colocator);
CREATE INDEX IF NOT EXISTS idx_addresses_loose_colocator ON Addresses(loose_colocator);
CREATE INDEX IF NOT EXISTS idx_addresses_canonical_covering ON Addresses(
    canonical_address,
    address_id,
    master_id,
    geocoding_id
);
-- Geocoding indexes
CREATE INDEX IF NOT EXISTS idx_geocoding_status ON Geocoding(geocoding_status);
CREATE INDEX IF NOT EXISTS idx_geocoding_canonical ON Geocoding(canonical_address);
-- ZipFiles indexes
CREATE INDEX IF NOT EXISTS idx_zipfiles_tax_year ON ZipFiles(tax_year);
CREATE INDEX IF NOT EXISTS idx_zipfiles_status ON ZipFiles(status);
-- XmlFiles indexes
CREATE INDEX IF NOT EXISTS idx_xmlfiles_zip_id ON XmlFiles(zip_id);
CREATE INDEX IF NOT EXISTS idx_xmlfiles_ein ON XmlFiles(ein);
CREATE INDEX IF NOT EXISTS idx_xmlfiles_tax_year ON XmlFiles(tax_year);
CREATE INDEX IF NOT EXISTS idx_xmlfiles_processed ON XmlFiles(processed);
-- Backfill indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_backfill_recipient_ein ON Backfill (recipient_ein);
CREATE INDEX IF NOT EXISTS idx_backfill_zip_code ON Backfill(zip_code);
CREATE INDEX IF NOT EXISTS idx_backfill_colocator ON Backfill(colocator);
CREATE INDEX IF NOT EXISTS idx_backfill_loose_colocator ON Backfill(loose_colocator);
-- PipelineProgress indexes
CREATE INDEX IF NOT EXISTS idx_pipeline_step_name ON PipelineProgress(step_name);
CREATE INDEX IF NOT EXISTS idx_pipeline_status ON PipelineProgress(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_years ON PipelineProgress(start_year, end_year);
-- Officers indexes
CREATE INDEX IF NOT EXISTS idx_officers_charity_id ON Officers(charity_id);
CREATE INDEX IF NOT EXISTS idx_officers_tax_year ON Officers(tax_year);
CREATE INDEX IF NOT EXISTS idx_officers_master_id ON Officers(master_id);
CREATE INDEX IF NOT EXISTS idx_officers_name ON Officers(last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_officers_full_name ON Officers(full_name);
CREATE INDEX IF NOT EXISTS idx_officers_colocator ON Officers(colocator);
CREATE INDEX IF NOT EXISTS idx_officers_loose_colocator ON Officers(loose_colocator);
-- Contractors indexes
CREATE INDEX IF NOT EXISTS idx_contractors_filer_ein ON Contractors(filer_ein);
CREATE INDEX IF NOT EXISTS idx_contractors_tax_year ON Contractors(tax_year);
CREATE INDEX IF NOT EXISTS idx_contractors_loose_colocator ON Contractors(loose_colocator);
-- PoliticalContributions indexes
CREATE INDEX IF NOT EXISTS idx_political_filer_ein ON PoliticalContributions(filer_ein);
CREATE INDEX IF NOT EXISTS idx_political_tax_year ON PoliticalContributions(tax_year);
CREATE INDEX IF NOT EXISTS idx_political_loose_colocator ON PoliticalContributions(loose_colocator);
-- Additional indexes for grant matching
CREATE INDEX IF NOT EXISTS idx_grants_grant_id ON Grants(grant_id);
CREATE INDEX IF NOT EXISTS idx_charities_colocator ON Charities(colocator);
-- AuthoritativeEin indexes (critical for name matching + Splink)
CREATE INDEX IF NOT EXISTS idx_authoritative_ein_name_colocator ON AuthoritativeEin(name, colocator);
CREATE INDEX IF NOT EXISTS idx_authoritative_ein_name_loose ON AuthoritativeEin(name, loose_colocator);
CREATE INDEX IF NOT EXISTS idx_charities_loose_colocator ON Charities(loose_colocator);
-- FEC Committees table
CREATE TABLE IF NOT EXISTS fec_committees (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    fec_cmte_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    treasurer_name VARCHAR,
    report_year INTEGER NOT NULL,
    colocator_id UUID,
    -- Link to Addresses or colocator
    colocation_score DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fec_cmte_id, report_year)
);
-- FEC Candidate Spendings table
CREATE TABLE IF NOT EXISTS fec_candidate_spendings (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    fec_sub_id VARCHAR NOT NULL,
    fec_cand_id VARCHAR NOT NULL,
    fec_cmte_id VARCHAR,
    spending_amount DOUBLE NOT NULL,
    spending_date TIMESTAMP NOT NULL,
    payee_name VARCHAR NOT NULL,
    purpose VARCHAR NOT NULL,
    report_year INTEGER NOT NULL,
    colocator_id UUID,
    colocation_score DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- FEC Committee Transactions table
CREATE TABLE IF NOT EXISTS fec_committee_transactions (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    fec_sub_id VARCHAR NOT NULL,
    fec_cmte_id VARCHAR NOT NULL,
    -- Recipient
    other_cmte_id VARCHAR NOT NULL,
    -- Donor
    transaction_amount DOUBLE NOT NULL,
    transaction_date TIMESTAMP NOT NULL,
    transaction_type VARCHAR NOT NULL,
    report_year INTEGER NOT NULL,
    colocator_id UUID,
    colocation_score DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- FEC Individual Contributions table
CREATE TABLE IF NOT EXISTS fec_individual_contributions (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    fec_sub_id VARCHAR NOT NULL,
    fec_cmte_id VARCHAR NOT NULL,
    contributor_name VARCHAR NOT NULL,
    contribution_amount DOUBLE NOT NULL,
    contribution_date TIMESTAMP NOT NULL,
    occupation VARCHAR,
    employer VARCHAR,
    report_year INTEGER NOT NULL,
    colocator_id UUID,
    colocation_score DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- FEC Operating Expenditures table
CREATE TABLE IF NOT EXISTS fec_operating_expenditures (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    fec_sub_id VARCHAR NOT NULL,
    fec_cmte_id VARCHAR NOT NULL,
    payee_name VARCHAR NOT NULL,
    expenditure_amount DOUBLE NOT NULL,
    expenditure_date TIMESTAMP NOT NULL,
    purpose VARCHAR NOT NULL,
    report_year INTEGER NOT NULL,
    colocator_id UUID,
    colocation_score DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Indexes for FEC tables
CREATE INDEX IF NOT EXISTS idx_fec_committees_id ON fec_committees(fec_cmte_id);
CREATE INDEX IF NOT EXISTS idx_fec_committees_year ON fec_committees(report_year);
CREATE INDEX IF NOT EXISTS idx_fec_candidate_spendings_cand_id ON fec_candidate_spendings(fec_cand_id);
CREATE INDEX IF NOT EXISTS idx_fec_candidate_spendings_year ON fec_candidate_spendings(report_year);
CREATE INDEX IF NOT EXISTS idx_fec_committee_transactions_cmte_id ON fec_committee_transactions(fec_cmte_id);
CREATE INDEX IF NOT EXISTS idx_fec_committee_transactions_year ON fec_committee_transactions(report_year);
CREATE INDEX IF NOT EXISTS idx_fec_individual_contributions_cmte_id ON fec_individual_contributions(fec_cmte_id);
CREATE INDEX IF NOT EXISTS idx_fec_individual_contributions_year ON fec_individual_contributions(report_year);
CREATE INDEX IF NOT EXISTS idx_fec_operating_expenditures_cmte_id ON fec_operating_expenditures(fec_cmte_id);
CREATE INDEX IF NOT EXISTS idx_fec_operating_expenditures_year ON fec_operating_expenditures(report_year);
-- Optional: Link to Charities if EIN matches
ALTER TABLE fec_committees
ADD COLUMN charity_ein VARCHAR(9);
-- CREATE INDEX IF NOT EXISTS idx_fec_committees_charity_ein ON fec_committees(charity_ein);
-- Similar for other tables if needed

-- Medicare / Medicaid CMS provider data (NPPES + T-MSIS spending + code lookups)
CREATE TABLE IF NOT EXISTS hcpcs_codes (
    code VARCHAR PRIMARY KEY,
    description VARCHAR,
    long_description VARCHAR
);
CREATE TABLE IF NOT EXISTS noc_codes (
    code VARCHAR PRIMARY KEY,
    description VARCHAR
);
CREATE TABLE IF NOT EXISTS nppes_code_values (
    field_name VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    description VARCHAR,
    PRIMARY KEY (field_name, code)
);
CREATE TABLE IF NOT EXISTS medicare_providers (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    npi VARCHAR NOT NULL UNIQUE,
    entity_type_code VARCHAR,
    ein VARCHAR,
    organization_name VARCHAR,
    provider_last_name VARCHAR,
    provider_first_name VARCHAR,
    provider_middle_name VARCHAR,
    provider_credential VARCHAR,
    enumeration_date DATE,
    last_update_date DATE,
    is_sole_proprietor VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS medicare_provider_spending (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    billing_provider_npi VARCHAR NOT NULL,
    billing_provider_name VARCHAR,
    servicing_provider_npi VARCHAR,
    servicing_provider_name VARCHAR,
    hcpcs_code VARCHAR,
    claim_from_month VARCHAR,
    total_unique_beneficiaries BIGINT,
    total_claims BIGINT,
    total_paid DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_medicare_spending_billing_npi ON medicare_provider_spending(billing_provider_npi);
CREATE INDEX IF NOT EXISTS idx_medicare_spending_hcpcs ON medicare_provider_spending(hcpcs_code);
CREATE INDEX IF NOT EXISTS idx_medicare_providers_npi ON medicare_providers(npi);

-- Consolidated Medicare spend (built by build_medicare_provider_rollup.py from line grain).
-- Most billing NPIs use a short HCPCS list (median ~4 types); these tables make $ ranking
-- and type/$ detail pages cheap without scanning medicare_provider_spending (230M+).
CREATE TABLE IF NOT EXISTS medicare_provider_hcpcs (
    npi VARCHAR NOT NULL,
    hcpcs_code VARCHAR NOT NULL,
    spend_rows BIGINT,
    total_claims BIGINT,
    total_beneficiaries BIGINT,
    total_paid DOUBLE,
    first_month VARCHAR,
    last_month VARCHAR
);
CREATE TABLE IF NOT EXISTS medicare_provider_rollup (
    npi VARCHAR NOT NULL,
    hcpcs_type_count BIGINT,
    spend_rows BIGINT,
    total_claims BIGINT,
    total_beneficiaries BIGINT,
    total_paid DOUBLE,
    first_month VARCHAR,
    last_month VARCHAR,
    top_hcpcs_code VARCHAR,
    top_hcpcs_paid DOUBLE,
    provider_id UUID,
    organization_name VARCHAR,
    person_name VARCHAR,
    entity_type_code VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_medicare_provider_hcpcs_npi ON medicare_provider_hcpcs(npi);
CREATE INDEX IF NOT EXISTS idx_medicare_provider_hcpcs_code ON medicare_provider_hcpcs(hcpcs_code);
CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_npi ON medicare_provider_rollup(npi);
CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_paid ON medicare_provider_rollup(total_paid);
CREATE INDEX IF NOT EXISTS idx_medicare_provider_rollup_provider_id ON medicare_provider_rollup(provider_id);

-- Treasury OFAC SDN sanctions (Treasury sanctions list ingest)
CREATE TABLE IF NOT EXISTS sanctioned_entities (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    ofac_uid VARCHAR NOT NULL UNIQUE,
    primary_name VARCHAR,
    entity_type VARCHAR,
    entity_subtype VARCHAR,
    list_type VARCHAR,
    list_date DATE,
    remarks VARCHAR,
    source_issue_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sanctioned_names (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    entity_id UUID NOT NULL,
    name VARCHAR NOT NULL,
    alias_type VARCHAR,
    is_primary BOOLEAN DEFAULT FALSE,
    low_quality BOOLEAN DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS sanctioned_identifiers (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    entity_id UUID NOT NULL,
    id_type VARCHAR,
    id_number VARCHAR,
    country VARCHAR
);
CREATE TABLE IF NOT EXISTS sanctioned_programs (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    entity_id UUID NOT NULL,
    program_code VARCHAR NOT NULL,
    sanctions_type VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_sanctioned_names_entity ON sanctioned_names(entity_id);
CREATE INDEX IF NOT EXISTS idx_sanctioned_names_name ON sanctioned_names(name);
CREATE INDEX IF NOT EXISTS idx_sanctioned_identifiers_entity ON sanctioned_identifiers(entity_id);
CREATE INDEX IF NOT EXISTS idx_sanctioned_programs_entity ON sanctioned_programs(entity_id);
CREATE INDEX IF NOT EXISTS idx_sanctioned_programs_code ON sanctioned_programs(program_code);

-- FMCSA DOT motor carrier census (Company Census File)
CREATE TABLE IF NOT EXISTS dot_carriers (
    id UUID DEFAULT uuidv7() PRIMARY KEY,
    dot_number VARCHAR NOT NULL UNIQUE,
    legal_name VARCHAR,
    dba_name VARCHAR,
    status_code VARCHAR,
    carrier_operation VARCHAR,
    business_org_desc VARCHAR,
    phone VARCHAR,
    email_address VARCHAR,
    power_units INTEGER,
    truck_units INTEGER,
    fleetsize VARCHAR,
    docket1 VARCHAR,
    docket1prefix VARCHAR,
    mcs150_date DATE,
    add_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dot_carriers_legal_name ON dot_carriers(legal_name);
CREATE INDEX IF NOT EXISTS idx_dot_carriers_dba_name ON dot_carriers(dba_name);

-- Zips table for geo-matching (loaded from compressed TSV in repo)
CREATE TABLE IF NOT EXISTS Zips_raw (
    country_code VARCHAR,
    zip VARCHAR,
    place_name VARCHAR,
    admin_name1 VARCHAR,
    admin_code1 VARCHAR,
    admin_name2 VARCHAR,
    admin_code2 VARCHAR,
    admin_name3 VARCHAR,
    admin_code3 VARCHAR,
    lat DOUBLE,
    lon DOUBLE,
    accuracy INTEGER
);
COPY Zips_raw
FROM '/Volumes/Data/irs_zips/US_zips.txt.gz' (
        FORMAT CSV,
        DELIMITER '\t',
        HEADER FALSE,
        IGNORE_ERRORS TRUE,
        NULL_PADDING TRUE,
        COMPRESSION 'gzip'
    );
CREATE TABLE IF NOT EXISTS Zips AS
SELECT zip,
    lat,
    lon
FROM Zips_raw
WHERE country_code = 'US';
CREATE INDEX IF NOT EXISTS idx_zips_zip ON Zips(zip);
-- ============================================================================
-- IRS BMF Table (full EO BMF data, excluding raw address fields)
-- ============================================================================
CREATE TABLE IF NOT EXISTS IrsBmf (
    irsbmf_id UUID PRIMARY KEY,
    -- UUID7 generated in Python
    ein VARCHAR NOT NULL,
    name VARCHAR,
    ico VARCHAR,
    group_code VARCHAR,
    subsection VARCHAR,
    affiliation BIGINT,
    classification VARCHAR,
    ruling VARCHAR,
    deductibility BIGINT,
    foundation VARCHAR,
    activity VARCHAR,
    organization BIGINT,
    status VARCHAR,
    tax_period BIGINT,
    asset_cd BIGINT,
    income_cd BIGINT,
    filing_req_cd VARCHAR,
    pf_filing_req_cd BIGINT,
    acct_pd VARCHAR,
    asset_amt DECIMAL(18, 2),
    income_amt DECIMAL(18, 2),
    revenue_amt DECIMAL(18, 2),
    ntee_cd VARCHAR,
    sort_name VARCHAR,
    source_file VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Indexes for fast lookup and resume paging
CREATE INDEX IF NOT EXISTS idx_irsbmf_ein ON IrsBmf(ein);
CREATE INDEX IF NOT EXISTS idx_irsbmf_name ON IrsBmf(name);
CREATE INDEX IF NOT EXISTS idx_irsbmf_ntee ON IrsBmf(ntee_cd);
CREATE INDEX IF NOT EXISTS idx_irsbmf_source ON IrsBmf(source_file);
CREATE INDEX IF NOT EXISTS idx_irsbmf_created ON IrsBmf(created_at);
-- Composite index useful for common queries
CREATE INDEX IF NOT EXISTS idx_irsbmf_ein_name ON IrsBmf(ein, name);
-- Optional: Index on status if you plan to filter active/inactive orgs
-- CREATE INDEX IF NOT EXISTS idx_irsbmf_status     ON IrsBmf(status);