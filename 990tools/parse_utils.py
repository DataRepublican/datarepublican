# parse_utils.py
import re
from lxml import etree  # type: ignore
from nameparser import HumanName
from io import BytesIO
import logging
from xpaths import NAMESPACES, GRANT_XPATHS, GRANT_EIN_XPATHS, GRANT_NAME_XPATHS, GRANT_AMOUNT_XPATHS, GRANT_FOREIGN_ADDRESS_XPATH, GRANT_COUNTRY_XPATH, GRANT_US_ADDRESS_XPATH, COMMON_XPATHS
from xpaths_990 import XPATHS_990
from xpaths_990ez import XPATHS_990EZ
from xpaths_990pf import XPATHS_990PF
from xpaths import SCHEDULE_C_XPATHS, SCHEDULE_C_AMOUNT_XPATHS, SCHEDULE_C_RECIPIENT_XPATHS, SCHEDULE_C_EIN_XPATHS, SCHEDULE_L_XPATHS
from xpath_utils import find_element
from constants import MONEY_PATTERN, FLOAT_PATTERN
from typing import Optional, List, Dict, Any
from models.address import Address
from models.political_contribution import PoliticalContribution
from logging_utils import log_error, log_debug

def parse_int_field(root, xpaths_dict, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats, verbose=False):
    elem = find_element(root, xpaths_dict[field], namespaces, xpath_cache=xpath_cache, field=field, form_type=context.getCharity().form_type if context.getCharity() else 'Unknown', log_error=log_error, xpath_match_stats=xpath_match_stats)
    if elem is not None:
        text = elem.text.strip() if elem.text else ""
        if text.upper() == "RESTRICTED":
            # Skip RESTRICTED values silently
            return 0
        try:
            value = int(text)
            if verbose:
                log_error(f"Parsed int field {field}: {value} for EIN {context.getCharity().ein if context.getCharity() else 'Unknown'} in {xml_filename}")
            return value
        except (ValueError, AttributeError):
            log_error(f"Invalid int value for field {field}: {text} in {xml_filename}")
    return 0

def parse_string_field(root, xpaths_dict, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats, verbose=False, default=None, return_element=False):
    elem = find_element(root, xpaths_dict[field], namespaces, xpath_cache=xpath_cache, field=field, form_type=context.getCharity().form_type if context.getCharity() else 'Unknown', log_error=log_error, xpath_match_stats=xpath_match_stats)
    if elem is not None:
        value = elem.text.strip() if elem.text else default
        if verbose:
            log_error(f"Parsed string field {field}: {value} for EIN {context.getCharity().ein if context.getCharity() else 'Unknown'} in {xml_filename}")
        return elem if return_element else value
    return default


def clean_name(name):
    return re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().upper()

# Precompiled regex patterns for fast name parsing
CLEAN_NAME_PATTERN = re.compile(r'[^a-zA-Z0-9\s]')
SPLIT_NAME_PATTERN = re.compile(r'\s+')

def parse_name_fast(name):
    """
    Fast name parsing with fallback to HumanName for complex names.
    Handles most IRS officer names (simple "First Last" format) with regex,
    falls back to HumanName for complex names (>2 parts).
    Strips trailing "N A" or "NA" suffixes from organizational names.
    """
    if not name:
        return 'Unknown', 'Unknown'

    cleaned = CLEAN_NAME_PATTERN.sub('', name).strip().upper()

    # Check if the name represents "Not Applicable" (NA, N/A, N.A., etc.)
    letters_only = re.sub(r'[^a-zA-Z]', '', cleaned)
    if letters_only == 'NA':
        return 'Not', 'Applicable'

    # Strip trailing "N A" or "NA" suffixes (e.g., "Bank of America N A" -> "Bank of America")
    cleaned = re.sub(r'\s+(?:N\s+A|NA)\s*$', '', cleaned)

    parts = SPLIT_NAME_PATTERN.split(cleaned)

    if len(parts) <= 2:
        # Fast path: simple names
        first = parts[0] if parts else 'Unknown'
        last = parts[-1] if len(parts) > 1 else 'Unknown'
        return first, last
    else:
        # For names with >2 parts after stripping suffixes, use HumanName for accuracy
        # This handles complex names like "Dr. Jane Doe Jr." or organizational names
        hn = HumanName(cleaned)
        first = hn.first or 'Unknown'
        last = hn.last or 'Unknown'
        return first, last

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

def split_zip_code(zip_code_str):
    """
    Split a ZIP code string into 5-digit zip_code and 4-digit zip4 components.

    Args:
        zip_code_str: String containing ZIP code (can be 5 or 9 digits)

    Returns:
        tuple: (zip_code, zip4) where zip_code is first 5 digits, zip4 is last 4 digits
               Both can be None if input is invalid
    """
    if not zip_code_str:
        return None, None

    # Remove any non-digit characters
    cleaned = re.sub(r'\D', '', str(zip_code_str))

    if len(cleaned) == 5:
        # Standard 5-digit ZIP
        return cleaned, None
    elif len(cleaned) == 9:
        # 9-digit ZIP code
        return cleaned[:5], cleaned[5:]
    elif len(cleaned) == 10 and cleaned[5] == '0':
        # Sometimes formatted as XXXXX-XXXX, handle the dash
        return cleaned[:5], cleaned[6:] if len(cleaned) > 6 else None
    else:
        # Invalid format, return as-is for zip_code (first 5 digits if possible)
        if len(cleaned) >= 5:
            return cleaned[:5], cleaned[5:9] if len(cleaned) >= 9 else None
        else:
            return cleaned, None


