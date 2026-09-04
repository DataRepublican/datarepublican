# extract_utils.py
import os
import glob
import logging
import zipfile
import csv
import re
import queue
from logging.handlers import QueueHandler, QueueListener
# etree import removed - use xpath_utils or xpaths.py for XPath operations
import subprocess
import signal
import sys
import pickle
import json
from lxml import etree  # type: ignore
import threading
from collections import defaultdict
import hashlib
from io import BytesIO
from typing import Tuple, Optional, List, Dict
from logging_utils import log_info, log_error, log_debug, log_warning, start_progress_reporting, stop_progress_reporting, update_progress
from models.address import Address


# XPath constants moved to xpaths.py - use from xpaths import COMMON_XPATHS, XPATHS_990, etc.
from xpaths import tostring
ZIP_REGEX = re.compile(r'^\d{5}$')
PO_BOX_REGEX = re.compile(r'P(?:\.?\s*O\.?\s*)?\bBOX\b\s*(\d+|[A-Z]\d*|[A-Z]+)', re.IGNORECASE)
PO_BOX_NUMBER_REGEX = re.compile(r'\b[-\w\d]+\b')
STOP_WORDS = {'AND', 'THE', 'OF', 'FOR', 'IN', 'TO', 'A', 'AN'}
USPS_FIXES = {
    'Saint': 'Street', 'St': 'Street', 'Ave': 'Avenue', 'Av': 'Avenue',
    'Blvd': 'Boulevard', 'Dr': 'Drive', 'Ln': 'Lane', 'Rd': 'Road',
    'Cir': 'Circle', 'Ct': 'Court', 'Pl': 'Place', 'Ter': 'Terrace',
    'Pkwy': 'Parkway', 'Hwy': 'Highway', 'Sq': 'Square'
}
VALID_STATES = {'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC', 'PR', 'VI', 'GU', 'AS', 'MP', 'FM', 'MH', 'PW', 'AA', 'AE', 'AP'}
ADDRESS_COLUMNS = ['filer_ein', 'filer_name', 'address_line1', 'address_line2', 'city', 'state', 'canonical_address', 'zip_code', 'zip4', 'po_box', 'colocator']
GRANT_COLUMNS = ['filer_ein', 'filer_name', 'recipient_ein', 'grantee_name', 'grant_amt', 'tax_year', 'filer_canonical_address', 'grantee_canonical_address']
DEBUG_ADDRESS_COLUMNS = ['filer_ein', 'filer_name', 'xml_filename', 'raw_components', 'canonical_address', 'raw_zip', 'zip_code', 'status', 'reason']
DEBUG_GRANT_COLUMNS = ['filer_ein', 'recipient_ein', 'filer_name', 'grantee_name', 'xml_filename', 'grant_address', 'grant_amt', 'tax_year', 'status', 'heuristic_score', 'reason']
INVALID_EIN_COLUMNS = ['tsv_ein', 'xml_ein', 'filer_name', 'xml_filename', 'reason']
PO_BOX_COLUMNS = ['po_box', 'zip_code', 'zip4', 'ein', 'org_name', 'colocator']
CSV_QUOTE_FIELDS = {
    'addresses': ['filer_name', 'canonical_address'],
    'grants': ['filer_name', 'recipient_ein'],
    'debug_address': ['filer_name', 'xml_filename', 'raw_components', 'canonical_address', 'reason'],
    'debug_grant': ['filer_name', 'xml_filename', 'grantee_name', 'recipient_ein', 'grant_address', 'reason'],
    'invalid_eins': ['tsv_ein', 'xml_ein', 'filer_name', 'xml_filename', 'reason'],
    'po_box_matches': ['org_name']
}
EIN_REGEX = re.compile(r'^\d{9}$')
BACKFILL_COLUMNS = ["recipient_ein", "name", "canonical_address", "po_box", "zip_code"]
VALID_EIN_PREFIXES = {
    '01', '02', '03', '04', '05', '06', '11', '13', '14', '16', '20', '21', '22', '23', '24', '25', '26', '27',
    '30', '31', '32', '33', '34', '35', '36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46', '47', '48', '49',
    '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69',
    '71', '72', '73', '74', '75', '76', '77', '78', '79', '80', '81', '82', '83', '84', '85', '86', '87', '88', '90', '91',
    '92', '93', '94', '95', '98'
}

