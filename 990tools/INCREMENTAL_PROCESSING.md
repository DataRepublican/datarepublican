# Incremental Processing for IRS 990 Data

## Overview

This document describes the version tracking system implemented to enable incremental processing of IRS 990 tax filings. This system allows the pipeline to efficiently handle monthly data updates without reprocessing all 2.8M+ XML files.

## Schema Changes

### XmlFiles Table Enhancement

Added a new `processing_version` column to the `XmlFiles` table:

```sql
processing_version INTEGER DEFAULT 0,
-- Version of processing pipeline used (for incremental updates)
```

### Processing Version Constant

Added a constant in `990processor.py`:

```python
CURRENT_PROCESSING_VERSION = 1  # Increment when processing logic changes
```

## How Incremental Processing Works

### 1. Version Tracking Mechanism

- Each XML file record in the database now includes a `processing_version` field
- When a file is successfully processed, it's marked with the current processing version
- Files are considered for reprocessing if they are unprocessed OR have an outdated version

### 2. Processing Logic Updates

The query for finding files to process has been updated:

```sql
-- Before: Only unprocessed files
SELECT xml_id, zip_id, filename, internal_path
FROM XmlFiles
WHERE processed = FALSE

-- After: Unprocessed OR outdated version files
SELECT xml_id, zip_id, filename, internal_path
FROM XmlFiles
WHERE processed = FALSE OR processing_version < ?
```

### 3. Version Updates

When files are processed (successfully or with errors), they are marked with the current version:

```sql
UPDATE XmlFiles SET processed = TRUE, processing_version = ? WHERE xml_id = ?
```

## Workflow for Monthly Updates

### Initial Processing (Version 1)
1. All XML files start with `processing_version = 0`
2. Pipeline processes all files, marking them as `processing_version = 1`
3. Database contains complete processed data

### Monthly Update Processing
1. New IRS data arrives (new ZIP files or updated existing files)
2. Pipeline identifies files needing processing:
   - New files: `processed = FALSE`
   - Existing files with old versions: `processing_version < CURRENT_PROCESSING_VERSION`
3. Only outdated/new files are reprocessed
4. Files are marked with new version after processing

### Future Processing Logic Changes
1. Increment `CURRENT_PROCESSING_VERSION` (e.g., to 2)
2. Update processing logic as needed
3. Run pipeline - all previously processed files will be reprocessed with new logic
4. Files get marked with version 2

## Benefits

### Performance
- Monthly updates only process new/changed files instead of all 2.8M files
- Significant time and resource savings

### Data Integrity
- Version tracking ensures all files are processed with consistent logic
- Prevents partial updates or mixed processing versions

### Flexibility
- Easy to trigger full reprocessing by incrementing the version constant
- Backward compatible with existing processed files

## Implementation Details

### Files Modified
- `schema.sql`: Added `processing_version` column to XmlFiles table
- `990processor.py`: Updated dataclass, constants, queries, and update statements
- `profile_pipeline.py`: Updated queries to use version checking

### Migration
- Existing databases will have `processing_version = 0` for all existing records
- First run after update will process all files to bring them to current version
- Subsequent runs will only process new files or files needing updates

## Usage Examples

### Normal Monthly Processing
```bash
# Process only new files and files with outdated versions
python3 990processor.py 2024 2024 --step xml
```

### Force Full Reprocessing
```python
# In 990processor.py, increment CURRENT_PROCESSING_VERSION
CURRENT_PROCESSING_VERSION = 2

# Run pipeline - all files will be reprocessed
```

### Check Processing Status
```sql
-- Files needing processing
SELECT COUNT(*) FROM XmlFiles
WHERE processed = FALSE OR processing_version < 1;

-- Processing version distribution
SELECT processing_version, COUNT(*) as count
FROM XmlFiles
GROUP BY processing_version
ORDER BY processing_version;
```

## Future Enhancements

### Version-Specific Logic
- Could implement version-specific processing logic if needed
- Allow gradual rollout of processing changes

### Processing History
- Could add a processing history table to track when files were processed at each version
- Useful for debugging and audit trails

### Selective Reprocessing
- Could add flags to force reprocessing of specific EINs or date ranges
- Useful for targeted data fixes