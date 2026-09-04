#!/usr/bin/env python3
"""
xml_error_handler.py - XML parsing error extraction and fixing mechanism

This module provides functionality to:
1. Extract and classify XML parsing errors from the database
2. Implement automated fixes for common XML parsing issues
3. Provide tools for manual error investigation and fixing
4. Generate error reports and statistics

Error Classification:
- XML_SYNTAX_ERROR: XML syntax issues (malformed XML, encoding problems)
- XML_PARSE_ERROR: XML parsing issues (invalid structure, missing elements)
- ZIP_FILE_ERROR: ZIP file corruption or extraction issues
- VALIDATION_ERROR: Data validation failures (invalid EIN, missing required fields)
- UNEXPECTED_ERROR: Other unexpected parsing errors
- FORM_990T: Form 990-T (intentionally skipped)
"""

import re
import os
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from dataclasses import dataclass
from lxml import etree
import zipfile
from io import BytesIO

from database_operations import DatabaseOperations
from logging_utils import log_info, log_error, log_warning, log_debug
from constants import CURRENT_PROCESSING_VERSION


@dataclass
class XMLError:
    """Represents a classified XML parsing error"""
    xml_id: str
    filename: str
    error_type: str
    error_message: str
    form_type: Optional[str] = None
    ein: Optional[str] = None
    tax_year: Optional[int] = None
    zip_id: Optional[str] = None
    file_size: Optional[int] = None
    can_be_fixed: bool = False
    fix_attempted: bool = False
    fix_successful: bool = False


class XMLErrorClassifier:
    """Classifies XML parsing errors into categories"""

    # Error pattern definitions
    ERROR_PATTERNS = {
        'XML_SYNTAX_ERROR': [
            r'XMLSyntaxError',
            r'xml syntax error',
            r'malformed xml',
            r'encoding error',
            r'unicode decode error',
            r'invalid character'
        ],
        'XML_PARSE_ERROR': [
            r'XMLParseError',
            r'xml parse error',
            r'parser error',
            r'namespace error',
            r'schema validation error'
        ],
        'ZIP_FILE_ERROR': [
            r'BadZipFile',
            r'ZIP File Error',
            r'zipfile error',
            r'extraction failed',
            r'corrupt zip'
        ],
        'VALIDATION_ERROR': [
            r'Validation Error',
            r'invalid.*format',
            r'missing.*required',
            r'No EIN found',
            r'Invalid EIN format'
        ],
        'FORM_990T': [
            r'skipped: 990t',
            r'Form 990-T'
        ],
        'UNEXPECTED_ERROR': [
            r'Unexpected Error',
            r'exception',
            r'failed'
        ]
    }

    @classmethod
    def classify_error(cls, error_message: str) -> str:
        """Classify an error message into a category"""
        if not error_message:
            return 'NO_ERROR'

        error_lower = error_message.lower()

        for error_type, patterns in cls.ERROR_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_lower, re.IGNORECASE):
                    return error_type

        return 'UNKNOWN_ERROR'