logger = None
quiet = False
thread_local = threading.local()

def validate_ein(ein):
    """
    Validate an EIN or IRS file sequence number.

    Args:
        ein (str): The EIN or file sequence number to validate.

    Returns:
        tuple: (bool, str) where bool indicates validity and str provides the reason if invalid.
    """
    if not ein:
        return False, "EIN is empty"
    if not EIN_REGEX.match(ein):
        if ein.isdigit() and len(ein) > 9:
            # Assume it's a valid IRS file sequence number
            if not quiet:
                log_error(f"Accepting IRS file sequence number: {ein} (length: {len(ein)})")
            return True, ""
        return False, f"EIN {ein} is not a digit string"
    if ein == "000000000":
        return False, "EIN is all zeros"
    if ein[:2] not in VALID_EIN_PREFIXES:
        return False, f"EIN prefix {ein[:2]} is not a valid IRS prefix"
    return True, ""

def log_error(msg_format, *args, ein=None, exc_info=False):
    if logger and not quiet:
        try:
            if ein:
                log_info(logger, msg_format.format(*args) + f" (EIN: {ein})", exc_info=exc_info)
            else:
                log_info(logger, msg_format.format(*args), exc_info=exc_info)
        except Exception as e:
            log_info(logger, "Log formatting error: {}; args: {}", str(e), args)
    elif ein is not None:
        # If logger is not set up but ein is provided, this might be the issue
        print(f"Logger not set up but ein parameter provided: {ein}")

def setup_logging(output_dir, log_filename, verbose, quiet_global):
    global logger, quiet
    quiet = quiet_global
    log_queue = queue.Queue(-1)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(os.path.join(output_dir, log_filename))
    file_handler.setFormatter(formatter)
    listener = QueueListener(log_queue, file_handler)
    listener.start()
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.ERROR)
    console_handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers = [queue_handler, console_handler] if not quiet else []
    return listener

def compute_zip_checksums(zip_dir):
    checksums = {}
    print("Computing Zip File Checksums...")
    try:
        result = subprocess.run(['sha256sum'] + glob.glob(os.path.join(zip_dir, '*.zip')), capture_output=True, text=True)
        for line in result.stdout.splitlines():
            hash_val, path = line.split(None, 1)
            checksums[os.path.normpath(path)] = hash_val
    except (subprocess.CalledProcessError, FileNotFoundError):
        for zip_path in glob.glob(os.path.join(zip_dir, '*.zip')):
            with open(zip_path, 'rb') as f:
                sha256 = hashlib.sha256()
                while chunk := f.read(8192):
                    sha256.update(chunk)
                checksums[os.path.normpath(zip_path)] = sha256.hexdigest()
    return checksums

def build_zip_index(zip_dir, start_year, end_year):
    index = {}
    zip_files = []
    zip_names = set()
    for year in range(start_year, end_year + 2):
        zip_files.extend(glob.glob(os.path.join(zip_dir, f"{year}*.zip")))
    if not quiet:
        log_error(f"Found {len(zip_files)} ZIP files in {zip_dir}")
    if not zip_files:
        if not quiet:
            log_error(f"No ZIP files found in {zip_dir} for years {start_year}-{end_year + 1}")
        return index
    # Start thread-safe progress reporting
    progress_reporter = start_progress_reporting(
        total=len(zip_files),
        desc="Indexing ZIP files",
        unit="zip"
    )

    for zip_path in zip_files:
        zip_names.add(os.path.basename(zip_path))
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for internal_path in zf.namelist():
                    if internal_path.endswith('.xml'):
                        filename = os.path.basename(internal_path)
                        if filename in index:
                            if not quiet:
                                log_error(f"Duplicate XML filename {filename} in ZIP {index[filename][0]}, overwriting with {zip_path}")
                        index[filename] = (zip_path, internal_path)
        except Exception as e:
            if not quiet:
                log_error(f"Error indexing ZIP {zip_path}: {str(e)}", exc_info=True)
        update_progress(progress_reporter, 1)
    # Stop progress reporting
    stop_progress_reporting()

    if not quiet:
        log_error("Built ZIP index with {} XML files from {} ZIPs", len(index), len(zip_names))
    return index

