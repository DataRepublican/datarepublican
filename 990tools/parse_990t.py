#!/usr/bin/env python3
"""
parse_990t.py - Stub parser for IRS Form 990-T

This module provides a stub implementation for Form 990-T parsing.
Form 990-T is for Exempt Organization Business Income Tax, which we skip.
"""

from base_parser import BaseParser
from constants import CURRENT_PROCESSING_VERSION

class Parser990T(BaseParser):
    """Stub parser for IRS Form 990-T (Exempt Organization Business Income Tax)"""

    def __init__(self):
        super().__init__("990T", {}, {})  # No XPaths needed for stub

    def parse_org_type(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Stub implementation - not used"""
        return "Unknown"

    def parse_grants_to_others(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Stub implementation - not used"""
        return 0

    def parse_travel(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Stub implementation - not used"""
        return 0

    def parse_conferences(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Stub implementation - not used"""
        return 0

    def get_field_parsers(self):
        """Stub implementation - no field parsers needed"""
        return []

    def parse_related_entities(self, root, xml_filename, context, xpath_cache, charity=None, form_type=None, xpath_match_stats=None):
        """Stub implementation - no related entities to parse"""
        pass

    def set_form_specific_fields(self, data):
        """Stub implementation - no form-specific fields"""
        return data

    def parse_form(self, root, xml_filename, xpath_cache, context, xpath_match_stats=None, cached_charity=None):
        """Stub implementation - Form 990-T is skipped"""
        # Form 990-T is for Exempt Organization Business Income Tax
        # We don't process these forms, just skip them
        # Add generic update operation to update XmlFiles table
        from database_operations import DatabaseOperation, DatabaseOperationType
        operation = DatabaseOperation(
            DatabaseOperationType.GENERIC_UPDATE,
            {
                "table_name": "XmlFiles",
                "update_data": {
                    "xml_id": context.xml_id if hasattr(context, 'xml_id') else None,
                    "processed": True,
                    "processing_version": CURRENT_PROCESSING_VERSION,  # Will be overridden by consumer
                    "error_message": "skipped: 990t",
                    "form_type": "990T",
                    "ein": None,
                    "tax_year": None,
                    "file_size": 0  # Will be set by caller
                },
                "id_column": "xml_id"
            },
            context.xml_id if hasattr(context, 'xml_id') else None
        )
        context.addOperationToDatabase(operation)


# Create parser instance
parser_990t = Parser990T()


def parse_990t(root, xml_filename, xpath_cache, context, xpath_match_stats=None):
    """Parse Form 990-T - stub implementation that skips processing"""
    parser_990t.parse_form(root, xml_filename, xpath_cache, context, xpath_match_stats=xpath_match_stats)


def main():
    """Main function for testing - not implemented for stub"""
    print("Form 990-T parsing is not implemented (forms are skipped)")


if __name__ == "__main__":
    main()