def validate_ein(ein):
    if not ein or not re.match(r'^\d{9}$', ein) or ein == "000000000":
        return False, "Invalid EIN format"
    prefix = ein[:2]
    valid_prefixes = {'01', '02', '03', '04', '05', '06', '11', '13', '14', '16', '20', '21', '22', '23', '24', '25', '26', '27',
                      '30', '31', '32', '33', '34', '35', '36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46', '47', '48', '49',
                      '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69',
                      '71', '72', '73', '74', '75', '76', '77', '78', '79', '80', '81', '82', '83', '84', '85', '86', '87', '88', '90', '91',
                      '92', '93', '94', '95', '98'}
    if prefix not in valid_prefixes:
        return False, f"Invalid EIN prefix {prefix}"
    return True, ""


def extract_address(root, filename: str, filer_ein: str, quiet: bool = False, logger=None) -> Optional[Address]:
    """Extract address from XML - moved from xml_processor.py"""
    from models.address import Address
    from logging_utils import log_debug, log_info

    if not quiet and logger is not None and log_debug is not None:
        log_debug(logger, f"DEBUG: Starting address extraction for EIN {filer_ein} in {filename}")

    # Extract filer name for address
    name_xpaths = COMMON_XPATHS["filer_name_xpaths"]

    filer_name = "Unknown"
    for xpath in name_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                filer_name = result[0].text.strip()
                if not quiet and logger is not None and log_debug is not None:
                    log_debug(logger, f"DEBUG: Found filer name: '{filer_name}' for EIN {filer_ein}")
                break
        except:
            continue

    # Create Address object with basic fields and call prep_for_insert
    address = Address(
        ein=filer_ein,
        name=filer_name,
        address_type="filer"
    )

    # Extract address components directly from XML using proper XPaths
    # Get individual address fields from ReturnHeader/Filer
    address_line1_xpaths = COMMON_XPATHS["filer_address_line1"]

    for xpath in address_line1_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                address.address_line1 = result[0].text.strip()
                if not quiet and logger is not None and log_debug is not None:
                    log_debug(logger, f"DEBUG: Found address_line1: '{address.address_line1}' for EIN {filer_ein} using xpath {xpath.path}")
                break
        except:
            continue

    # Debug: if no address_line1 found, log the XML structure around address
    if not address.address_line1 and not quiet:
        # Try to find any USAddress elements and log their structure
        try:
            us_addresses = root.xpath(".//USAddress", namespaces={})
            if us_addresses and logger is not None and log_debug is not None:
                log_debug(logger, f"DEBUG: Found {len(us_addresses)} USAddress elements for EIN {filer_ein}")
                for i, addr_elem in enumerate(us_addresses[:1]):  # Just log first one
                    log_debug(logger, f"DEBUG: USAddress {i} content: {etree.tostring(addr_elem, encoding='unicode')[:500]}...")
            elif logger is not None and log_debug is not None:
                log_debug(logger, f"DEBUG: No USAddress elements found for EIN {filer_ein}")
        except Exception as e:
            if logger is not None and log_debug is not None:
                log_debug(logger, f"DEBUG: Error checking USAddress structure for EIN {filer_ein}: {str(e)}")

    # Address line 2
    address_line2_xpaths = COMMON_XPATHS["filer_address_line2"]

    for xpath in address_line2_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                address.address_line2 = result[0].text.strip()
                break
        except:
            continue

    # City
    city_xpaths = COMMON_XPATHS["filer_city"]

    for xpath in city_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                address.city = result[0].text.strip()
                break
        except:
            continue

    # State
    state_xpaths = COMMON_XPATHS["filer_state"]

    for xpath in state_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                address.state = result[0].text.strip()
                break
        except:
            continue

    # ZIP Code
    zip_xpaths = COMMON_XPATHS["filer_zip_code"]

    for xpath in zip_xpaths:
        try:
            result = xpath(root)
            if result and result[0].text:
                address.zip_code = result[0].text.strip()
                break
        except:
            continue

    if not quiet and logger is not None and log_debug is not None:
        log_debug(logger, f"DEBUG: About to call prep_for_insert for EIN {filer_ein}, address_line1='{address.address_line1}', city='{address.city}', state='{address.state}', zip='{address.zip_code}'")

    address.prep_for_insert()

    if not quiet and logger is not None and log_debug is not None:
        log_debug(logger, f"DEBUG: After prep_for_insert for EIN {filer_ein}: canonical_address='{address.canonical_address}', po_box='{address.po_box}', colocator='{address.colocator}'")

    if address.canonical_address:
        if not quiet and logger is not None and log_info is not None:
            log_info(logger, f"DEBUG: Created Address object - canonical_address='{address.canonical_address}', po_box='{address.po_box}', colocator='{address.colocator}'")
        return address
    else:
        if not quiet and logger is not None and log_info is not None:
            log_info(logger, f"DEBUG: No canonical_address created - canonical_address='{address.canonical_address}', po_box='{address.po_box}', colocator='{address.colocator}'")
        return None