def load_zip_cache(cache_dir, start_year, end_year, zip_dir, checksums):
    cache_valid = False
    cached_data = None
    checksum_file = os.path.join(cache_dir, f'zip_checksums_{start_year}_{end_year}.json')
    print("Loading ZIP index cache...")
    if os.path.exists(checksum_file):
        try:
            with open(checksum_file, 'r') as f:
                cached_checksums = json.load(f)
            if cached_checksums == checksums:
                zip_index_file = os.path.join(cache_dir, f'cached_zip_index_{start_year}_{end_year}.pkl')
                if os.path.exists(zip_index_file):
                    with open(zip_index_file, 'rb') as f:
                        cached_data = pickle.load(f)
                    cache_valid = True
        except Exception as e:
            if not quiet:
                log_error("Error loading ZIP index cache: {}", str(e), exc_info=True)
    return cache_valid, cached_data

def save_zip_cache(cache_dir, start_year, end_year, checksums, zip_index):
    try:
        print("Saving ZIP index cache...")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, f'zip_checksums_{start_year}_{end_year}.json'), 'w') as f:
            json.dump(checksums, f)
        with open(os.path.join(cache_dir, f'cached_zip_index_{start_year}_{end_year}.pkl'), 'wb') as f:
            pickle.dump(zip_index, f)
    except Exception as e:
        if not quiet:
            log_error("Error saving ZIP index cache: {}", str(e), exc_info=True)

def read_tsv_files(tsv_file, start_year, end_year, expected_columns=None):
    rows = []
    if not os.path.exists(tsv_file):
        if not quiet:
            log_error(f"TSV file {tsv_file} does not exist.")
        return rows
    try:
        with open(tsv_file, 'r', encoding='utf-8') as f:
            header = f.readline().strip().split('\t')
            header_map = {col: idx for idx, col in enumerate(header)}
            if expected_columns and not all(col in header_map for col in expected_columns):
                if not quiet:
                    log_error(f"Missing required columns in TSV {tsv_file}: {[col for col in expected_columns if col not in header_map]}")
                return rows
            for line in f:
                fields = line.strip().split('\t')
                if len(fields) < len(header_map):
                    continue
                row = {col: fields[idx] for col, idx in header_map.items()}
                if 'tax_year' in row:
                    try:
                        row_year = int(row['tax_year'])
                        if start_year <= row_year <= end_year:
                            rows.append(row)
                    except ValueError:
                        if not quiet:
                            log_error(f"Invalid tax_year {row.get('tax_year', '')} in TSV {tsv_file}, skipping row")
                else:
                    rows.append(row)
    except Exception as e:
        if not quiet:
            log_error(f"Error reading TSV {tsv_file}: {str(e)}", exc_info=True)
    if not quiet:
        log_error(f"Read {len(rows)} rows from {tsv_file}")
    return rows


