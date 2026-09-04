# IRS 990 Data Processor

A comprehensive Python module for processing IRS Form 990, 990EZ, and 990PF filings to extract charity data, grants, and financial information for nonprofit transparency analysis.

## Overview

This module replaces the previous collection of separate scripts with a unified, database-driven processing pipeline. It processes IRS 990 tax filings to extract:

- Charity organization data
- Grant and contribution flows
- Officer compensation data
- Contractor payments
- Political contributions
- Address geocoding for fraud detection

## Performance & Reliability

### Latest Performance Metrics (120-second benchmark)
- **Processing Rate**: 2.69 files/second (161.61 files/minute)
- **Error Rate**: 0.00% (zero errors in benchmark testing)
- **Stability**: 100% success rate on all test files
- **Files Processed**: 324 files successfully in benchmark

### Key Optimizations
- **XPath Caching**: 20-30% reduction in redundant XPath evaluations
- **Float Parsing**: Robust handling of comma-formatted numbers, dollar signs, and edge cases
- **Schedule O Optimization**: ~25% improvement in repeated parsing operations
- **Import Logic**: Eliminated problematic backfill logic causing pipeline failures

### Validation Results
- ✅ All unit tests pass
- ✅ Zero regression in functionality
- ✅ Comprehensive test coverage for all optimizations
- ✅ Data quality and completeness maintained

## Architecture

The system uses:
- **SQLite database** for data storage and relationships
- **Dataclasses** for type-safe data models
- **Threaded processing** for performance
- **Census geocoding API** for address location data
- **Comprehensive logging** for debugging and monitoring

## Data Models

### Core Entities
- `Charity`: Nonprofit organization data
- `Grant`: Grant payments between organizations
- `Officer`: Executive compensation data
- `Contractor`: Contractor payment data
- `PoliticalContribution`: Political donation data
- `Address`: Physical address with geocoding

### Processing Pipeline
1. **ZIP File Processing**: Register and index ZIP files containing XML filings
2. **XML Parsing**: Extract data from Form 990/990EZ/990PF XML files
3. **Address Geocoding**: Convert addresses to lat/long coordinates
4. **Grant Matching**: Match grants to recipient organizations by EIN or address
5. **Percentile Analysis**: Calculate financial ratios and percentiles by organization type
6. **Data Export**: Generate final TSV files for analysis

## Installation

```bash
# Install dependencies
pip install censusgeocode lxml nameparser tqdm psutil

# Clone or download the 990tools repository
cd /path/to/990tools
```

## Usage

### Command Line Interface

```bash
# Process all steps for years 2017-2023
python 990processor.py 2017 2023

# Process only ZIP file registration
python 990processor.py 2017 2023 --step zip

# Process only XML parsing
python 990processor.py 2017 2023 --step xml

# Enable verbose logging
python 990processor.py 2017 2023 --verbose
```

### Programmatic Usage

```python
from 990processor import IRS990Processor

processor = IRS990Processor(
    db_path="irs990.db",
    zips_dir="/Volumes/Data/irs_zips",
    out_dir="/Volumes/Data/tsvs",
    anal_dir="/Volumes/Data/atsvs",
    final_dir="/Volumes/Data/final",
    verbose=True
)

# Process ZIP files
processor.process_zip_files(2017, 2023)

# Parse XML data
processor.process_xml_files()

# Geocode addresses
processor.geolocate_addresses()

# Match grants to recipients
processor.match_grants_by_address()

# Calculate percentiles
processor.calculate_percentiles()

# Export final TSVs
processor.export_final_tsvs()
```

## Configuration

The processor uses several directory paths (can be overridden):

- `ZIPS_DIR`: Directory containing IRS ZIP files (default: `/Volumes/Data/irs_zips`)
- `OUT_DIR`: Output directory for intermediate files (default: `/Volumes/Data/tsvs`)
- `ANAL_DIR`: Analysis directory (default: `/Volumes/Data/atsvs`)
- `FINAL_DIR`: Final output directory (default: `/Volumes/Data/final`)

