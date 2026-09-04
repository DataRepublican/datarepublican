#!/usr/bin/env python3
"""
models/address.py - Address data model

This module contains the Address dataclass and related business logic.
Addresses represent physical locations associated with charities and other entities.

Colocator Format:
  LL:<lat>:<long>     - Latitude and longitude of the address, starts empty until geocoded
  EIN:<EIN>           - Used for grants that provide an EIN so we don't need to geolocate an Address
  PO:<po_box>:<zip5> - Used for addresses that are PO Boxes. No need to geolocate, it would be the post office anyways
  FA:<countrycode>    - Used for foreign addresses
  AMBIG:<state>:<zip5> - Declared state disagrees with US_zips primary state for that ZIP

This allows downstream database joins by location.
"""

import json
from dataclasses import dataclass, field
from typing import Optional
from constants import VALID_STATES, PO_BOX_REGEX, PO_BOX_NUMBER_REGEX, STREET_FIXES, UNIT_FIXES
from countryCodes import lookupCC
from .base import BaseModel
from models.geocoding import Geocoding
from logging_utils import log_debug
from us_zip_lookup import ambig_colocator, is_state_zip_mismatch


@dataclass
class Address(BaseModel):
    """Represents a physical address with geocoding information"""

    address_id: Optional[int] = None
    ein: str = ""
    name: str = ""
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None  # First 5 digits
    zip4: Optional[str] = None  # Last 4 digits
    po_box: Optional[str] = None
    canonical_address: Optional[str] = None  # Standardized address for geocoding
    address_type: str = "filer"  # filer, grant_recipient, etc.
    owner_id: Optional[str] = None  # Loose relationship to owning entity (EIN or UUID)
    geocoding_id: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    colocator: Optional[str] = None
    created_at: Optional[str] = None
    master_id: Optional[str] = None


    @property
    def po_box_number(self) -> Optional[str]:
        """Extract PO Box number from address_line1"""
        if not self.address_line1:
            return None

        match = PO_BOX_REGEX.search(self.address_line1.upper())
        if match:
            return match.group(1)
        return None

    @po_box_number.setter
    def po_box_number(self, value: Optional[str]):
        """Set PO Box number (for backward compatibility)"""
        self.po_box = value

    def is_valid_state(self) -> bool:
        """Check if state is valid"""
        return self.state in VALID_STATES if self.state else False

    def is_po_box(self) -> Optional[str]:
        """Return PO Box number if this is a PO Box address, None otherwise"""
        if self.po_box:
            return self.po_box
        if self.address_line1 and "PO BOX" in self.address_line1.upper():
            match = PO_BOX_REGEX.search(self.address_line1.upper())
            if match:
                po_box_str = match.group(1).strip() if match.group(1) else ""
                if po_box_str:
                    number_match = PO_BOX_NUMBER_REGEX.match(po_box_str)
                    if number_match:
                        return number_match.group(0)
                else:
                    # No specific box number, but it's still a PO Box
                    return "POBOX"
        return None

    def canonicalize_address(self):
        """Canonicalize the address by expanding abbreviations and setting canonical_address as a comma-separated list"""
        # Check if this is a foreign address (FA colocator) and return early if so
        if self.colocator and self.colocator.startswith('FA:'):
            return

        # Build parts with parts.append each piece directly from self, and then use a list comprehension to filter out the None
        parts = [self.address_line1, self.address_line2, self.city, self.state, self.zip_code]
        parts = [p for p in parts if p is not None]

        # Expand abbreviations in place
        if self.address_line1:
            words = self.address_line1.split()
            if words and words[-1] in STREET_FIXES:
                words[-1] = STREET_FIXES[words[-1]]
                self.address_line1 = " ".join(words)

        if self.address_line2:
            words = self.address_line2.split()
            if len(words) >= 2 and words[-2] in UNIT_FIXES:
                words[-2] = UNIT_FIXES[words[-2]]
                self.address_line2 = " ".join(words)

        # Detect PO Box
        po_box_candidate = None
        for line in (self.address_line1, self.address_line2):
            if line:
                match = PO_BOX_REGEX.search(line.upper())
                if match:
                    po_box_str = (match.group(1) or "").strip()
                    if po_box_str:
                        number_match = PO_BOX_NUMBER_REGEX.match(po_box_str)
                        if number_match:
                            po_box_candidate = number_match.group(0)
                            break
                    else:
                        # Generic PO Box with no number (still skip geocoding)
                        po_box_candidate = "POBOX"
                        break

        if po_box_candidate:
            self.po_box = po_box_candidate

        # Validate state
        if self.state and self.state.upper() not in VALID_STATES:
            self.state = None

        # Split ZIP code
        if self.zip_code:
            from parse_utils import split_zip_code
            self.zip_code, self.zip4 = split_zip_code(self.zip_code)

        # Set colocator for PO Boxes
        if self.po_box:
            if self.po_box == "POBOX":
                # Generic PO Box without specific number
                self.colocator = f"PO:BOX:{self.zip_code}"
            else:
                # Specific PO Box number
                self.colocator = f"PO:{self.po_box}:{self.zip_code}"
        elif self.state and self.zip_code and is_state_zip_mismatch(self.state, self.zip_code):
            # Declared state vs ZIP region conflict (e.g. Atlanta, NJ 30339)
            # Prefer ZIP's geography for joins; keep declared state in the tag.
            self.colocator = ambig_colocator(self.state, self.zip_code)

        # Build canonical address with comma-separated components
        canonical_parts = []
        if self.po_box:
            if self.po_box == "POBOX":
                canonical_parts.append("PO Box")
            else:
                canonical_parts.append(f"PO Box {self.po_box}")
        if self.address_line1:
            canonical_parts.append(self.address_line1)
        if self.address_line2:
            canonical_parts.append(self.address_line2)
        if self.city:
            canonical_parts.append(self.city)
        if self.state:
            canonical_parts.append(self.state)
        if self.zip_code:
            canonical_parts.append(self.zip_code)

        if canonical_parts:
            self.canonical_address = ", ".join(canonical_parts).title()
        else:
            self.canonical_address = ""

    @classmethod
    def create_for_charity(cls, charity, address_line1: Optional[str] = None, address_line2: Optional[str] = None,
                          city: Optional[str] = None, state: Optional[str] = None, zip_code: Optional[str] = None,
                          zip4: Optional[str] = None, address_type: str = "charity") -> 'Address':
        """Factory method to create an Address for a specific charity"""
        result = cls(
            ein=charity.ein,
            name=charity.filer_name,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            zip_code=zip_code,
            zip4=zip4,
            address_type=address_type,
            owner_id=charity.charity_id
        )
        if result.colocator: charity.colocator = result.colocator

    @classmethod
    def create_foreign_address(cls, country_code: str, address_type: str = "filer", owner_id: Optional[str] = None) -> 'Address':
        """Factory method to create an Address record for foreign addresses"""
        country_info = lookupCC(country_code)
        if country_info:
            country_name = country_info['name']
            # Use the country number as the EIN for foreign addresses
            ein = country_info['number']
            name = country_name
        else:
            country_name = f"Unknown Country ({country_code})"
            ein = "999"
            name = country_name

        address = cls(
            ein=ein,
            name=name,
            address_line1=f"Foreign: {country_name}",
            state=country_code,
            colocator=f"FA:{country_code}",
            address_type=address_type,
            owner_id=owner_id
        )
        return address

    def prep_for_insert(self):
        """Prepare address for database insertion by canonicalizing, detecting PO Boxes, and setting colocators"""
        # Call superclass first
        super().prep_for_insert()
        # Then do address-specific logic
        self.canonicalize_address()

    def census_json(self) -> dict:
        """Build JSON dictionary ready for census geocoding API"""
        # Use the canonicalized address components
        street_parts = []
        if self.address_line1:
            street_parts.append(self.address_line1)
        if self.address_line2:
            street_parts.append(self.address_line2)

        census_data = {
            'id': 0,  # Will be set by caller
            'street': ' '.join(street_parts).strip(),
            'city': self.city or '',
            'state': self.state or '',
            'zip': self.zip_code or ''
        }

        # Debug logging: Log census_json creation
        log_debug(f"Address {self.address_id} census_json: street='{census_data['street']}', city='{census_data['city']}', state='{census_data['state']}', zip='{census_data['zip']}'")

        return census_data

    def create_geocoding(self) -> 'Geocoding':
        """Factory method to create a Geocoding record for this address"""
        # Ensure address is canonicalized
        self.canonicalize_address()

        # Build census JSON
        census_json = self.census_json()

        # Create Geocoding object
        geocoding = Geocoding(
            canonical_address=self.canonical_address or "",
            normalized_address=json.dumps(census_json),  # Store as proper JSON string
            geocoding_status='pending'
        )

        return geocoding

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations"""
        return {
            'address_id': self.address_id,
            'ein': self.ein,
            'owner_id': self.owner_id,
            'master_id': self.master_id,
            'name': self.name,
            'address_line1': self.address_line1,
            'address_line2': self.address_line2,
            'city': self.city,
            'state': self.state,
            'zip_code': self.zip_code,
            'zip4': self.zip4,
            'po_box': self.po_box,
            'canonical_address': self.canonical_address,
            'address_type': self.address_type,
            'geocoding_id': self.geocoding_id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'colocator': self.colocator,
            'created_at': self.created_at
        }