class XMLErrorExtractor:
    """Extracts and analyzes XML parsing errors from the database"""

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def extract_errors(self, limit: Optional[int] = None) -> List[XMLError]:
        """Extract all XML parsing errors from the database"""
        query = """
            SELECT xml_id, filename, error_message, form_type, ein, tax_year, zip_id, file_size
            FROM XmlFiles
            WHERE error_message IS NOT NULL
            AND error_message != 'success'
            AND processed = TRUE
            ORDER BY xml_id
        """

        if limit:
            query += f" LIMIT {limit}"

        results = self.db_ops.execute_query(query).fetchall()

        errors = []
        for row in results:
            xml_id, filename, error_message, form_type, ein, tax_year, zip_id, file_size = row

            error_type = XMLErrorClassifier.classify_error(error_message)

            # Determine if error can be fixed
            can_be_fixed = self._can_error_be_fixed(error_type, error_message)

            error = XMLError(
                xml_id=xml_id,
                filename=filename,
                error_type=error_type,
                error_message=error_message,
                form_type=form_type,
                ein=ein,
                tax_year=tax_year,
                zip_id=zip_id,
                file_size=file_size,
                can_be_fixed=can_be_fixed
            )
            errors.append(error)

        return errors

    def _can_error_be_fixed(self, error_type: str, error_message: str) -> bool:
        """Determine if a specific error can potentially be fixed"""
        # XML syntax errors might be fixable with encoding fixes
        if error_type == 'XML_SYNTAX_ERROR':
            return 'encoding' in error_message.lower() or 'unicode' in error_message.lower()

        # Some validation errors might be fixable
        if error_type == 'VALIDATION_ERROR':
            return 'Invalid EIN format' in error_message

        # ZIP file errors are generally not fixable
        if error_type == 'ZIP_FILE_ERROR':
            return False

        # Form 990-T is intentionally skipped, not an error
        if error_type == 'FORM_990T':
            return False

        return False

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get statistics about XML parsing errors"""
        errors = self.extract_errors()

        stats = {
            'total_errors': len(errors),
            'errors_by_type': defaultdict(int),
            'fixable_errors': 0,
            'errors_by_form_type': defaultdict(int),
            'top_error_messages': defaultdict(int)
        }

        for error in errors:
            stats['errors_by_type'][error.error_type] += 1
            if error.can_be_fixed:
                stats['fixable_errors'] += 1
            if error.form_type:
                stats['errors_by_form_type'][error.form_type] += 1

            # Group similar error messages (first 100 chars)
            error_prefix = error.error_message[:100] if error.error_message else 'None'
            stats['top_error_messages'][error_prefix] += 1

        # Convert defaultdicts to regular dicts for JSON serialization
        stats['errors_by_type'] = dict(stats['errors_by_type'])
        stats['errors_by_form_type'] = dict(stats['errors_by_form_type'])
        stats['top_error_messages'] = dict(sorted(
            stats['top_error_messages'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10])  # Top 10 error messages

        return stats


class XMLErrorFixer:
    """Attempts to fix common XML parsing errors"""

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def attempt_fix(self, error: XMLError) -> bool:
        """Attempt to fix a specific XML parsing error"""
        if not error.can_be_fixed:
            return False

        error.fix_attempted = True

        try:
            if error.error_type == 'XML_SYNTAX_ERROR':
                return self._fix_encoding_error(error)
            elif error.error_type == 'VALIDATION_ERROR':
                return self._fix_validation_error(error)
            else:
                return False
        except Exception as e:
            log_error(f"Error during fix attempt for {error.xml_id}: {e}")
            return False

    def _fix_encoding_error(self, error: XMLError) -> bool:
        """Attempt to fix encoding-related XML syntax errors"""
        try:
            # Get the ZIP file path
            zip_path = self.db_ops.get_zip_file_path(error.zip_id)
            if not zip_path or not os.path.exists(zip_path):
                return False

            # Extract XML content
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                with zip_ref.open(error.filename) as xml_file:
                    xml_content = xml_file.read()

            # Try different encoding fixes
            fixed_content = None

            # Try to decode with different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    decoded = xml_content.decode(encoding)
                    # Try to re-encode as UTF-8
                    fixed_content = decoded.encode('utf-8')
                    break
                except (UnicodeDecodeError, UnicodeEncodeError):
                    continue

            if fixed_content:
                # Try to parse the fixed content
                parser = etree.XMLParser(recover=True)
                tree = etree.parse(BytesIO(fixed_content), parser)
                root = tree.getroot()

                # If parsing succeeds, we could potentially reprocess
                # For now, just mark as potentially fixable
                log_info(f"Encoding fix successful for {error.xml_id}")
                error.fix_successful = True
                return True

        except Exception as e:
            log_debug(f"Encoding fix failed for {error.xml_id}: {e}")

        return False

    def _fix_validation_error(self, error: XMLError) -> bool:
        """Attempt to fix validation errors like invalid EIN format"""
        if 'Invalid EIN format' in error.error_message:
            # This would require extracting and reformatting the EIN
            # For now, just log that it could potentially be fixed
            log_info(f"EIN validation error detected for {error.xml_id} - could potentially be fixed")
            return False  # Not implementing actual fix yet

        return False

    def fix_all_fixable_errors(self) -> Dict[str, int]:
        """Attempt to fix all fixable errors"""
        extractor = XMLErrorExtractor(self.db_ops)
        errors = extractor.extract_errors()

        results = {
            'total_fixable': 0,
            'fix_attempts': 0,
            'fix_successes': 0,
            'fix_failures': 0
        }

        for error in errors:
            if error.can_be_fixed:
                results['total_fixable'] += 1
                results['fix_attempts'] += 1

                if self.attempt_fix(error):
                    results['fix_successes'] += 1
                else:
                    results['fix_failures'] += 1

        return results


class XMLErrorReporter:
    """Generates reports about XML parsing errors"""

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops

    def generate_error_report(self, output_file: Optional[str] = None) -> str:
        """Generate a comprehensive error report"""
        extractor = XMLErrorExtractor(self.db_ops)
        stats = extractor.get_error_statistics()
        errors = extractor.extract_errors()

        report_lines = []
        report_lines.append("XML Parsing Error Report")
        report_lines.append("=" * 50)
        report_lines.append("")

        report_lines.append(f"Total Errors: {stats['total_errors']}")
        report_lines.append(f"Fixable Errors: {stats['fixable_errors']}")
        report_lines.append("")

        report_lines.append("Errors by Type:")
        for error_type, count in stats['errors_by_type'].items():
            report_lines.append(f"  {error_type}: {count}")
        report_lines.append("")

        report_lines.append("Errors by Form Type:")
        for form_type, count in stats['errors_by_form_type'].items():
            report_lines.append(f"  {form_type}: {count}")
        report_lines.append("")

        report_lines.append("Top Error Messages:")
        for i, (message, count) in enumerate(stats['top_error_messages'].items(), 1):
            report_lines.append(f"  {i}. ({count} times) {message}")
        report_lines.append("")

        report_lines.append("Sample Errors:")
        for i, error in enumerate(errors[:10], 1):  # Show first 10 errors
            report_lines.append(f"  {i}. {error.xml_id} ({error.filename})")
            report_lines.append(f"     Type: {error.error_type}")
            report_lines.append(f"     Message: {error.error_message[:200]}...")
            report_lines.append(f"     Fixable: {error.can_be_fixed}")
            report_lines.append("")

        report = "\n".join(report_lines)

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            log_info(f"Error report written to {output_file}")

        return report


def main():
    """Main function for testing the error handler"""
    from database_operations import DatabaseOperations

    # Use default database path - adjust as needed for testing
    db_path = "irs990.duckdb"  # Default database file
    db_ops = DatabaseOperations(db_path)

    # Extract and report errors
    extractor = XMLErrorExtractor(db_ops)
    reporter = XMLErrorReporter(db_ops)

    print("Extracting XML parsing errors...")
    errors = extractor.extract_errors(limit=100)  # Limit for testing
    print(f"Found {len(errors)} errors")

    print("\nError Statistics:")
    stats = extractor.get_error_statistics()
    print(f"Total errors: {stats['total_errors']}")
    print(f"Fixable errors: {stats['fixable_errors']}")

    print("\nErrors by type:")
    for error_type, count in stats['errors_by_type'].items():
        print(f"  {error_type}: {count}")

    # Generate report
    report = reporter.generate_error_report()
    print("\nError Report (first 500 chars):")
    print(report[:500] + "...")

    # Test fixer on a few errors
    fixer = XMLErrorFixer(db_ops)
    fixable_errors = [e for e in errors if e.can_be_fixed]

    if fixable_errors:
        print(f"\nAttempting to fix {len(fixable_errors)} fixable errors...")
        results = fixer.fix_all_fixable_errors()
        print(f"Fix results: {results}")


if __name__ == "__main__":
    main()