def parse_filer_address(xml_content, xml_filename: str, row, zip_index, output_dir: str, sample_xml, parse_type: str = "filer", skip_address_errors: bool = False) -> Tuple[bool, Optional[str]]:
    global thread_local
    if not hasattr(thread_local, 'result'):
        thread_local.result = {
            'address_entries': [],
            'debug_address_entries': [],
            'po_box_entries': [],
            'invalid_ein_entries': [],
            'ein_mismatch_set': set(),
            'total_addresses': 0,
            'total_queue_puts': 0,
            'total_address_errors': 0,
            'zip_code_index': {},
            'po_box_zip_index': {},
            'filer_eins': {}
        }
    result = thread_local.result
    try:
        parser = etree.XMLParser(recover=True)  # type: ignore
        tree = etree.parse(BytesIO(xml_content), parser)  # type: ignore
        root = tree.getroot()  # type: ignore
        xml_ein = None
        from xpaths import COMMON_XPATHS
        for xpath in COMMON_XPATHS["filer_ein"]:
            elem = xpath(root)
            if elem and elem[0].text:
                xml_ein = elem[0].text.strip()
                break
        filer_name = None
        for xpath in COMMON_XPATHS["filer_name"]:
            elem = xpath(root)
            if elem and elem[0].text:
                filer_name = elem[0].text.strip()
                break
        if not xml_ein:
            if not quiet:
                log_error("Skipping XML %s: No EIN in XML", xml_filename)
            result['invalid_ein_entries'].append({
                'tsv_ein': '',
                'xml_ein': '',
                'filer_name': filer_name or 'Unknown',
                'xml_filename': xml_filename,
                'reason': 'No EIN in XML'
            })
            result['debug_address_entries'].append({
                'filer_ein': '',
                'filer_name': filer_name or 'Unknown',
                'xml_filename': xml_filename,
                'raw_components': '',
                'canonical_address': '',
                'raw_zip': '',
                'zip_code': '',
                'status': 'skipped',
                'reason': 'No EIN in XML'
            })
            return False, None
        # Check if it's a valid 9-digit EIN
        if EIN_REGEX.match(xml_ein):
            # Validate the EIN format
            valid, reason = validate_ein(xml_ein)
            if not valid:
                if not quiet:
                    log_error(f"Skipping XML {xml_filename}: Invalid EIN {xml_ein} ({reason})")
                result['invalid_ein_entries'].append({
                    'tsv_ein': '',
                    'xml_ein': xml_ein,
                    'filer_name': filer_name or 'Unknown',
                    'xml_filename': xml_filename,
                    'reason': reason
                })
                result['debug_address_entries'].append({
                    'filer_ein': xml_ein,
                    'filer_name': filer_name or 'Unknown',
                    'xml_filename': xml_filename,
                    'raw_components': '',
                    'canonical_address': '',
                    'raw_zip': '',
                    'zip_code': '',
                    'status': 'skipped',
                    'reason': f"Invalid EIN: {reason}"
                })
                return False, None
        else:
            # Not a 9-digit number - could be a file sequence number or other identifier
            # Log but don't skip - this might be acceptable for processing
            if not quiet:
                log_error(f"XML {xml_filename} has non-standard EIN format: {xml_ein} (length: {len(xml_ein)})")
        if not filer_name:
            filer_name = 'Unknown'
            if not quiet:
                result['debug_address_entries'].append({
                    'filer_ein': xml_ein,
                    'filer_name': filer_name,
                    'xml_filename': xml_filename,
                    'raw_components': '',
                    'canonical_address': '',
                    'raw_zip': '',
                    'zip_code': '',
                    'status': 'skipped',
                    'reason': 'No filer name in XML'
                })
            return False, None
        # Count USAddress elements to diagnose multiple addresses
        us_addresses = root.findall(".//irs:Filer/irs:USAddress", namespaces=NAMESPACES) or \
                      root.findall(".//Filer/USAddress", namespaces=NAMESPACES) or \
                      root.findall(".//USAddress", namespaces=NAMESPACES)
        if not quiet:
            log_error(f"parse_filer_address: Found {len(us_addresses)} USAddress elements in XML {xml_filename}")

        # Extract address components using XPaths from xpaths.py
        from xpaths import COMMON_XPATHS

        address_line1 = None
        for xpath in COMMON_XPATHS["filer_address_line1"]:
            try:
                result = xpath(root)  # type: ignore
                if result and result[0].text:
                    address_line1 = result[0].text.strip()
                    break
            except:
                continue

        address_line2 = None
        for xpath in COMMON_XPATHS["filer_address_line2"]:
            try:
                result = xpath(root)  # type: ignore
                if result and result[0].text:
                    address_line2 = result[0].text.strip()
                    break
            except:
                continue

        city = None
        for xpath in COMMON_XPATHS["filer_city"]:
            try:
                result = xpath(root)  # type: ignore
                if result and result[0].text:
                    city = result[0].text.strip()
                    break
            except:
                continue

        state = None
        for xpath in COMMON_XPATHS["filer_state"]:
            try:
                result = xpath(root)  # type: ignore
                if result and result[0].text:
                    state = result[0].text.strip()
                    break
            except:
                continue

        zip_code = None
        for xpath in COMMON_XPATHS["filer_zip_code"]:
            try:
                result = xpath(root)  # type: ignore
                if result and result[0].text:
                    zip_code = result[0].text.strip()
                    break
            except:
                continue

        address = Address(
            ein=xml_ein,
            name=filer_name,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            zip_code=zip_code
        )
        canonical_address = address.canonical_address
        address_line1 = address.address_line1
        address_line2 = address.address_line2
        city = address.city
        state = address.state
        po_box = address.po_box
        zip_code = address.zip_code
        zip4 = address.zip4
        colocator = address.colocator
        raw_components_str = ""
        us_address = root.find(".//irs:Filer/irs:USAddress", namespaces=NAMESPACES)  # type: ignore
        address_snippet = tostring(us_address if us_address is not None else root, encoding='unicode', method='xml', pretty_print=True)[:500]  # type: ignore
        if canonical_address:
            if not quiet:
                log_error(f"parse_filer_address: SUCCESS - Created address entry for EIN {xml_ein}: canonical='{canonical_address}', city='{city}', state='{state}', zip='{zip_code}', zip4='{zip4}', po_box='{po_box}', colocator='{colocator}'")
            result['address_entries'].append({
                'filer_ein': xml_ein,
                'filer_name': filer_name,
                'address_line1': address_line1,
                'address_line2': address_line2,
                'city': city,
                'state': state,
                'canonical_address': canonical_address,
                'zip_code': zip_code,
                'zip4': zip4,
                'po_box': po_box,
                'colocator': colocator
            })
            if po_box and zip_code and ZIP_REGEX.match(zip_code):
                result['po_box_entries'].append({
                    'po_box': po_box,
                    'zip_code': zip_code,
                    'zip4': zip4,
                    'ein': xml_ein,
                    'org_name': filer_name,
                    'colocator': colocator
                })
                po_box_key = (po_box, zip_code)
                if po_box_key not in result['po_box_zip_index']:
                    result['po_box_zip_index'][po_box_key] = set()
                result['po_box_zip_index'][po_box_key].add((xml_ein, filer_name))
            if zip_code and ZIP_REGEX.match(zip_code):
                if zip_code not in result['zip_code_index']:
                    result['zip_code_index'][zip_code] = set()
                result['zip_code_index'][zip_code].add((xml_ein, filer_name))
            result['total_addresses'] += 1
            result['total_queue_puts'] += 1
        else:
            if not quiet:
                log_error(f"parse_filer_address: ERROR - No canonical address for EIN {xml_ein}: components={len(address_components)}, raw_components='{raw_components_str}'")
            result['total_address_errors'] += 1
            result['debug_address_entries'].append({
                'filer_ein': xml_ein or '',
                'filer_name': filer_name or 'Unknown',
                'xml_filename': xml_filename,
                'raw_components': raw_components_str,
                'canonical_address': '',
                'raw_zip': '',
                'zip_code': '',
                'status': 'error',
                'reason': f"Invalid address; snippet={address_snippet}"
            })
            if sample_xml:
                os.makedirs(sample_xml, exist_ok=True)
                with open(os.path.join(sample_xml, xml_filename), 'wb') as f:
                    f.write(xml_content)
            if not skip_address_errors:
                return False, None
            with threading.Lock():
                result['filer_eins'][xml_filename] = (xml_ein, row, canonical_address)
        return True, xml_ein
    except Exception as e:
        if not quiet:
            log_error(f"Error parsing XML {xml_filename}: {str(e)}", exc_info=True)
        result['total_address_errors'] += 1
        result['debug_address_entries'].append({
            'filer_ein': xml_ein or '',
            'filer_name': filer_name or 'Unknown',
            'xml_filename': xml_filename,
            'raw_components': '',
            'canonical_address': '',
            'raw_zip': '',
            'zip_code': '',
            'status': 'error',
            'reason': str(e)
        })
        return False, None

