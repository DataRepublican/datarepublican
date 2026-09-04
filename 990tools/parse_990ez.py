#!/usr/bin/env python3

import sys
from lxml import etree  # type: ignore
from io import BytesIO
import re
from nameparser import HumanName
from parse_utils import parse_int_field, parse_string_field, clean_name, MONEY_PATTERN, parse_float_field, parse_name_fast
from xpaths_990ez import XPATHS_990EZ, NAMESPACES
from models import Charity, Officer, Grant, Contractor, PoliticalContribution, Address
from typing import Optional, List, Tuple, Callable, Dict, Any
from logging_utils import log_error, log_debug, log_info, log_warning, create_stub_log_error, create_stub_log_debug
from functools import partial
from config import global_config
from base_parser import BaseParser
from constants import DEBUG_EINS, ORG_TYPE_SUFFIXES, TRAVEL_KEYWORDS, CONFERENCE_KEYWORDS


class Parser990EZ(BaseParser):
    """Parser for IRS Form 990EZ"""

    def __init__(self):
        super().__init__("990EZ", XPATHS_990EZ, NAMESPACES)

    def parse_org_type(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse organization type for Form 990EZ"""
        from parse_utils import parse_string_field
        elem = parse_string_field(root, self.XPATHS, "org_type", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
        if elem is not None:
            ein = charity.ein if charity else 'Unknown'
            log_info("Found org_type element: tag={}, text={!r}, attrib={!r} for EIN {} in {}",
                        elem.tag, elem.text, elem.attrib, ein, xml_filename)
            if elem.tag.endswith("Organization501cInd"):
                type_num = elem.get("organization501cTypeTxt")
                if type_num and type_num.isdigit() and 1 <= int(type_num) <= 29:
                    org_type = f"501(c)({type_num})"
                elif elem.text and "X" in elem.text.upper():
                    org_type = "501(c)(3)"
                else:
                    org_type = "501(c)(3)"
            elif elem.tag.endswith(tuple(ORG_TYPE_SUFFIXES)):
                for suffix in ORG_TYPE_SUFFIXES:
                    if elem.tag.endswith(suffix):
                        type_num = suffix.replace("Organization501c", "").replace("Ind", "")
                        if type_num == "3":
                            org_type = "501(c)(3)"
                        elif type_num.isdigit() and 1 <= int(type_num) <= 29:
                            org_type = f"501(c)({type_num})"
                        else:
                            org_type = "501(c)(3)"
                            log_error(f"Unexpected suffix {suffix} for EIN {ein} in {xml_filename}, defaulting to 501(c)(3)")
                        break
            elif elem.tag.endswith("TaxExemptStatus") or elem.tag.endswith("ExemptStatusCd"):
                if elem.text and "501(c)" in elem.text:
                    match = re.search(r'501\(c\)\((\d+)\)', elem.text)
                    if match and 1 <= int(match.group(1)) <= 29:
                        org_type = f"501(c)({match.group(1)})"
                    else:
                        org_type = "501(c)(3)"
                        log_error("Invalid 501(c) format in TaxExemptStatus/ExemptStatusCd value {} for EIN {} in {}, defaulting to 501(c)(3)",
                                   elem.text, ein, xml_filename)
                elif elem.text and "4947(a)(1)" in elem.text:
                    org_type = "4947(a)(1)"
                else:
                    org_type = "501(c)(3)"  # Default for 990EZ
                    log_error(f"Unexpected TaxExemptStatus/ExemptStatusCd value {elem.text} for EIN {ein} in {xml_filename}, defaulting to 501(c)(3)")
            elif elem.tag.endswith("Organization4947a1NotPFInd") or elem.tag.endswith("Organization4947a1TrtdPFInd"):
                org_type = "4947(a)(1)"
            elif elem.tag.endswith("Organization501c3Ind"):
                org_type = "501(c)(3)"
            else:
                org_type = "501(c)(3)"  # Default for 990EZ
                # Only log error if verbose or debug mode
                if (ein in DEBUG_EINS) and not global_config.is_quiet():
                    log_error(f"Unexpected org_type tag {elem.tag} for EIN {ein} in {xml_filename}, defaulting to 501(c)(3)")
        else:
            ein = charity.ein if charity else 'Unknown'
            log_error("Failed to parse org_type for EIN {} in {}",
                        ein, xml_filename)
            return_data = parse_string_field(root, self.XPATHS, "return_data", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            all_tags = [child.tag for child in return_data.xpath("*", namespaces=namespaces)] if return_data is not None and return_data.xpath is not None else []
            log_error("No org_type tags found, defaulting to 501(c)(3). All ReturnData tags: {!r} in {}",
                       all_tags, xml_filename)
            org_type = "501(c)(3)"  # Default for 990EZ when no org_type tags are found
        ein = charity.ein if charity else 'Unknown'
        log_info("Parsed org_type {} for EIN {} in {}",
                    org_type, ein, xml_filename)
        return org_type

    def parse_grants_to_others(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse grants to others for Form 990EZ"""
        total = 0
        # Parse grants from Schedule I and F using the existing parse_schedule_i function
        from parse_schedule_i import parse_grants
        grants_data = parse_grants(root, xml_filename, charity.ein if charity else 'Unknown', charity.filer_name if charity else 'Unknown', charity.tax_year if charity else 'Unknown', set(), self.form_type, context=context)
        # parse_grants now adds grants directly to context, so we need to calculate total from the grants
        for grant in grants_data:
            total += grant.get('grant_amt', 0)

        ein = charity.ein if charity else 'Unknown'
        if total > 5_000_000 or ein in {"271414646", "520851555", "471203726", "464284638", "592965108", "486289145", "650869895"}:
            log_warning(f"Non-zero grants_to_others ${total} for EIN {ein}, Name {charity.filer_name if charity else 'Unknown'}, TaxYear {charity.tax_year if charity else 'Unknown'}, XML {xml_filename}")
        elif total == 0 and ein in {"271414646", "520851555", "471203726", "464284638", "592965108", "486289145", "650869895"}:
            return_data = parse_string_field(root, self.XPATHS, "return_data", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            child_tags = [child.tag for child in return_data.xpath("*", namespaces=namespaces)] if return_data is not None else []
            log_error("Zero grants_to_others for EIN {}, Name {}, File {}. ReturnData children: {!r}",
                        ein, charity.filer_name if charity else 'Unknown', xml_filename, child_tags)
        return total

    def parse_travel(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse travel expenses for Form 990EZ"""
        from parse_utils import parse_string_field
        total = 0
        # Cache the schedule_o elements to avoid repeated XPath evaluations
        if 'schedule_o_elements' not in xpath_cache:
            schedule_o_elements = []
            for xpath in self.XPATHS["schedule_o"]:
                result = xpath(root)
                schedule_o_elements.extend(result)
            xpath_cache['schedule_o_elements'] = schedule_o_elements
        else:
            schedule_o_elements = xpath_cache['schedule_o_elements']
    
        for elem in schedule_o_elements:
            desc = parse_string_field(elem, self.XPATHS, "schedule_o_value", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            if desc is not None:
                desc_text = (desc or "").upper()
                # Check for travel keywords anywhere in the description
                has_travel_keywords = any(keyword in desc_text for keyword in TRAVEL_KEYWORDS)
                if has_travel_keywords:
                    # Look for any money pattern in the description
                    match = MONEY_PATTERN.search(desc)
                    if match:
                        try:
                            amount = int(parse_float_field(match.group(1)))
                            total += amount
                            log_info("Parsed travel_amt ${} from Schedule O in {}",
                                       amount, xml_filename)
                        except IndexError:
                            # Skip logging travel parsing failures - handled downstream
                            pass
                    else:
                        # If no money pattern found but keywords present, try to extract any number
                        # Look for patterns like "AMOUNT: $1234" or just "$1234"
                        alt_match = re.search(r'(?:AMOUNT:\s*)?\$?([\d,]+\.?\d*)', desc, re.IGNORECASE)
                        if alt_match:
                            try:
                                amount = int(parse_float_field(alt_match.group(1)))
                                total += amount
                                log_info(f"Parsed travel_amt ${amount} (alt pattern) from Schedule O in {xml_filename}")
                            except (ValueError, IndexError):
                                # Skip logging travel parsing failures - handled downstream
                                pass
        return total

    def parse_conferences(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse conference expenses for Form 990EZ"""
        from parse_utils import parse_string_field
        total = 0
        # Cache the schedule_o elements to avoid repeated XPath evaluations
        if 'schedule_o_elements' not in xpath_cache:
            schedule_o_elements = []
            for xpath in self.XPATHS["schedule_o"]:
                result = xpath(root)
                schedule_o_elements.extend(result)
            xpath_cache['schedule_o_elements'] = schedule_o_elements
        else:
            schedule_o_elements = xpath_cache['schedule_o_elements']
    
        for elem in schedule_o_elements:
            desc = parse_string_field(elem, self.XPATHS, "schedule_o_value", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            if desc is not None:
                desc_text = (desc or "").upper()
                # Check for conference/meeting keywords anywhere in the description
                has_conference_keywords = any(keyword in desc_text for keyword in CONFERENCE_KEYWORDS)
                if has_conference_keywords:
                    # Look for any money pattern in the description
                    match = MONEY_PATTERN.search(desc)
                    if match:
                        try:
                            amount = int(parse_float_field(match.group(1)))
                            total += amount
                            log_info("Parsed conferences_amt ${} from Schedule O in {}",
                                       amount, xml_filename)
                        except IndexError:
                            # Skip logging conference parsing failures - handled downstream
                            pass
                    else:
                        # If no money pattern found but keywords present, try to extract any number
                        # Look for patterns like "AMOUNT: $1234" or just "$1234"
                        alt_match = re.search(r'(?:AMOUNT:\s*)?\$?([\d,]+\.?\d*)', desc, re.IGNORECASE)
                        if alt_match:
                            try:
                                amount = int(parse_float_field(alt_match.group(1)))
                                total += amount
                                log_info(f"Parsed conferences_amt ${amount} (alt pattern) from Schedule O in {xml_filename}")
                            except (ValueError, IndexError):
                                # Skip logging conference parsing failures - handled downstream
                                pass
        return total

    def get_field_parsers(self):
        """Get field parsers for Form 990EZ"""
        return [
            ("receipt", self.parse_receipt),
            ("contributions", self.parse_contributions),
            ("total_exp", self.parse_total_exp),
            ("prog_exp", self.parse_prog_exp),
            ("travel", self.parse_travel),
            ("conferences", self.parse_conferences),
            ("officer_comp", self.parse_officer_comp),
            ("grants_to_others", self.parse_grants_to_others),
            ("total_assets", self.parse_total_assets),
            ("org_type", self.parse_org_type),
            ("foreign_office", self.parse_foreign_office)
        ]

    def parse_form(self, root, xml_filename, xpath_cache, context, xpath_match_stats=None, cached_charity=None):
        """Parse Form 990EZ and add objects to context"""
        from pending_database_context import PendingDatabaseContext

        if not isinstance(context, PendingDatabaseContext):
            raise ValueError("context must be a PendingDatabaseContext instance")

        # Use cached charity if provided, otherwise get from context
        charity = cached_charity if cached_charity is not None else context.getCharity()
        if not charity or not charity.ein or charity.ein == "Unknown":
            raise ValueError(f"Invalid charity in context for Form 990EZ parsing in file {xml_filename}")

        super().parse_form(root, xml_filename, xpath_cache, context, xpath_match_stats=xpath_match_stats, cached_charity=charity)

    def set_form_specific_fields(self, data):
        """Set Form 990EZ specific fields"""
        data["foreign_expenses_ptile"] = None
        data["govt_grants"] = None
        data["grift_ratio"] = None
        data["foreign_office"] = False
        data["foreign_expenses_pct"] = None
        data["foreign_expenses"] = None
        data["domestic_misrep_flag"] = False
        return data

# Create parser instance
parser_990ez = Parser990EZ()

def parse_990ez(root, xml_filename, xpath_cache, context, xpath_match_stats=None):
    """Parse Form 990EZ - now uses context instead of returning tuples"""
    from pending_database_context import PendingDatabaseContext

    if not isinstance(context, PendingDatabaseContext):
        raise ValueError("context must be a PendingDatabaseContext instance")

    # Validate charity exists
    charity = context.getCharity()
    if not charity or not charity.ein or charity.ein == "Unknown":
        raise ValueError(f"Invalid charity in context for Form 990EZ parsing in file {xml_filename}")

    parser_990ez.parse_form(root, xml_filename, xpath_cache, context, xpath_match_stats=xpath_match_stats)


def main():
    if len(sys.argv) != 2:
        print("Usage: python parse_990ez.py <xml_file>", file=sys.stderr)
        sys.exit(1)

    xml_file = sys.argv[1]
    try:
        with open(xml_file, 'rb') as f:
            xml_content = f.read()
    except IOError as e:
        print("Error reading XML file {}: {}", xml_file, e, file=sys.stderr)
        sys.exit(1)

    parser = etree.XMLParser(recover=True)
    tree = etree.parse(BytesIO(xml_content), parser)
    root = tree.getroot()
    namespaces = {'irs': 'http://www.irs.gov/efile'}

    form_type_paths = [
        etree.XPath(".//irs:ReturnHeader/irs:ReturnTypeCd", namespaces=namespaces),
        etree.XPath(".//ReturnHeader/ReturnTypeCd")
    ]
    form_type = None
    for xpath in form_type_paths:
        result = xpath(root)
        if result:
            form_type = result[0].text
            break
    form_type = form_type if form_type is not None else "Unknown"

    tax_year_paths = [
        etree.XPath(".//irs:ReturnHeader/irs:TaxYr", namespaces=namespaces),
        etree.XPath(".//ReturnHeader/TaxYr")
    ]
    tax_year = None
    for xpath in tax_year_paths:
        result = xpath(root)
        if result:
            tax_year = result[0].text
            break
    tax_year = tax_year if tax_year is not None else "Unknown"
    if tax_year == "Unknown":
        tax_year = xml_file[:4] if xml_file[:4].isdigit() else "Unknown"
    else:
        try:
            tax_year = int(tax_year)
        except ValueError:
            tax_year = xml_file[:4] if xml_file[:4].isdigit() else "Unknown"

    filer_ein_paths = [
        etree.XPath(".//irs:ReturnHeader/irs:Filer/irs:EIN", namespaces=namespaces),
        etree.XPath(".//ReturnHeader/Filer/EIN")
    ]
    filer_ein = None
    for xpath in filer_ein_paths:
        result = xpath(root)
        if result:
            filer_ein = result[0].text.strip()
            break
    filer_ein = filer_ein if filer_ein is not None else "Unknown"

    # Create context and charity
    from pending_database_context import PendingDatabaseContext
    context = PendingDatabaseContext()
    charity = Charity(
        ein=filer_ein,
        tax_year=tax_year,
        form_type=form_type,
        xml_name=xml_file
    )
    context.addObjectToDatabase(charity)

    # Parse using context
    parse_990ez(root, xml_file, {}, context)

    # Print object counts
    print(context.getObjectCounts())

if __name__ == "__main__":
    main()