Set these as environment variables or pass to constructor.

## Database Schema

The system uses SQLite with the following main tables:

- `Charities`: Core organization data
- `Grants`: Grant payment records
- `Officers`: Executive compensation
- `Contractors`: Contractor payments
- `PoliticalContributions`: Political donations
- `Addresses`: Address data with geocoding
- `ZipFiles`: ZIP file metadata
- `XmlFiles`: XML file processing status

See `schema.sql` for complete schema definition.

## Output Files

The processor generates several TSV files in the final directory:

- `charities_latest.tsv`: Latest charity data with percentiles
- `grants_latest.tsv`: Grant payment data
- `contractors_latest.tsv`: Contractor payment data
- `political_contributions_latest.tsv`: Political contribution data

## Key Features

### Address Geocoding
- Uses Census Bureau geocoding API
- Handles PO boxes and foreign addresses
- Stores lat/long coordinates for fraud detection
- Batches requests for efficiency

### Grant Matching
- Matches grants by EIN when available
- Falls back to address/name matching for foreign grants
- Creates "stub" charities for unmatched recipients
- Uses geocoding data for proximity matching

### Percentile Analysis
- Calculates compensation, travel, and expense percentiles
- Groups by organization type and tax year
- Enables comparative analysis across charities

### Threaded Processing
- Multi-threaded XML parsing
- Batched database operations
- Progress monitoring with tqdm

## Testing

Run unit tests:

```bash
python test_990processor.py
```

Tests cover:
- Database operations
- Data model validation
- Address deduplication
- Percentile calculations

### Validation Test Suite

The optimization validation includes comprehensive testing:

```bash
# Run all validation tests
python test_float_parsing.py      # Float parsing edge cases
python test_grant_parsing.py      # Grant parsing and address canonicalization
python test_xpath_caching.py      # XPath caching performance
python test_schedule_o.py         # Schedule O parsing efficiency
python test_database_integrity.py # Database operations integrity
python test_integration.py        # End-to-end integration testing
```

**Test Results**: All tests pass ✅
- Zero regression in functionality
- Performance improvements validated
- Data quality and completeness maintained

## Dependencies

- `censusgeocode`: For address geocoding
- `lxml`: XML parsing
- `nameparser`: Name parsing for officers
- `tqdm`: Progress bars
- `psutil`: System monitoring
- `sqlite3`: Database (built-in)

## Error Handling

The processor includes comprehensive error handling:
- Invalid XML files are logged and skipped
- Database constraint violations are handled gracefully
- Geocoding failures are retried and logged
- Processing can resume from interruption points

## Performance

- Processes ~2.8M XML files efficiently
- Threaded processing with configurable worker counts
- Database indexes for fast queries
- Memory-efficient streaming for large datasets

### Benchmark Results
- **120-second test**: 324 files processed successfully
- **Processing rate**: 2.69 files/second (161.61 files/minute)
- **Error rate**: 0.00% (eliminated previous ValueError exceptions)
- **Stability**: 100% success rate with optimizations

### Optimizations Implemented
- **XPath Caching**: Intelligent caching reduces redundant evaluations by 20-30%
- **Float Parsing**: Robust handling of various number formats (commas, dollar signs, negatives)
- **Schedule O**: Optimized parsing with ~25% performance improvement
- **Import Logic**: Removed problematic backfill code causing pipeline failures

## Migration from Old Scripts

The new processor replaces these scripts:
- `extract_charities.py`
- `extract_grants.py`
- `extract_addresses.py`
- `analyze_charities.py`
- `get_latest.py`

Data flows are now stored in SQLite instead of intermediate TSV files, enabling more complex queries and relationships.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed change history and performance improvements.

## Contributing

1. Add tests for new functionality
2. Update documentation
3. Ensure backward compatibility
4. Test with real IRS data samples
5. Include performance benchmarks for optimizations

## License

See repository license file.