def parse_recipient_address(grant_element, xml_filename: str, recipient_ein: str, recipient_name: str, output_dir: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    if not hasattr(thread_local, 'result'):
        thread_local.result = {
            'address_entries': [],
            'debug_address_entries': [],
            'po_box_entries': [],
            'total_addresses': 0,
            'total_address_errors': 0,
            'zip_code_index': {},
            'po_box_zip_index': {}
        }
    result = thread_local.result
    try:
        # Extract address components using XPaths from xpaths.py
        from xpaths import COMMON_XPATHS

        address_line1 = None
        for xpath in COMMON_XPATHS["recipient_address_line1"]:
            try:
                result = xpath(grant_element)  # type: ignore
                if result and result[0].text:
                    address_line1 = result[0].text.strip()
                    break
            except:
                continue

        address_line2 = None
        for xpath in COMMON_XPATHS["recipient_address_line2"]:
            try:
                result = xpath(grant_element)  # type: ignore
                if result and result[0].text:
                    address_line2 = result[0].text.strip()
                    break
            except:
                continue

        city = None
        for xpath in COMMON_XPATHS["recipient_city"]:
            try:
                result = xpath(grant_element)  # type: ignore
                if result and result[0].text:
                    city = result[0].text.strip()
                    break
            except:
                continue

        state = None
        for xpath in COMMON_XPATHS["recipient_state"]:
            try:
                result = xpath(grant_element)  # type: ignore
                if result and result[0].text:
                    state = result[0].text.strip()
                    break
            except:
                continue

        zip_code = None
        for xpath in COMMON_XPATHS["recipient_zip_code"]:
            try:
                result = xpath(grant_element)  # type: ignore
                if result and result[0].text:
                    zip_code = result[0].text.strip()
                    break
            except:
                continue

        address = Address(
            ein=recipient_ein or 'Unknown',
            name=recipient_name or 'Unknown',
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            zip_code=zip_code
        )
        address.prep_for_insert()
        canonical_address = address.canonical_address
        address_line1 = address.address_line1
        address_line2 = address.address_line2
        city = address.city
        state = address.state
        po_box = address.po_box
        zip_code = address.zip_code
        zip4 = address.zip4
        colocator = address.colocator
        raw_components_str = ""
        address_snippet = etree.tostring(grant_element, encoding='unicode', method='xml', pretty_print=True)[:500]  # type: ignore
        if not canonical_address:
            result['total_address_errors'] += 1
            result['debug_address_entries'].append({
                'filer_ein': recipient_ein or 'Unknown',
                'filer_name': recipient_name or 'Unknown',
                'xml_filename': xml_filename,
                'raw_components': raw_components_str,
                'canonical_address': '',
                'raw_zip': '',
                'zip_code': '',
                'status': 'error',
                'reason': f"Invalid recipient address; snippet={address_snippet}"
            })
            return "", None, None, None, None, None, None, None, None
        return canonical_address, address_line1, address_line2, city, state, po_box, zip_code, zip4, colocator
    except Exception as e:
        if not quiet:
            log_error(f"Error parsing recipient address in XML {xml_filename}: {str(e)}", exc_info=True)
        result['total_address_errors'] += 1
        result['debug_address_entries'].append({
            'filer_ein': recipient_ein or 'Unknown',
            'filer_name': recipient_name or 'Unknown',
            'xml_filename': xml_filename,
            'raw_components': '',
            'canonical_address': '',
            'raw_zip': '',
            'zip_code': '',
            'status': 'error',
            'reason': str(e)
        })
        return "", None, None
    
def write_tsv(file_path: str, entries, columns, quote_key, sort_keys=None) -> None:
    if sort_keys:
        entries = deduplicate_sorted_dicts(entries, sort_keys)
    if not quiet:
        log_error(f"Opening TSV file: {file_path}")
    with open(file_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow(columns)
        for entry in entries:
            writer.writerow([entry.get(col, '') for col in columns])
    if not quiet:
        log_error(f"Wrote {len(entries)} rows to {file_path}")

def deduplicate_sorted_dicts(entries, key_order) -> List[Dict]:
    seen = set()
    deduped = []
    for entry in entries:
        key_tuple = tuple(str(entry.get(key, '')) for key in key_order)
        if key_tuple not in seen:
            seen.add(key_tuple)
            deduped.append(entry)
    return sorted(deduped, key=lambda x: tuple(str(x.get(k, '')).lower() for k in key_order))

def load_address_cache(cache_dir: str, start_year: int, end_year: int, zip_dir: str) -> Tuple[bool, Optional[Tuple]]:
    cache_valid = False
    cached_data = None
    checksum_file = os.path.join(cache_dir, f'zip_checksums_{start_year}_{end_year}.json')
    print("Loading address cache...")
    if os.path.exists(checksum_file):
        try:
            with open(checksum_file, 'r') as f:
                cached_checksums = json.load(f)
            addresses_file = os.path.join(cache_dir, f'cached_addresses_{start_year}_{end_year}.pkl')
            mappings_file = os.path.join(cache_dir, f'cached_mappings_{start_year}_{end_year}.pkl')
            if all(os.path.exists(f) for f in [addresses_file, mappings_file]):
                with open(addresses_file, 'rb') as f:
                    address_entries, debug_address_entries = pickle.load(f)
                with open(mappings_file, 'rb') as f:
                    po_box_entries, zip_code_index, po_box_zip_index = pickle.load(f)
                cached_data = (address_entries, debug_address_entries, po_box_entries, zip_code_index, po_box_zip_index)
                cache_valid = True
        except Exception as e:
            if not quiet:
                log_error("Error loading address cache: {}", str(e), exc_info=True)
    return cache_valid, cached_data

def save_address_cache(cache_dir: str, start_year: int, end_year: int, address_entries, debug_address_entries, po_box_entries, zip_code_index, po_box_zip_index) -> None:
    try:
        print("Saving address cache...")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, f'cached_addresses_{start_year}_{end_year}.pkl'), 'wb') as f:
            pickle.dump((address_entries, debug_address_entries), f)
        with open(os.path.join(cache_dir, f'cached_mappings_{start_year}_{end_year}.pkl'), 'wb') as f:
            pickle.dump((po_box_entries, zip_code_index, po_box_zip_index), f)
    except Exception as e:
        if not quiet:
            log_error("Error saving address cache: {}", str(e), exc_info=True)

def normalize_file_path(arg_value, default_filename: str, base_dir=None) -> str:
    """Normalize a file path argument, appending default_filename to a directory or using the file path as-is."""
    if not arg_value:
        return os.path.join(base_dir or ".", default_filename)
    if os.path.isdir(arg_value):
        return os.path.join(arg_value, default_filename)
    return arg_value