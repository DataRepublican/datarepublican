# Grok TODO: Complete Codebase Audit and Refactoring Plan

## Overview
This document provides a comprehensive audit of all Python files in the 990Tools codebase, organized by architectural layer. Each file and method is analyzed for PDC compliance, architectural consistency, and required refactoring work.

## Base Architecture Layer

### `database_operations.py`
**Status**: ✅ PARTIALLY COMPLETE - Core methods refactored, legacy methods marked deprecated

#### Key Methods - COMPLETED ✅
- `GENERIC_INSERT()` - ✅ Implemented, enforces ownership order
- `INSERT_BY_TYPE()` - ✅ Implemented, for PDC integration
- `bulk_insert()` - ✅ Core insert method with performance optimizations
- `execute_query()` - ✅ Thread-safe query execution
- `select_dataclass()` - ✅ Generic SELECT with reflection

#### Methods Needing Work
- `insert_zip_file()` - ✅ Uses bulk_insert (good)
- `insert_xml_file()` - ✅ Uses bulk_insert (good)
- Legacy `insert_*()` methods - ✅ Deleted

### `pending_database_context.py`
**Status**: ✅ COMPLETE - Fully PDC-compliant

#### Key Methods - COMPLETED ✅
- `save_to_database()` - ✅ Primary execution method
- `addObjectToDatabase()` - ✅ Type-based object collection
- `merge()` - ✅ Context merging for parallel processing
- `_execute_operation()` - ✅ Operation execution dispatcher

### `base_processor.py`
**Status**: ⚠️ PARTIALLY COMPLETE - Mixed PDC/operation models

#### Key Classes/Methods
- `ProcessorCoordinator.process_producer_consumer()` - ✅ PDC-based
- `BaseProducer.collect_contexts()` - ✅ PDC method exists
- `BaseConsumer.execute_contexts_batch()` - ✅ PDC method exists
- `collect_operations()` - ⚠️ DEPRECATED wrapper (acceptable for compatibility, should delete)
- Various `_process_*_operations()` methods - ❌ Still operation-based, need PDC conversion

## Processor Layer

### Core Processors (High Priority)

#### `xml_processor.py`
**Status**: ✅ COMPLETE - PDC-compliant
- Uses PDC accumulation correctly
- `process_batch()` creates PDC contexts
- Integrates with consumer via PDC

#### `zip_processor.py`
**Status**: ✅ COMPLETE - PDC-compliant
- Uses PDC accumulation correctly
- `process_batch()` creates PDC contexts

#### `irsfetch_processor.py`
**Status**: ✅ COMPLETE - Producer-only, PDC-compliant
- Correctly uses PDC accumulation
- No consumer operations (download-only)

#### `address_deduplication_processor.py`
**Status**: ✅ COMPLETE - PDC-compliant
- Uses PDC accumulation correctly
- Creates geocoding records via operations

#### `geocoding_api_processor.py`
**Status**: ✅ COMPLETE - PDC-compliant
- Uses PDC accumulation correctly
- Calls Census API and updates addresses

### Additional Processors (NOTYET - Need Complete Rewrite)

#### `export_processor.py`
**Status**: NOTYET
- Not analyzed - needs complete rewrite for PDC compliance

#### `extract_processor.py`
**Status**: NOTYET
- Not analyzed - needs complete rewrite for PDC compliance

#### `photo_processor.py`
**Status**: NOTYET
- Not analyzed - needs complete rewrite for PDC compliance

#### `officer_deduplication_processor.py`
**Status**: NOTYET
- Not analyzed - needs complete rewrite for PDC compliance

#### `stats_processor.py`
**Status**: N/A
- Run after each step to gather table stats, special case. 

## Model Layer

### `models/base.py`
**Status**: ✅ COMPLETE - BaseModel class
- `prep_for_insert()` - ✅ UUID generation
- `set_id_if_needed()` - ✅ ID management
- `get_db_field_names()` - ✅ Field mapping

