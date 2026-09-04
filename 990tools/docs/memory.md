# IRS 990 Processing Codebase Memory

## Codebase Structure

### Overview
- **Unified Python module** for processing IRS Form 990, 990EZ, and 990PF filings
- **Database-driven pipeline** replacing separate scripts with SQLite storage
- **Processes ~2.8M XML files** efficiently with threaded processing
- **Extracts nonprofit transparency data**: charity info, grants, officer compensation, contractors, political contributions
- **Geocoding integration** using Census Bureau API for address location data (10m precision)

### Core Components
- `irs990processor.py` - Main unified processor class
- `parse_990.py`, `parse_990ez.py`, `parse_990pf.py` - Form-specific XML parsers
- `xpath_utils.py` - XPath evaluation with intelligent caching
- `parse_utils.py` - Robust float parsing and data extraction utilities
- `geolocation_processor.py` - Address geocoding and coordinate processing
- `address_matcher.py` - Grant recipient matching by EIN/address
- `database_operations.py` - SQLite database interface and operations

### Data Models (Dataclasses)
- `Charity` - Nonprofit organization data with financial metrics and percentiles
- `Grant` - Grant payment records between organizations
- `Officer` - Executive compensation data
- `Contractor` - Contractor payment information
- `PoliticalContribution` - Political donation data
- `Address` - Physical address with geocoding coordinates

## Address Processing
- Addresses are extracted in pieces from the XML files to handle complex address structures.
- For filer addresses, the owner_id in the Address record is set to the charity_id.

### Processing Pipeline
1. **ZIP File Registration** - Index and register IRS ZIP files
2. **XML Parsing** - Extract data from Form 990/990EZ/990PF XML files
3. **Address Geocoding** - Convert addresses to lat/long coordinates
4. **Grant Matching** - Match grants to recipient organizations by EIN or address
5. **Percentile Analysis** - Calculate financial ratios and percentiles by organization type
6. **Data Export** - Generate final TSV files for analysis

## Database Schema

### Core Tables
- **Charities** - EIN, tax_year, financial metrics, percentiles, form metadata
- **Grants** - Filer EIN, recipient EIN, grant amounts, tax year
- **Addresses** - EIN, canonical addresses, geocoding coordinates, colocator data
- **Geocoding** - Cached geocoding results with status tracking
- **Officers** - Charity executive compensation data
- **Contractors** - Contractor payment records
- **PoliticalContributions** - Political donation data

### Metadata Tables
- **ZipFiles** - ZIP file registration and processing status
- **XmlFiles** - XML file metadata within ZIPs, processing version tracking
- **PipelineProgress** - Processing pipeline status and progress tracking

### Key Features
- Foreign key constraints enabled (`PRAGMA foreign_keys = ON`)
- Comprehensive indexes for query performance
- UNIQUE constraints prevent duplicate records
- Triggers for automatic timestamp updates
- Referential integrity maintained across all relationships

## Development Guidelines

### Performance Optimizations
- **XPath Caching**: 20-30% reduction in redundant evaluations using root element ID + expression + namespace keys
- **Float Parsing**: Robust handling of comma-separated, dollar-sign prefixed, and negative number formats
- **Schedule O Optimization**: ~25% improvement in repeated parsing operations
- **Threaded Processing**: Multi-threaded XML parsing and geocoding with configurable workers
- **Memory Efficiency**: Automatic cache cleanup per document, efficient object reuse

### Error Handling & Reliability
- **Zero Error Rate**: Eliminated ValueError exceptions through robust parsing
- **Graceful Failures**: Invalid XML files logged and skipped, geocoding failures retried
- **Resume Capability**: Processing can restart from interruption points
- **Comprehensive Logging**: Debug and monitoring information for troubleshooting

### Testing & Validation
- **Unit Tests**: Core functionality, database operations, data model validation
- **Integration Tests**: End-to-end pipeline validation
- **Optimization Tests**: XPath caching, float parsing, Schedule O performance
- **Benchmarking**: 120-second tests with 2.69 files/second processing rate

### Dependencies
- `duckdb>=0.9.0` - Database operations
- `lxml>=4.9.0` - XML parsing
- `requests>=2.28.0` - HTTP requests for geocoding
- `python-dateutil>=2.8.0` - Date parsing utilities

### Migration & Compatibility
- **Backward Compatible**: No breaking changes from old separate scripts
- **Automatic Migration**: Existing scripts work unchanged with performance improvements
- **Gradual Adoption**: Can process recent years with new processor, legacy with old scripts
- **Data Integrity**: All existing TSV output formats maintained

### Configuration
- **Environment Variables**: `ZIPS_DIR`, `OUT_DIR`, `ANAL_DIR`, `FINAL_DIR`
- **Database Path**: Configurable SQLite database location
- **Step-by-Step Processing**: Can run individual pipeline steps for debugging
- **Verbose Logging**: Detailed progress and performance metrics

### Best Practices
- Read https://raw.githubusercontent.com/twinforces/grok-prompts/refs/heads/better-code/better_code.j2 for coding instructions.
- Add comprehensive tests for new functionality
- Include performance benchmarks for optimizations
- Maintain backward compatibility
- Update documentation for changes
- Monitor error logs and performance metrics regularly
- The live database is in /Volumes/Data/final/irs990.duckdb always use that if you want real data. 