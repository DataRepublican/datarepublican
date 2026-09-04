#!/usr/bin/env python3
"""
fix_po_box_addresses.py - Update po_box field for existing addresses with PO Box patterns

This script identifies addresses that contain PO Box patterns in address_line1 or address_line2
but have NULL po_box field, and updates them so they can be properly excluded from geocoding.
"""

import logging
import re
from database_operations import DatabaseOperations
from models import Address
from logging_utils import get_logger, log_info, log_error as proper_log_error, log_debug as proper_log_debug, log_error, log_debug, log_warning

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# PO Box regex (same as in models/address.py)
PO_BOX_REGEX = re.compile(r'P(?:.*?\bBOX\b\s+)([-\w\d]+)', re.IGNORECASE)

def fix_po_box_addresses(db_path: str = 'irs990.duckdb'):
    """Update po_box field for addresses with PO Box patterns but NULL po_box"""

    db_ops = DatabaseOperations(db_path)

    # Find addresses with NULL po_box but PO Box patterns in address lines
    if not quiet:
        logger.info("Finding addresses with PO Box patterns but NULL po_box field...")

    # Query for addresses that need updating
    result = db_ops.execute_query("""
        SELECT address_id, address_line1, address_line2, city, state, zip_code, po_box
        FROM Addresses
        WHERE po_box IS NULL OR po_box = ''
    """)

    addresses_to_update = []
    for row in result.fetchall():
        address_id, line1, line2, city, state, zip_code, po_box = row

        # Check both address lines for PO Box pattern
        po_box_found = None
        for line in [line1, line2]:
            if line:
                match = PO_BOX_REGEX.search(line)
                if match:
                    po_box_found = match.group(1)
                    break

        if po_box_found:
            addresses_to_update.append((address_id, po_box_found, line1, line2, city, state, zip_code))
            if not quiet:
                logger.info(f"Found address {address_id} with PO Box '{po_box_found}' in lines: '{line1}' / '{line2}'")

    if not quiet:
        logger.info(f"Found {len(addresses_to_update)} addresses to update")

    if not addresses_to_update:
        if not quiet:
            logger.info("No addresses need updating")
        return 0

    # Update addresses in batches
    batch_size = 1000
    updated_count = 0

    for i in range(0, len(addresses_to_update), batch_size):
        batch = addresses_to_update[i:i+batch_size]
        if not quiet:
            logger.info(f"Processing batch {i//batch_size + 1} with {len(batch)} addresses")

        for address_id, po_box_number, line1, line2, city, state, zip_code in batch:
            # Create Address object to properly set colocator
            address = Address(
                address_id=address_id,
                address_line1=line1,
                address_line2=line2,
                city=city,
                state=state,
                zip_code=zip_code,
                po_box=po_box_number  # This will trigger colocator calculation
            )

            # Update the database
            db_ops.update_address_po_box_and_colocator(address_id, po_box_number, address.colocator)
            updated_count += 1

            if updated_count % 100 == 0:
                if not quiet:
                    logger.info(f"Updated {updated_count} addresses so far")

    if not quiet:
        logger.info(f"Successfully updated {updated_count} addresses with PO Box information")
    return updated_count

if __name__ == '__main__':
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'irs990.duckdb'
    if not quiet:
        logger.info(f"Starting PO Box address fix for database: {db_path}")

    try:
        updated = fix_po_box_addresses(db_path)
        if not quiet:
            logger.info(f"Fix completed. Updated {updated} addresses.")
    except Exception as e:
        if not quiet:
            logger.error(f"Fix failed: {e}", exc_info=True)
        sys.exit(1)