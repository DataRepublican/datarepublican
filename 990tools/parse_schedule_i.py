#!/usr/bin/env python3
"""
parse_schedule_i.py - Parse Schedule I (Grants) from IRS 990 forms

This module handles parsing of Schedule I (Grants to Organizations or Individuals in the United States)
from IRS Form 990, 990EZ, and 990PF.
"""

import re
from lxml import etree  # type: ignore
from io import BytesIO
import logging
from xpaths import NAMESPACES, GRANT_XPATHS, GRANT_EIN_XPATHS, GRANT_NAME_XPATHS, GRANT_AMOUNT_XPATHS, GRANT_FOREIGN_ADDRESS_XPATH, GRANT_COUNTRY_XPATH, GRANT_US_ADDRESS_XPATH
try:
    from xpaths_990 import XPATHS_990
    from xpaths_990ez import XPATHS_990EZ
    from xpaths_990pf import XPATHS_990PF
except ImportError:
    from xpaths_990 import XPATHS_990
    from xpaths_990ez import XPATHS_990EZ
    from xpaths_990pf import XPATHS_990PF
from xpath_utils import find_element
from constants import MONEY_PATTERN, FLOAT_PATTERN
from typing import Optional, List, Dict, Any
from models.address import Address
from models.grant import Grant


def parse_grants(root, xml_filename: str, filer_ein: str, filer_name: str, tax_year: int, known_eins, form_type: str, backfill_entries=None, seen_backfill_keys=None, log_error=None, context=None) -> List[Dict[str, Any]]:
    grants = []
    try:
        # Get form-specific XPath configurations
        form_xpaths = {
            "990": XPATHS_990,
            "990EZ": XPATHS_990EZ,
            "990PF": XPATHS_990PF,
        }.get(form_type, {})

        # Use form-specific batch XPaths if available, otherwise fall back to global ones
        grant_ein_xpaths = form_xpaths.get("grant_ein_xpaths", GRANT_EIN_XPATHS)
        grant_name_xpaths = form_xpaths.get("grant_name_xpaths", GRANT_NAME_XPATHS)
        grant_amount_xpaths = form_xpaths.get("grant_amount_xpaths", GRANT_AMOUNT_XPATHS)

        grant_xpaths = GRANT_XPATHS.get(form_type, [])
        for xpath in grant_xpaths:
            elements = xpath(root)
            for elem in elements:
                try:
                    # Try all EIN xpaths - use find_element for better performance
                    ein_elem = None
                    for ein_xpath in grant_ein_xpaths:
                        ein_elem = find_element(elem, [ein_xpath], NAMESPACES)
                        if ein_elem is not None:
                            break

                    # Try all name xpaths - use find_element for better performance
                    name_elem = None
                    for name_xpath in grant_name_xpaths:
                        name_elem = find_element(elem, [name_xpath], NAMESPACES)
                        if name_elem is not None:
                            break

                    # Try all amount xpaths - use find_element for better performance
                    amount_elem = None
                    for amt_xpath in grant_amount_xpaths:
                        amount_elem = find_element(elem, [amt_xpath], NAMESPACES)
                        if amount_elem is not None:
                            break

                    grantee_name = (name_elem[0].text.strip() if name_elem and name_elem[0].text else "Unknown")
                    recipient_ein = ein_elem[0].text.strip() if ein_elem else "Unknown"

                    grant_amt = 0
                    if amount_elem and amount_elem[0].text:
                        try:
                            amt_text = amount_elem[0].text.strip()
                            if amt_text:  # Only parse if not empty
                                grant_amt = int(parse_float_field(amt_text))
                        except (ValueError, TypeError):
                            pass

                    grant_data = {
                        'filer_ein': filer_ein,
                        'filer_name': filer_name,
                        'grantee_name': grantee_name,
                        'recipient_ein': recipient_ein,
                        'grant_amt': grant_amt,
                        'tax_year': tax_year
                    }
                    grants.append(grant_data)

                    # If context is provided, also add to context
                    if context is not None:
                        grant_obj = Grant(**grant_data)
                        context.addObjectToDatabase(grant_obj)
                except Exception as e:
                    continue
    except Exception as e:
        logging.error(f"Error parsing grants from {xml_filename}: {e}")
    return grants

def parse_float_field(text):
    """Parse a float from text, handling commas, dollar signs, and other formatting"""
    if not text:
        return 0.0

    # Remove commas and dollar signs first
    cleaned = str(text).replace(',', '').replace('$', '').strip()

    # Use regex to find the first valid number pattern
    match = FLOAT_PATTERN.search(cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass

    return 0.0