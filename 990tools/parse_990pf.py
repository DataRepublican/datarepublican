#!/usr/bin/env python3
import sys

from lxml import etree  # type: ignore
from io import BytesIO
from parse_utils import parse_int_field, parse_string_field, clean_name, MONEY_PATTERN, parse_float_field, parse_name_fast, split_zip_code
from xpaths_990pf import XPATHS_990PF, NAMESPACES
from models import Charity, Officer, Grant, Contractor, PoliticalContribution, Address
from typing import Optional, List, Tuple, Dict, Any, Callable
from logging_utils import log_error, log_debug, log_info, log_warning, create_stub_log_error, create_stub_log_debug
from config import global_config
from base_parser import BaseParser
from constants import DEBUG_EINS, ORG_TYPE_SUFFIXES


class Parser990PF(BaseParser):
    """Parser for IRS Form 990PF"""

    def __init__(self):
        super().__init__("990PF", XPATHS_990PF, NAMESPACES)

    def get_field_parsers(self):
        """Get field parsers for Form 990PF"""
        return [
            ("receipt", self.parse_receipt),
            ("total_exp", self.parse_total_exp),
            ("prog_exp", self.parse_prog_exp),
            ("officer_comp", self.parse_officer_comp),
            ("grants_to_others", self.parse_grants_to_others),
            ("total_assets", self.parse_total_assets),
            ("travel", self.parse_travel),
            ("conferences", self.parse_conferences),
            ("org_type", self.parse_org_type),
            ("foreign_office", self.parse_foreign_office)
        ]

    def set_form_specific_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Set form-specific fields for 990PF"""
        # PF forms don't have govt_grants or contributions
        data["govt_grants"] = None
        data["contributions"] = None
        data["foreign_expenses"] = None
        data["foreign_expenses_pct"] = None
        data["foreign_expenses_ptile"] = None
        data["foreign_office"] = False
        data["domestic_misrep_flag"] = False
        return data

    def parse_travel(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse travel expenses - 990PF doesn't have TravelGrp"""
        return 0

    def parse_officer_comp(
        self,
        root: etree._Element,
        field: str,
        namespaces: Dict[str, str],
        xml_filename: str,
        context: 'PendingDatabaseContext',
        xpath_cache: Dict[str, Any],
        form_type: str,
        xpath_match_stats: Optional[Dict[str, int]] = None,
        charity: Optional['Charity'] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Parse officer compensation - 990PF uses OfficerDirTrstKeyEmplInfoGrp"""
        total: int = 0
        officer_entries: List[Dict[str, Any]] = []

        xpaths_for_form = self.get_xpaths_for_form(form_type)

        # Check if this form type has officer compensation elements
        if not xpaths_for_form.get("officer_comp_elements"):
            return total, officer_entries  # No officer compensation for this form type

        # Use XPath union for better performance - get all officer elements at once
        from xpaths import ORG_TYPE_UNION_XPATH
        officer_xpath = etree.XPath(f".//irs:IRS{form_type}/irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp | .//irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp | .//OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp", namespaces=namespaces)
        elements: List[etree._Element] = officer_xpath(root)

        # Use provided charity or get from context
        charity = charity or context.getCharity()
        if not charity:
            return total, officer_entries

        for elem in elements:
            # Direct element access instead of parse_string_field for better performance
            name_elem = elem.find("irs:PersonNm", namespaces)
            if name_elem is None:
                name_elem = elem.find("PersonNm")
            comp_elem = elem.find("irs:CompensationAmt", namespaces)
            if comp_elem is None:
                comp_elem = elem.find("CompensationAmt")

            if name_elem is not None and comp_elem is not None:
                name_text = name_elem.text.strip()
                try:
                    comp_value = int(float(comp_elem.text.strip().replace(',', '')))
                    if comp_value > 0:
                        cleaned_name = clean_name(name_text)
                        first_name, last_name = parse_name_fast(cleaned_name)

                        officer_entries.append({
                            "first_name": first_name,
                            "last_name": last_name,
                            "full_name": name_text,  # Store original name for photo lookup
                            "amount": comp_value,
                            "ein": charity.ein,
                            "charity_name": charity.filer_name or 'Unknown',
                            "tax_year": charity.tax_year,
                            "element": elem  # Store element for address parsing
                        })
                        total += comp_value

                        if not global_config.is_quiet():
                            log_info("Parsed officer {0} {1} compensation: ${2} for EIN {3} in {4}",
                                      first_name, last_name, comp_value, charity.ein, xml_filename)
                except (ValueError, AttributeError):
                    continue

        return total, officer_entries

    def _parse_officer_address(self, officer_elem: etree._Element, charity: Charity, xml_filename: str, context: 'PendingDatabaseContext') -> None:
        """Parse address information from 990PF officer element and add to context"""
        # For 990PF, officers are not stored as separate objects, so we just create the address directly
        try:
            # For 990PF, the address is directly within the OfficerDirTrstKeyEmplGrp element
            # Look for USAddress element
            address_elem = officer_elem.find("irs:USAddress", namespaces={'irs': 'http://www.irs.gov/efile'})
            if address_elem is None:
                address_elem = officer_elem.find("USAddress")

            if address_elem is not None:
                # Extract address components
                address_line1_elem = address_elem.find("irs:AddressLine1Txt", namespaces={'irs': 'http://www.irs.gov/efile'})
                if address_line1_elem is None:
                    address_line1_elem = address_elem.find("AddressLine1Txt")

                city_elem = address_elem.find("irs:CityNm", namespaces={'irs': 'http://www.irs.gov/efile'})
                if city_elem is None:
                    city_elem = address_elem.find("CityNm")

                state_elem = address_elem.find("irs:StateAbbreviationCd", namespaces={'irs': 'http://www.irs.gov/efile'})
                if state_elem is None:
                    state_elem = address_elem.find("StateAbbreviationCd")

                zip_elem = address_elem.find("irs:ZIPCd", namespaces={'irs': 'http://www.irs.gov/efile'})
                if zip_elem is None:
                    zip_elem = address_elem.find("ZIPCd")

                # Extract values
                address_line1 = address_line1_elem.text.strip() if address_line1_elem is not None and address_line1_elem.text else None
                city = city_elem.text.strip() if city_elem is not None and city_elem.text else None
                state = state_elem.text.strip() if state_elem is not None and state_elem.text else None
                zip_code_raw = zip_elem.text.strip() if zip_elem is not None and zip_elem.text else None

                # Split ZIP code
                zip_code, zip4 = split_zip_code(zip_code_raw or '')

                # Check if we have at least some address components
                if any([address_line1, city, state, zip_code]):
                    # Create address directly using Address.create_for_charity pattern
                    from models import Address
                    address = Address(
                        ein="",  # Officers don't have EINs
                        name="BANK OF AMERICA N A",  # From the XML we saw
                        address_line1=address_line1,
                        address_line2=None,
                        city=city,
                        state=state,
                        zip_code=zip_code,
                        zip4=zip4,
                        address_type="officer",
                        owner_id=charity.id  # Link to charity
                    )
                    address.prep_for_insert()  # This will canonicalize and set colocator
                    context.addObjectToDatabase(address)
        except Exception as e:
            log_debug("Failed to parse 990PF officer address in {0}: {1}", xml_filename, str(e))
    def parse_grants_to_others(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        """Parse grants to others for Form 990PF"""
        total = 0
        # Parse grants from Supplementary Information
        grant_elements = []
        for xpath in XPATHS_990PF["grant_elements"]:
            result = xpath(root)
            grant_elements.extend(result)

        for entry in grant_elements:
            # Parse grant amount
            amt_elem = entry.find("irs:Amt", namespaces=NAMESPACES)
            grant_amount = 0
            if amt_elem is not None and amt_elem.text:
                try:
                    grant_amount = int(float((amt_elem.text or "").replace(',', '')))
                except (ValueError, AttributeError):
                    pass

            # Parse recipient information
            recipient_name_elem = entry.find("irs:RecipientBusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES)
            recipient_name = ""
            if recipient_name_elem is not None and recipient_name_elem.text:
                recipient_name = recipient_name_elem.text.strip()

            # Parse recipient EIN if available
            recipient_ein_elem = entry.find("irs:RecipientEIN", namespaces=NAMESPACES)
            recipient_ein = ""
            if recipient_ein_elem is not None and recipient_ein_elem.text:
                recipient_ein = recipient_ein_elem.text.strip()

            # Parse recipient address
            address_line1_elem = entry.find("irs:RecipientUSAddress/irs:AddressLine1Txt", namespaces=NAMESPACES)
            address_line1 = ""
            if address_line1_elem is not None and address_line1_elem.text:
                address_line1 = address_line1_elem.text.strip()

            city_elem = entry.find("irs:RecipientUSAddress/irs:CityNm", namespaces=NAMESPACES)
            city = ""
            if city_elem is not None and city_elem.text:
                city = city_elem.text.strip()

            state_elem = entry.find("irs:RecipientUSAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES)
            state = ""
            if state_elem is not None and state_elem.text:
                state = state_elem.text.strip()

            zip_elem = entry.find("irs:RecipientUSAddress/irs:ZIPCd", namespaces=NAMESPACES)
            zip_code = ""
            if zip_elem is not None and zip_elem.text:
                zip_code = zip_elem.text.strip()

            if grant_amount > 0 and recipient_name:
                # Create Grant object
                grant = Grant(
                    filer_ein=charity.ein if charity else "",
                    filer_name=charity.filer_name if charity else "",
                    grantee_name=recipient_name,
                    recipient_ein=recipient_ein if recipient_ein else None,
                    grant_amt=grant_amount,
                    tax_year=charity.tax_year if charity else 0
                )
                grant.prep_for_insert()
                context.addObjectToDatabase(grant)

                # Create address for grant recipient if no EIN (common in 990PF)
                if not recipient_ein and (address_line1 or city or state or zip_code):
                    address = grant.build_address(
                        address_line1=address_line1,
                        city=city,
                        state=state,
                        zip_code=zip_code
                    )
                    context.addObjectToDatabase(address)

                total += grant_amount

        debug_eins = {"271414646", "520851555", "471203726", "464284638", "592965108", "486289145", "650869895"}
        ein = charity.ein if charity else 'Unknown'
        if (total > 5_000_000 or ein in debug_eins) and not global_config.is_quiet():
            log_debug("Non-zero grants_to_others $%s for EIN %s, Name %s, TaxYear %s, XML %s",
                        total, ein, charity.filer_name if charity else 'Unknown', charity.tax_year if charity else 'Unknown', xml_filename)
        elif total == 0 and ein in debug_eins and not global_config.is_quiet():
            return_data = parse_string_field(root, XPATHS_990PF, "return_data", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            child_tags = [child.tag for child in return_data.xpath("*", namespaces=namespaces)] if return_data is not None and return_data.xpath is not None else []
            log_debug("Zero grants_to_others for EIN %s, Name %s, File %s. ReturnData children: %r",
                                ein, charity.filer_name if charity else 'Unknown', xml_filename, child_tags)
        return total

    def parse_travel_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        total = 0
        for xpath in XPATHS_990PF["schedule_expenses"]:
            expense_elem = parse_string_field(root, XPATHS_990PF, "schedule_expenses", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            if expense_elem is not None:
                desc = parse_string_field(expense_elem, XPATHS_990PF, "expense_desc", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
                amount = parse_int_field(expense_elem, XPATHS_990PF, "expense_value", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)
                if desc is not None:
                    desc_text = (desc or "").upper()
                    if "TRAVEL" in desc_text:
                        total += amount
                        log_info("Parsed travel_amt ${} from OtherExpensesSchedule in {}",
                                  amount, xml_filename)
        return total

    def parse_conferences_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        total = 0
        for xpath in XPATHS_990PF["schedule_expenses"]:
            expense_elem = parse_string_field(root, XPATHS_990PF, "schedule_expenses", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            if expense_elem is not None:
                desc = parse_string_field(expense_elem, XPATHS_990PF, "expense_desc", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
                amount = parse_int_field(expense_elem, XPATHS_990PF, "expense_value", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)
                if desc is not None:
                    desc_text = (desc or "").upper()
                    if "CONFERENCE" in desc_text or "MEETING" in desc_text:
                        total += amount
                        log_info("Parsed conferences_amt ${} from OtherExpensesSchedule in {}",
                                  amount, xml_filename)
        return total

    def parse_receipt_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)

    def parse_govt_grants_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)

    def parse_contributions_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)

    def parse_total_exp_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)

    def parse_prog_exp_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)

    def parse_total_assets_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        charity = context.getCharity()
        total = parse_int_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats)
        log_info(f"Raw total_assets value: {total} for EIN {charity.ein if charity else 'Unknown'} in {xml_filename}")
        return total

    def parse_filer_name_990pf(self, root, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=None):
        return parse_string_field(root, XPATHS_990PF, field, namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default="Unknown")

    def parse_address_990pf(self, root, xml_filename, context, xpath_cache, charity=None, xpath_match_stats=None):
        """Parse address information from Form 990PF"""
        from parse_utils import parse_string_field
        try:
            namespaces = {'irs': 'http://www.irs.gov/efile'}
            # Parse address components
            address_line1 = parse_string_field(root, XPATHS_990PF, "address_line1", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            address_line2 = parse_string_field(root, XPATHS_990PF, "address_line2", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            city = parse_string_field(root, XPATHS_990PF, "city", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            state = parse_string_field(root, XPATHS_990PF, "state", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)
            zip_code = parse_string_field(root, XPATHS_990PF, "zip_code", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None)

            # Check if we have at least some address components
            if any([address_line1, address_line2, city, state, zip_code]) and charity is not None:
                # Charity must be available to build address - restructure if needed
                return charity.build_address(
                    address_line1=address_line1 or "",
                    address_line2=address_line2 or "",
                    city=city or "",
                    state=state or "",
                    zip_code=zip_code or ""
                )
            return None
        except Exception as e:
            charity = context.getCharity()
            log_error("Failed to parse address for EIN %s in %s: %s", charity.ein if charity else 'Unknown', xml_filename, str(e))
            return None

    def parse_org_type(self, root, field, namespaces, xml_filename, context, xpath_cache, form_type, xpath_match_stats=None, charity=None):
        elem = parse_string_field(root, XPATHS_990PF, "org_type", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
        ein = charity.ein if charity else 'Unknown'
        if elem is not None:
            log_info("Found org_type element: tag={}, text={!r}, attrib={!r} for EIN {} in {}", elem.tag, elem.text, elem.attrib, ein, xml_filename)
            if elem.tag.endswith(tuple(ORG_TYPE_SUFFIXES)):
                if elem.tag.endswith(("Organization501c3ExemptPFInd", "Organization501c3TaxablePFInd")):
                    org_type = "501(c)(3)"
                elif "4947a1" in elem.tag:
                    org_type = "4947(a)(1)"
                else:
                    org_type = "Unknown"
                    log_error("Unexpected org_type tag {} for EIN {} in {}, defaulting to Unknown", elem.tag, ein, xml_filename)
            elif elem.tag.endswith("Organization4947a1TrtdPFInd"):
                # Handle 4947(a)(1) trust organizations
                org_type = "4947(a)(1)"
                log_info("Found org_type tag {} for EIN {} in {} (handled as 4947(a)(1))", elem.tag, ein, xml_filename)
            elif elem.tag.endswith("Organization501c3TaxablePFInd"):
                # Handle taxable private foundations
                org_type = "501(c)(3)"
                log_info("Found org_type tag {} for EIN {} in {} (handled as 501(c)(3) taxable PF)", elem.tag, ein, xml_filename)
            elif elem.tag.endswith("Organization501c3ExemptPFInd"):
                # Handle the case where the tag doesn't end with the expected suffixes but is still valid
                org_type = "501(c)(3)"
                log_info("Found org_type tag {} for EIN {} in {} (handled as 501(c)(3))", elem.tag, ein, xml_filename)
            else:
                org_type = "Unknown"
                log_error(f"Unexpected org_type tag {elem.tag} for EIN {ein} in {xml_filename}, defaulting to Unknown")
        else:
            log_error("Failed to parse org_type for EIN {} in {}", ein, xml_filename)
            return_data = parse_string_field(root, XPATHS_990PF, "return_data", namespaces, xml_filename, context, xpath_cache, xpath_match_stats=xpath_match_stats, default=None, return_element=True)
            org_tags = [child.tag for child in return_data.xpath("*[contains(local-name(), 'Organization')]", namespaces=namespaces)] if return_data is not None and return_data.xpath is not None else []
            form_type_val = charity.form_type if charity else 'Unknown'
            log_error("Form type: {}, Available org_type tags: {!r} in {}", form_type_val, org_tags, xml_filename)
            org_type = "Unknown"
        ein = charity.ein if charity else 'Unknown'
        log_info("Parsed org_type {} for EIN {} in {}", org_type, ein, xml_filename)
        return org_type

def parse_990pf(root, xml_filename, xpath_cache, context, xpath_match_stats=None):
    """Parse Form 990PF - now uses context instead of returning tuples"""
    from pending_database_context import PendingDatabaseContext

    if not isinstance(context, PendingDatabaseContext):
        raise ValueError("context must be a PendingDatabaseContext instance")

    # Validate charity exists
    charity = context.getCharity()
    if not charity or not charity.ein or charity.ein == "Unknown":
        raise ValueError(f"Invalid charity in context for Form 990PF parsing in file {xml_filename}")

    parser = Parser990PF()
    parser.parse_form(root, xml_filename, xpath_cache, context, xpath_match_stats=xpath_match_stats)

def main():
    if len(sys.argv) != 2:
        print("Usage: python parse_990pf.py <xml_file>", file=sys.stderr)
        sys.exit(1)

    xml_file = sys.argv[1]
    try:
        with open(xml_file, 'rb') as f:
            xml_content = f.read()
    except IOError as e:
        print(f"Error reading XML file {xml_file}: {e}", file=sys.stderr)
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
    # Ensure tax_year is always an int for Charity constructor
    if isinstance(tax_year, str):
        try:
            tax_year = int(tax_year)
        except ValueError:
            tax_year = 0  # Default fallback

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
    parse_990pf(root, xml_file, {}, context)

    # Print object counts
    print(context.getObjectCounts())

if __name__ == "__main__":
    main()