### `models/charity.py`
**Status**: ✅ COMPLETE - Charity dataclass
- Factory methods create related objects
- Proper ownership relationships

### `models/address.py`
**Status**: ✅ COMPLETE - Address dataclass
- Canonical address building
- PO Box detection
- Geocoding integration

### `models/zip_file.py`
**Status**: ✅ COMPLETE - ZipFile dataclass

### Other Model Files
**Status**: ✅ COMPLETE - Standard dataclasses
- `models/grant.py`
- `models/officer.py`
- `models/contractor.py`
- `models/political_contribution.py`

## Utility Layer

### `logging_utils.py`
**Status**: ✅ COMPLETE - Progress bar management
- `start_progress_reporting()` - ✅ Progress bar initialization
- `update_progress()` - ✅ Thread-safe progress updates

### `config.py`
**Status**: ✅ COMPLETE - Global configuration
- `global_config.max_files` - ✅ Test limiting
- `global_config.log_sql` - ✅ SQL logging control

### `constants.py`
**Status**: ✅ COMPLETE - Application constants
- `VALID_STATES` - ✅ State validation
- `CURRENT_PROCESSING_VERSION` - ✅ Version tracking

## Test Files

## Infrastructure Files

### `irs990processor.py`
**Status**: ✅ COMPLETE - Main entry point
- Command-line argument parsing
- Stage coordination via `--start-step`/`--stop-step`

### `uuid7.py`
**Status**: ✅ COMPLETE - UUID generation
- Time-ordered UUIDs for efficient indexing

## Priority Refactoring Tasks

### HIGH PRIORITY (Blockers)
1. **Complete Base Processor PDC Conversion**
   - Convert all `_process_*_operations()` methods to PDC
   - Remove operation-based compatibility methods
   - Ensure all processors use PDC consistently

2. **Clean Up Legacy Methods**
   - Remove deprecated `insert_*()` methods after full PDC adoption
   - Clean up operation-based compatibility code

### MEDIUM PRIORITY (Architecture)
3. **Processor Standardization**
   - Ensure all processors follow PDC pattern
   - Standardize threading models
   - Consistent error handling

4. **Documentation Updates**
   - Update Architecture.md with PDC details
   - Document progress bar integration
   - Add testing guidelines

### LOW PRIORITY (Future Processors)
5. **NOTYET Processors**
   - Complete rewrite of export_processor.py
   - Complete rewrite of extract_processor.py
   - Complete rewrite of photo_processor.py
   - Complete rewrite of officer_deduplication_processor.py
   - Complete rewrite of stats_processor.py

## Success Criteria

### ✅ PDC Architecture Fully Implemented
- All processors use PDC accumulation
- GENERIC_INSERT and INSERT_BY_TYPE are primary insert methods
- Ownership order strictly enforced
- Thread-local connections prevent writer conflicts

### ✅ Progress Tracking Working
- Progress bar shows real-time updates
- --max-files limits work for testing
- --bytes flag supported for detailed progress

### ✅ Code Quality
- Comprehensive docstrings added
- Architectural violations resolved
- Consistent error handling
- Thread-safe operations

## Implementation Notes

### PDC Pattern Enforcement
```
Producer Thread:
  context = PendingDatabaseContext()
  context.addObjectToDatabase(obj)
  return context

Consumer Thread:
  ids = context.save_to_database(db_ops)
  # IDs returned for relationship tracking
```

### Progress Integration
```
# Scope query first
total_items = db_ops.execute_query("SELECT COUNT(*) FROM table")[0][0]

# Producers emit PROGRESS_UPDATE operations
context.addOperationToDatabase(DatabaseOperation(
    DatabaseOperationType.PROGRESS_UPDATE,
    {"count": processed_count}
))
```

### Testing with Limits
```
# In config.py
global_config.max_files = 100  # Limit for testing

# All producers check this limit
if global_config.max_files and processed >= global_config.max_files:
    break