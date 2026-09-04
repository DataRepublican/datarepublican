#!/usr/bin/env python3
"""
parse_contractors.py - Parse contractors from Schedule L (Transactions with Interested Persons) from IRS 990 forms

This module handles parsing of contractors from Schedule L (Transactions with Interested Persons)
from IRS Form 990, 990EZ, and 990PF.
"""

import re
from lxml import etree  # type: ignore
from io import BytesIO
import logging
from xpaths import NAMESPACES, SCHEDULE_L_XPATHS
from xpaths_990 import XPATHS_990
from xpaths_990ez import XPATHS_990EZ
from xpaths_990pf import XPATHS_990PF
from constants import MONEY_PATTERN, FLOAT_PATTERN
from typing import Optional, List, Dict, Any
from models.contractor import Contractor
from models.address import Address
from models.charity import Charity

def parse_contractors(root, xml_filename: str, filer_ein: str, filer_name: str, tax_year: int, form_type: str, context=None) -> List[Dict[str, Any]]:
    """Parse contractors from Schedule L"""
    contractors = []
    try:

        # Select the appropriate XPath dictionary based on form_type
        if form_type == "990":
            xpath_dict = XPATHS_990
        elif form_type == "990EZ":
            xpath_dict = XPATHS_990EZ
        elif form_type == "990PF":
            xpath_dict = XPATHS_990PF
        else:
            xpath_dict = XPATHS_990  # Default to 990 if unknown form type

        # Use the form-specific XPath patterns from xpaths.py
        contractor_xpaths = SCHEDULE_L_XPATHS.get(form_type, [])

        for xpath in contractor_xpaths:
            elements = xpath(root)
            for elem in elements:
                # Extract contractor name using new XPath patterns
                name_line1_xpaths = xpath_dict.get("contractor_name_line1", [])
                name_line2_xpaths = xpath_dict.get("contractor_name_line2", [])

                contractor_name_parts = []
                for name_xpath in name_line1_xpaths:
                    try:
                        name_elem = name_xpath(elem)
                        if name_elem and name_elem[0].text:
                            contractor_name_parts.append(name_elem[0].text.strip())
                            break
                    except:
                        continue

                for name_xpath in name_line2_xpaths:
                    try:
                        name_elem = name_xpath(elem)
                        if name_elem and name_elem[0].text:
                            contractor_name_parts.append(name_elem[0].text.strip())
                            break
                    except:
                        continue

                contractor_name = " ".join(contractor_name_parts) if contractor_name_parts else "Unknown"

                # Extract address components
                address_line1 = None
                address_line2 = None
                city = None
                state = None
                zip_code = None

                address_line1_xpaths = xpath_dict.get("contractor_address_line1", [])
                for addr_xpath in address_line1_xpaths:
                    try:
                        addr_elem = addr_xpath(elem)
                        if addr_elem and addr_elem[0].text:
                            address_line1 = addr_elem[0].text.strip()
                            break
                    except:
                        continue

                address_line2_xpaths = xpath_dict.get("contractor_address_line2", [])
                for addr_xpath in address_line2_xpaths:
                    try:
                        addr_elem = addr_xpath(elem)
                        if addr_elem and addr_elem[0].text:
                            address_line2 = addr_elem[0].text.strip()
                            break
                    except:
                        continue

                city_xpaths = xpath_dict.get("contractor_city", [])
                for city_xpath in city_xpaths:
                    try:
                        city_elem = city_xpath(elem)
                        if city_elem and city_elem[0].text:
                            city = city_elem[0].text.strip()
                            break
                    except:
                        continue

                state_xpaths = xpath_dict.get("contractor_state", [])
                for state_xpath in state_xpaths:
                    try:
                        state_elem = state_xpath(elem)
                        if state_elem and state_elem[0].text:
                            state = state_elem[0].text.strip()
                            break
                    except:
                        continue

                zip_xpaths = xpath_dict.get("contractor_zip_code", [])
                for zip_xpath in zip_xpaths:
                    try:
                        zip_elem = zip_xpath(elem)
                        if zip_elem and zip_elem[0].text:
                            zip_code = zip_elem[0].text.strip()
                            break
                    except:
                        continue

                # Extract compensation amount
                amount_xpaths = [
                    etree.XPath("irs:CompensationAmt", namespaces=NAMESPACES),
                    etree.XPath("irs:ServicesAmt", namespaces=NAMESPACES),
                    etree.XPath("irs:TotalAmt", namespaces=NAMESPACES),
                    etree.XPath("CompensationAmt"),
                    etree.XPath("ServicesAmt"),
                    etree.XPath("TotalAmt"),
                ]

                amount = 0.0
                for amt_xpath in amount_xpaths:
                    try:
                        amt_elem = amt_xpath(elem)
                        if amt_elem and amt_elem[0].text:
                            amount = parse_float_field(amt_elem[0].text.strip())
                            if amount > 0:
                                break
                    except:
                        continue

                # Extract EIN if available
                ein_xpaths = [
                    etree.XPath("irs:EIN", namespaces=NAMESPACES),
                    etree.XPath("irs:ContractorEIN", namespaces=NAMESPACES),
                    etree.XPath("EIN"),
                    etree.XPath("ContractorEIN"),
                ]

                contractor_ein = None
                for ein_xpath in ein_xpaths:
                    try:
                        ein_elem = ein_xpath(elem)
                        if ein_elem and ein_elem[0].text:
                            raw_ein = ein_elem[0].text.strip()
                            if raw_ein.isdigit():
                                contractor_ein = f"{int(raw_ein):09d}"
                                break
                    except:
                        continue

                if amount > 0:
                    # Build full address string
                    address_parts = []
                    if address_line1:
                        address_parts.append(address_line1)
                    if address_line2:
                        address_parts.append(address_line2)
                    if city:
                        address_parts.append(city)
                    if state:
                        address_parts.append(state)
                    full_address = ", ".join(address_parts) if address_parts else None

                    contractor_data = {
                        'filer_ein': filer_ein,
                        'name': contractor_name,
                        'amount': amount,
                        'ein': contractor_ein,
                        'address': full_address,
                        'zip_code': zip_code,
                        'tax_year': tax_year
                    }
                    contractors.append(contractor_data)

                    # If context is provided, also add to context
                    if context is not None:
                        # Create a dummy Charity object to use the factory method
                        dummy_charity = Charity(ein=filer_ein, tax_year=tax_year, filer_name=filer_name)
                        contractor_obj = dummy_charity.build_contractor(
                            name=contractor_name,
                            amount=amount,
                            ein=contractor_ein
                        )
                        context.addObjectToDatabase(contractor_obj)

                        # Create and add Address record owned by the contractor
                        if address_line1 or address_line2 or city or state or zip_code:
                            address_obj = contractor_obj.build_address(
                                address_line1=address_line1,
                                address_line2=address_line2,
                                city=city,
                                state=state,
                                zip_code=zip_code
                            )
                            context.addObjectToDatabase(address_obj)

    except Exception as e:
        logging.error(f"Error parsing contractors from {xml_filename}: {e}")
    return contractors

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