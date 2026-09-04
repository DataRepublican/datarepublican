#!/usr/bin/env python3
"""
sanctions_processor.py - Treasury OFAC SDN advanced XML ingest.

Downloads sdn_advanced.xml (curl, idempotent), parses with iterparse, and
promotes to sanctioned_* tables plus Addresses (address_type=ofac_sanction).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from constants import VALID_STATES
from countryCodes import detect_foreign_country, iso3166_alpha2, lookupCC
from database_operations import DatabaseOperations
from download_utils import discover_ofac_sdn_url, ensure_download
from logging_utils import log_info, log_warning
from models import (
    Address,
    SanctionedEntity,
    SanctionedIdentifier,
    SanctionedName,
    SanctionedProgram,
)

BATCH_SIZE = 5_000
CHECKPOINT_EVERY_BATCHES = 5
SDN_FILENAME = "sdn_advanced.xml"
INGEST_VERSION = 3

# OFAC country labels that don't match iso3166 names verbatim.
OFAC_COUNTRY_ALIASES = {
    "BURMA": "MM",
    "KOREA, NORTH": "KP",
    "KOREA, SOUTH": "KR",
    "CONGO, DEMOCRATIC REPUBLIC OF THE": "CD",
    "CONGO, REPUBLIC OF THE": "CG",
    "COTE D IVOIRE": "CI",
    "THE GAMBIA": "GM",
    "BAHAMAS, THE": "BS",
    "IRAN": "IR",
    "RUSSIA": "RU",
}
SKIP_LOCATION_LABELS = frozenset({"", "UNDETERMINED"})

LOC_PART_FIELDS = {
    "1451": "address_line1",
    "1452": "address_line2",
    "1454": "city",
    "1455": "state",
    "1456": "zip_code",
}


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(elem: Optional[ET.Element]) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _bool_attr(value: Optional[str]) -> bool:
    return str(value or "").lower() == "true"


@dataclass
class ParsedLocation:
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""
    unstructured: str = ""


@dataclass
class ParsedIdDocument:
    id_type: str = ""
    id_number: str = ""
    country: str = ""


@dataclass
class ParsedSanctionsEntry:
    list_type: str = ""
    list_date: str = ""
    programs: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class ReferenceLookups:
    alias_types: Dict[str, str] = field(default_factory=dict)
    party_subtypes: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    party_types: Dict[str, str] = field(default_factory=dict)
    id_doc_types: Dict[str, str] = field(default_factory=dict)
    area_codes: Dict[str, str] = field(default_factory=dict)
    countries: Dict[str, str] = field(default_factory=dict)
    lists: Dict[str, str] = field(default_factory=dict)
    sanctions_types: Dict[str, str] = field(default_factory=dict)
    issue_date: str = ""


class SanctionsProcessor:
    def __init__(self, db_ops: DatabaseOperations, data_dir: str | Path):
        self.db_ops = db_ops
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, int]:
        log_info("=== Starting sanctions step (download → parse → promote) ===")
        stats = {
            "downloads": 0,
            "entities": 0,
            "names": 0,
            "identifiers": 0,
            "programs": 0,
            "addresses": 0,
        }

        xml_path = self._ensure_sdn_xml(stats)
        if xml_path is None:
            log_warning("No OFAC SDN XML available — skipping sanctions ingest")
            return stats

        marker = self.data_dir / ".sdn_ingest.json"
        if self._ingest_current(xml_path, marker):
            return self._existing_counts(stats)

        lookups, locations, id_docs, sanctions_entries = self._parse_support_data(xml_path)
        promoted = self._promote_parties(
            xml_path,
            lookups,
            locations,
            id_docs,
            sanctions_entries,
        )
        stats.update(promoted)
        self._save_ingest_marker(marker, xml_path)
        log_info(f"=== Sanctions complete: {stats} ===")
        return stats

    def _ensure_sdn_xml(self, stats: Dict[str, int]) -> Optional[Path]:
        dest = self.data_dir / SDN_FILENAME
        url = discover_ofac_sdn_url()
        try:
            if ensure_download(url, dest, timeout=0):
                stats["downloads"] += 1
        except RuntimeError as exc:
            log_warning(f"OFAC SDN download failed: {exc}")
            if not dest.exists() or dest.stat().st_size == 0:
                return None
        return dest if dest.exists() and dest.stat().st_size > 0 else None

    def _ingest_current(self, source: Path, marker: Path) -> bool:
        if not marker.exists():
            return False
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if meta.get("source") != str(source.resolve()):
            return False
        if meta.get("size") != source.stat().st_size:
            return False
        if meta.get("mtime") != source.stat().st_mtime:
            return False
        if meta.get("ingest_version") != INGEST_VERSION:
            return False
        try:
            count = self.db_ops.execute_query(
                "SELECT COUNT(*) FROM sanctioned_entities"
            ).fetchone()[0]
        except Exception:
            return False
        if count > 0:
            log_info(f"Skipping sanctions ingest — source unchanged ({count:,} entities)")
            return True
        return False

    def _existing_counts(self, stats: Dict[str, int]) -> Dict[str, int]:
        stats["entities"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM sanctioned_entities"
        ).fetchone()[0]
        stats["names"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM sanctioned_names"
        ).fetchone()[0]
        stats["identifiers"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM sanctioned_identifiers"
        ).fetchone()[0]
        stats["programs"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM sanctioned_programs"
        ).fetchone()[0]
        stats["addresses"] = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM Addresses WHERE address_type = 'ofac_sanction'"
        ).fetchone()[0]
        return stats

    def _save_ingest_marker(self, marker: Path, source: Path) -> None:
        st = source.stat()
        marker.write_text(
            json.dumps(
                {
                    "source": str(source.resolve()),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "ingest_version": INGEST_VERSION,
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _resolve_country_code(*candidates: str) -> Optional[str]:
        for raw in candidates:
            if not raw or not str(raw).strip():
                continue
            text = str(raw).strip()
            upper = text.upper()
            if upper in OFAC_COUNTRY_ALIASES:
                return OFAC_COUNTRY_ALIASES[upper]
            if len(text) == 2 and text.isalpha() and lookupCC(text.upper()):
                return text.upper()
            for code, info in iso3166_alpha2.items():
                if info.get("name", "").upper() == upper:
                    return code
            cc = detect_foreign_country(text)
            if cc and cc != "ZZ":
                return cc
        return None

    @staticmethod
    def _has_structured_parts(loc: ParsedLocation) -> bool:
        return bool(
            loc.address_line1
            or loc.address_line2
            or loc.city
            or loc.state
            or loc.zip_code
        )

    @staticmethod
    def _is_promotable_address(address: Address) -> bool:
        if address.colocator and address.colocator.startswith("FA:"):
            return True
        return bool((address.canonical_address or "").strip())

    def _build_foreign_address(
        self, entity: SanctionedEntity, country_code: str
    ) -> Address:
        info = lookupCC(country_code) or {}
        country_name = info.get("name", country_code)
        address = Address(
            ein="",
            name=entity.primary_name or "",
            address_line1=f"Foreign: {country_name}",
            state=country_code,
            colocator=f"FA:{country_code}",
            address_type="ofac_sanction",
            owner_id=entity.id,
        )
        address.prep_for_insert()
        return address

    @staticmethod
    def _is_skipped_label(value: str) -> bool:
        return value.strip().upper() in SKIP_LOCATION_LABELS

    def _build_ofac_address(
        self, entity: SanctionedEntity, loc: ParsedLocation
    ) -> Optional[Address]:
        if self._is_skipped_label(loc.unstructured) and self._is_skipped_label(
            loc.country
        ) and not self._has_structured_parts(loc):
            return None

        if not self._has_structured_parts(loc):
            unstructured = (loc.unstructured or "").strip()
            country_code = self._resolve_country_code(loc.country, unstructured)
            if country_code and (
                not unstructured
                or "," not in unstructured
                or unstructured.upper() in OFAC_COUNTRY_ALIASES
            ):
                return self._build_foreign_address(entity, country_code)
            label = unstructured or (loc.country or "").strip()
            if not label or self._is_skipped_label(label):
                return None
            address = entity.build_address(address_line1=label)
            return address if self._is_promotable_address(address) else None

        if loc.unstructured and not (
            loc.address_line1 or loc.address_line2 or loc.city or loc.zip_code
        ):
            text = loc.unstructured.strip()
            if self._is_skipped_label(text):
                return None
            country_code = self._resolve_country_code(text, loc.country)
            if country_code and (
                "," not in text or text.upper() in OFAC_COUNTRY_ALIASES
            ):
                return self._build_foreign_address(entity, country_code)
            address = entity.build_address(address_line1=text)
            return address if self._is_promotable_address(address) else None

        state = loc.state if loc.state and loc.state.upper() in VALID_STATES else None
        address = entity.build_address(
            address_line1=loc.address_line1,
            address_line2=loc.address_line2,
            city=loc.city,
            state=state,
            zip_code=loc.zip_code,
        )
        return address if self._is_promotable_address(address) else None

    def _parse_support_data(
        self, xml_path: Path
    ) -> Tuple[
        ReferenceLookups,
        Dict[str, ParsedLocation],
        Dict[str, List[ParsedIdDocument]],
        Dict[str, ParsedSanctionsEntry],
    ]:
        log_info(f"Parsing OFAC reference data from {xml_path.name}")
        lookups = ReferenceLookups()
        locations: Dict[str, ParsedLocation] = {}
        id_docs: Dict[str, List[ParsedIdDocument]] = defaultdict(list)
        sanctions_entries: Dict[str, ParsedSanctionsEntry] = {}

        current_ref_bucket: Optional[str] = None
        current_location: Optional[ParsedLocation] = None
        current_location_id: Optional[str] = None
        current_id_doc: Optional[ParsedIdDocument] = None
        current_id_doc_identity: Optional[str] = None
        current_entry: Optional[ParsedSanctionsEntry] = None
        current_entry_profile: Optional[str] = None
        current_measure_type: Optional[str] = None
        skip_party_depth = 0

        for event, elem in ET.iterparse(xml_path, events=("start", "end")):
            tag = _local_tag(elem.tag)

            if tag == "DistinctParty":
                if event == "start":
                    skip_party_depth += 1
                    continue
                skip_party_depth = max(0, skip_party_depth - 1)
                elem.clear()
                continue

            if skip_party_depth > 0:
                if event == "end":
                    elem.clear()
                continue

            if event == "start":
                if tag == "ReferenceValueSets":
                    current_ref_bucket = None
                elif tag in {
                    "AliasTypeValues",
                    "PartySubTypeValues",
                    "PartyTypeValues",
                    "IDRegDocTypeValues",
                    "AreaCodeValues",
                    "CountryValues",
                    "ListValues",
                    "SanctionsTypeValues",
                }:
                    current_ref_bucket = tag
                elif tag == "Location":
                    current_location_id = elem.get("ID")
                    current_location = ParsedLocation()
                elif tag == "IDRegDocument":
                    current_id_doc = ParsedIdDocument()
                    current_id_doc_identity = elem.get("IdentityID")
                    doc_type_id = elem.get("IDRegDocTypeID")
                    if doc_type_id:
                        current_id_doc.id_type = lookups.id_doc_types.get(
                            doc_type_id, doc_type_id
                        )
                    country_id = elem.get("IssuedBy-CountryID")
                    if country_id:
                        current_id_doc.country = (
                            lookups.countries.get(country_id)
                            or lookups.area_codes.get(country_id, "")
                        )
                elif tag == "SanctionsEntry":
                    current_entry = ParsedSanctionsEntry()
                    current_entry_profile = elem.get("ProfileID")
                    list_id = elem.get("ListID")
                    if list_id:
                        current_entry.list_type = lookups.lists.get(list_id, list_id)
                elif tag == "SanctionsMeasure":
                    current_measure_type = elem.get("SanctionsTypeID")
                continue

            if tag == "DateOfIssue" and lookups.issue_date == "":
                year = month = day = ""
                for child in elem:
                    child_tag = _local_tag(child.tag)
                    if child_tag == "Year":
                        year = _text(child)
                    elif child_tag == "Month":
                        month = _text(child).zfill(2)
                    elif child_tag == "Day":
                        day = _text(child).zfill(2)
                if year and month and day:
                    lookups.issue_date = f"{year}-{month}-{day}"

            elif current_ref_bucket == "AliasTypeValues" and tag == "AliasType":
                lookups.alias_types[elem.get("ID", "")] = _text(elem)
            elif current_ref_bucket == "PartySubTypeValues" and tag == "PartySubType":
                party_type_id = elem.get("PartyTypeID", "")
                lookups.party_subtypes[elem.get("ID", "")] = (
                    _text(elem),
                    lookups.party_types.get(party_type_id, party_type_id),
                )
            elif current_ref_bucket == "PartyTypeValues" and tag == "PartyType":
                lookups.party_types[elem.get("ID", "")] = _text(elem)
            elif current_ref_bucket == "IDRegDocTypeValues" and tag == "IDRegDocType":
                lookups.id_doc_types[elem.get("ID", "")] = _text(elem)
            elif current_ref_bucket == "AreaCodeValues" and tag == "AreaCode":
                area_id = elem.get("ID", "")
                lookups.area_codes[area_id] = _text(elem) or elem.get("Description", "")
            elif current_ref_bucket == "CountryValues" and tag == "Country":
                lookups.countries[elem.get("ID", "")] = _text(elem) or elem.get(
                    "Description", ""
                )
            elif current_ref_bucket == "ListValues" and tag == "List":
                lookups.lists[elem.get("ID", "")] = _text(elem)
            elif current_ref_bucket == "SanctionsTypeValues" and tag == "SanctionsType":
                lookups.sanctions_types[elem.get("ID", "")] = _text(elem)

            elif tag == "LocationPart" and current_location is not None:
                part_type = elem.get("LocPartTypeID", "")
                field_name = LOC_PART_FIELDS.get(part_type)
                value = ""
                for sub in elem.iter():
                    if _local_tag(sub.tag) == "Value":
                        value = _text(sub)
                        break
                if field_name and value:
                    setattr(current_location, field_name, value)
                elif part_type == "1" and value:
                    current_location.unstructured = value

            elif tag == "LocationCountry" and current_location is not None:
                country_id = elem.get("CountryID", "")
                current_location.country = (
                    lookups.countries.get(country_id)
                    or lookups.area_codes.get(country_id, "")
                )

            elif tag == "LocationAreaCode" and current_location is not None:
                area_id = elem.get("AreaCodeID", "")
                if not current_location.country:
                    current_location.country = lookups.area_codes.get(area_id, "")

            elif tag == "Location" and current_location is not None and current_location_id:
                locations[current_location_id] = current_location
                current_location = None
                current_location_id = None
                elem.clear()

            elif tag == "IDRegistrationNo" and current_id_doc is not None:
                current_id_doc.id_number = _text(elem)

            elif tag == "IDRegDocument" and current_id_doc is not None:
                if current_id_doc_identity and current_id_doc.id_number:
                    id_docs[current_id_doc_identity].append(current_id_doc)
                current_id_doc = None
                current_id_doc_identity = None
                elem.clear()

            elif tag == "EntryEvent" and current_entry is not None:
                for child in elem:
                    if _local_tag(child.tag) != "Date":
                        continue
                    year = month = day = ""
                    for part in child:
                        part_tag = _local_tag(part.tag)
                        if part_tag == "Year":
                            year = _text(part)
                        elif part_tag == "Month":
                            month = _text(part).zfill(2)
                        elif part_tag == "Day":
                            day = _text(part).zfill(2)
                    if year and month and day:
                        current_entry.list_date = f"{year}-{month}-{day}"

            elif tag == "Comment" and current_entry is not None and current_measure_type == "1":
                program = _text(elem)
                if program:
                    measure_label = lookups.sanctions_types.get("1", "Program")
                    current_entry.programs.append((program, measure_label))

            elif tag == "SanctionsMeasure" and current_entry is not None:
                measure_type_id = elem.get("SanctionsTypeID", "")
                if measure_type_id and measure_type_id != "1":
                    label = lookups.sanctions_types.get(measure_type_id, measure_type_id)
                    current_entry.programs.append((label, label))
                current_measure_type = None

            elif tag == "SanctionsEntry" and current_entry is not None and current_entry_profile:
                sanctions_entries[current_entry_profile] = current_entry
                current_entry = None
                current_entry_profile = None
                elem.clear()

        for subtype_id, (subtype_name, party_type_id) in list(
            lookups.party_subtypes.items()
        ):
            lookups.party_subtypes[subtype_id] = (
                subtype_name,
                lookups.party_types.get(party_type_id, party_type_id),
            )

        return lookups, locations, id_docs, sanctions_entries

    def _promote_parties(
        self,
        xml_path: Path,
        lookups: ReferenceLookups,
        locations: Dict[str, ParsedLocation],
        id_docs: Dict[str, List[ParsedIdDocument]],
        sanctions_entries: Dict[str, ParsedSanctionsEntry],
    ) -> Dict[str, int]:
        log_info("Promoting OFAC DistinctParty records")
        totals = {
            "entities": 0,
            "names": 0,
            "identifiers": 0,
            "programs": 0,
            "addresses": 0,
        }

        entity_batch: List[SanctionedEntity] = []
        name_batch: List[SanctionedName] = []
        identifier_batch: List[SanctionedIdentifier] = []
        program_batch: List[SanctionedProgram] = []
        address_batch: List[Address] = []
        batch_num = 0

        with self.db_ops.acquire_write_conn() as conn:
            self._ensure_sanctions_schema(conn)
            self._clear_sanctions_tables(conn)
            conn.execute("SET preserve_insertion_order=false")
            conn.execute("SET threads=2")

            for party in self._iter_distinct_parties(xml_path, lookups, locations, id_docs, sanctions_entries):
                entity_batch.append(party["entity"])
                name_batch.extend(party["names"])
                identifier_batch.extend(party["identifiers"])
                program_batch.extend(party["programs"])
                address_batch.extend(party["addresses"])

                if len(entity_batch) >= BATCH_SIZE:
                    batch_num += 1
                    totals = self._flush_batches(
                        conn,
                        entity_batch,
                        name_batch,
                        identifier_batch,
                        program_batch,
                        address_batch,
                        totals,
                    )
                    entity_batch.clear()
                    name_batch.clear()
                    identifier_batch.clear()
                    program_batch.clear()
                    address_batch.clear()
                    if batch_num % CHECKPOINT_EVERY_BATCHES == 0:
                        conn.execute("CHECKPOINT")
                        log_info(f"  sanctions checkpoint after {totals['entities']:,} entities")

            if entity_batch:
                totals = self._flush_batches(
                    conn,
                    entity_batch,
                    name_batch,
                    identifier_batch,
                    program_batch,
                    address_batch,
                    totals,
                )
            conn.execute("CHECKPOINT")

        for key, label in (
            ("entities", "sanctioned_entities"),
            ("names", "sanctioned_names"),
            ("identifiers", "sanctioned_identifiers"),
            ("programs", "sanctioned_programs"),
            ("addresses", "Addresses (ofac_sanction)"),
        ):
            log_info(f"  {label}: {totals[key]:,}")
            print(f"  {label}: {totals[key]:,}", flush=True)
        return totals

    def _ensure_sanctions_schema(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sanctioned_entities (
                id UUID DEFAULT uuidv7() PRIMARY KEY,
                ofac_uid VARCHAR NOT NULL UNIQUE,
                primary_name VARCHAR,
                entity_type VARCHAR,
                entity_subtype VARCHAR,
                list_type VARCHAR,
                list_date DATE,
                remarks VARCHAR,
                source_issue_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sanctioned_names (
                id UUID DEFAULT uuidv7() PRIMARY KEY,
                entity_id UUID NOT NULL,
                name VARCHAR NOT NULL,
                alias_type VARCHAR,
                is_primary BOOLEAN DEFAULT FALSE,
                low_quality BOOLEAN DEFAULT FALSE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sanctioned_identifiers (
                id UUID DEFAULT uuidv7() PRIMARY KEY,
                entity_id UUID NOT NULL,
                id_type VARCHAR,
                id_number VARCHAR,
                country VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sanctioned_programs (
                id UUID DEFAULT uuidv7() PRIMARY KEY,
                entity_id UUID NOT NULL,
                program_code VARCHAR NOT NULL,
                sanctions_type VARCHAR
            )
            """
        )

    def _clear_sanctions_tables(self, conn) -> None:
        conn.execute(
            "DELETE FROM Addresses WHERE address_type = 'ofac_sanction'"
        )
        for table in (
            "sanctioned_programs",
            "sanctioned_identifiers",
            "sanctioned_names",
            "sanctioned_entities",
        ):
            conn.execute(f"DELETE FROM {table}")

    def _flush_batches(
        self,
        conn,
        entities: List[SanctionedEntity],
        names: List[SanctionedName],
        identifiers: List[SanctionedIdentifier],
        programs: List[SanctionedProgram],
        addresses: List[Address],
        totals: Dict[str, int],
    ) -> Dict[str, int]:
        if entities:
            self.db_ops.bulk_insert(entities, conn=conn)
            totals["entities"] += len(entities)
        if names:
            self.db_ops.bulk_insert(names, conn=conn)
            totals["names"] += len(names)
        if identifiers:
            self.db_ops.bulk_insert(identifiers, conn=conn)
            totals["identifiers"] += len(identifiers)
        if programs:
            self.db_ops.bulk_insert(programs, conn=conn)
            totals["programs"] += len(programs)
        if addresses:
            self.db_ops.bulk_insert(addresses, conn=conn)
            totals["addresses"] += len(addresses)
        return totals

    def _iter_distinct_parties(
        self,
        xml_path: Path,
        lookups: ReferenceLookups,
        locations: Dict[str, ParsedLocation],
        id_docs: Dict[str, List[ParsedIdDocument]],
        sanctions_entries: Dict[str, ParsedSanctionsEntry],
    ) -> Iterable[Dict[str, List]]:
        in_party = False
        ofac_uid = ""
        profile_id = ""
        party_subtype_id = ""
        remarks = ""
        identity_ids: Set[str] = set()
        location_ids: Set[str] = set()
        names: List[SanctionedName] = []
        current_alias_type = ""
        current_alias_primary = False
        current_alias_low_quality = False
        current_name_parts: List[str] = []

        for event, elem in ET.iterparse(xml_path, events=("start", "end")):
            tag = _local_tag(elem.tag)

            if tag == "DistinctParty" and event == "start":
                in_party = True
                ofac_uid = elem.get("FixedRef", "")
                profile_id = ""
                party_subtype_id = ""
                remarks = ""
                identity_ids = set()
                location_ids = set()
                names = []
                continue

            if not in_party:
                continue

            if event == "start":
                if tag == "Alias":
                    current_alias_type = lookups.alias_types.get(
                        elem.get("AliasTypeID", ""),
                        elem.get("AliasTypeID", ""),
                    )
                    current_alias_primary = _bool_attr(elem.get("Primary"))
                    current_alias_low_quality = _bool_attr(elem.get("LowQuality"))
                elif tag == "DocumentedNamePart":
                    current_name_parts = []
                continue

            if tag == "Comment" and remarks == "":
                remarks = _text(elem)

            elif tag == "Profile":
                profile_id = elem.get("ID", profile_id)
                party_subtype_id = elem.get("PartySubTypeID", "")

            elif tag == "Identity":
                identity_id = elem.get("ID")
                if identity_id:
                    identity_ids.add(identity_id)

            elif tag == "NamePartValue":
                value = _text(elem)
                if value:
                    current_name_parts.append(value)

            elif tag == "DocumentedName":
                name = " ".join(current_name_parts).strip()
                current_name_parts = []
                if name:
                    names.append(
                        {
                            "name": name,
                            "alias_type": current_alias_type,
                            "is_primary": current_alias_primary,
                            "low_quality": current_alias_low_quality,
                        }
                    )

            elif tag == "VersionLocation":
                location_id = elem.get("LocationID")
                if location_id:
                    location_ids.add(location_id)

            elif tag == "DistinctParty" and event == "end":
                subtype, party_type = lookups.party_subtypes.get(
                    party_subtype_id, ("", "")
                )
                entry = sanctions_entries.get(profile_id or ofac_uid)
                primary_name = ""
                for item in names:
                    if item["is_primary"]:
                        primary_name = item["name"]
                        break
                if not primary_name and names:
                    primary_name = names[0]["name"]

                entity = SanctionedEntity(
                    ofac_uid=ofac_uid,
                    primary_name=primary_name or None,
                    entity_type=party_type or None,
                    entity_subtype=subtype or None,
                    list_type=entry.list_type if entry else None,
                    list_date=entry.list_date if entry else None,
                    remarks=remarks or None,
                    source_issue_date=lookups.issue_date or None,
                )
                entity.prep_for_insert()

                entity_names = [
                    SanctionedName(
                        entity_id=entity.id,
                        name=item["name"],
                        alias_type=item["alias_type"] or None,
                        is_primary=item["is_primary"],
                        low_quality=item["low_quality"],
                    )
                    for item in names
                ]
                for obj in entity_names:
                    obj.prep_for_insert()

                entity_identifiers: List[SanctionedIdentifier] = []
                for identity_id in identity_ids:
                    for doc in id_docs.get(identity_id, []):
                        ident = SanctionedIdentifier(
                            entity_id=entity.id,
                            id_type=doc.id_type or None,
                            id_number=doc.id_number or None,
                            country=doc.country or None,
                        )
                        ident.prep_for_insert()
                        entity_identifiers.append(ident)

                entity_programs: List[SanctionedProgram] = []
                if entry:
                    for program_code, sanctions_type in entry.programs:
                        prog = SanctionedProgram(
                            entity_id=entity.id,
                            program_code=program_code,
                            sanctions_type=sanctions_type,
                        )
                        prog.prep_for_insert()
                        entity_programs.append(prog)

                entity_addresses: List[Address] = []
                for location_id in location_ids:
                    loc = locations.get(location_id)
                    if loc is None:
                        continue
                    address = self._build_ofac_address(entity, loc)
                    if address is not None:
                        entity_addresses.append(address)

                yield {
                    "entity": entity,
                    "names": entity_names,
                    "identifiers": entity_identifiers,
                    "programs": entity_programs,
                    "addresses": entity_addresses,
                }

                in_party = False
                elem.clear()