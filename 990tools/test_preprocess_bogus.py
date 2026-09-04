#!/usr/bin/env python3
"""Unit tests for preprocess bogus / city-only short-circuit detection."""

import unittest
from unittest.mock import MagicMock

from geocoding_api_processor import GeocodingAPIProcessor, GeocodingWorkUnit


class TestPreprocessBogus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GeocodingAPIProcessor._us_zip_codes = None
        GeocodingAPIProcessor._us_zip_states = None
        GeocodingAPIProcessor._us_zip_coords = None
        db_ops = MagicMock()
        cls.proc = GeocodingAPIProcessor(db_ops, MagicMock())
        cls.proc.run_stats.preprocess_match = 0

    def _unit(self, canonical: str, parsed: dict) -> GeocodingWorkUnit:
        return GeocodingWorkUnit.work_item('preprocess', {
            'geocoding_id': '00000000-0000-0000-0000-000000000001',
            'canonical_address': canonical,
            'normalized_address': parsed,
            'attempt_count': 0,
            'address_count': 1,
            'geocoding_status': 'pending',
        })

    def test_placeholder_street_structured(self):
        unit = self._unit('Unknown, Las Vegas, Nv, 89102', {
            'street': 'Unknown', 'city': 'Las Vegas', 'state': 'NV', 'zip': '89102',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '89102')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:89102')

    def test_city_only_from_structured(self):
        unit = self._unit('Fort Lauderdale, Fl, 33336', {
            'street': 'Fort Lauderdale', 'city': 'Fort Lauderdale', 'state': 'FL', 'zip': '33336',
        })
        pattern = self.proc._check_geocoding_patterns(
            unit.canonical_address, '33336', 'safe', parsed=unit.parsed_normalized,
        )
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern['colocator'], 'VENDOR:Fort Lauderdale:FL:33336')
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'VENDOR:Fort Lauderdale:FL:33336',
        )

    def test_city_only_empty_street(self):
        unit = self._unit('Dallas, Tx, 75392', {
            'street': '', 'city': 'Dallas', 'state': 'TX', 'zip': '75392',
        })
        self.assertTrue(self.proc._is_city_only_parsed('', 'Dallas', 'TX', '75392', unit.canonical_address))

    def test_real_street_not_city_only(self):
        unit = self._unit('123 Main St, Dallas, Tx, 75392', {
            'street': '123 Main St', 'city': 'Dallas', 'state': 'TX', 'zip': '75392',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '75392')
        self.assertIsNone(hit)

    def test_canadian_province(self):
        unit = self._unit('100 King St, Toronto, On,  M5H', {
            'street': '100 King St', 'city': 'Toronto', 'state': 'On', 'zip': 'M5H',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:CA')

    def test_foreign_city_zip_short_zip(self):
        unit = self._unit('Toronto, 516', {
            'street': '', 'city': 'Toronto', 'state': '', 'zip': '516',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_us_zip_lookup_loaded(self):
        self.assertGreater(len(self.proc._us_zip_codes or ()), 40_000)

    def test_invalid_us_zip_foreign(self):
        unit = self._unit('Muenchen, 80639', {
            'street': '', 'city': 'Muenchen', 'state': '', 'zip': '15000',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '15000')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_pr_territory_vendor(self):
        unit = self._unit('Salisburry St, Culebra, Pr, 00775', {
            'street': 'SALISBURRY ST', 'city': 'CULEBRA', 'state': 'PR', 'zip': '00775',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '00775')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'VENDOR:CULEBRA:PR:00775',
        )

    def test_dept_mail_drop(self):
        unit = self._unit('Dept 912024, Denver, Co, 80291', {
            'street': 'DEPT 912024', 'city': 'DENVER', 'state': 'CO', 'zip': '80291',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '80291')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'DEPT:912024:80291',
        )

    def test_zip_only_valid_us_zip(self):
        unit = self._unit('13346', {
            'street': '', 'city': '', 'state': '', 'zip': '13346',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '13346')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'VENDOR::NY:13346',
        )

    def test_zip_only_invalid_us_zip(self):
        unit = self._unit('25730', {
            'street': '', 'city': '', 'state': '', 'zip': '25730',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '25730')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'PARTIAL:25730',
        )

    def test_foreign_city_with_us_zip(self):
        unit = self._unit('Calgary, 12345', {
            'street': '', 'city': 'Calgary', 'state': '', 'zip': '12345',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '12345')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_highway_intersection_partial(self):
        unit = self._unit('Oak Ave & Interstate, San Jose, Ca, 95110', {
            'street': 'Oak Ave & Interstate', 'city': 'San Jose', 'state': 'CA', 'zip': '95110',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '95110')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PARTIAL:95110')

    def test_department_numbered_mail_drop(self):
        unit = self._unit('Department 4387, Carol Stream, Il, 60122', {
            'street': 'DEPARTMENT 4387', 'city': 'CAROL STREAM', 'state': 'IL', 'zip': '60122',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '60122')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'DEPT:4387:60122',
        )

    def test_bin_mail_drop(self):
        unit = self._unit('Bin 88263, Milwaukee, Wi, 53288', {
            'street': 'BIN 88263', 'city': 'MILWAUKEE', 'state': 'WI', 'zip': '53288',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '53288')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'DEPT:BIN88263:53288',
        )

    def test_street_intersection_partial(self):
        unit = self._unit('34Th St & Civic Center Blvd, Philadelphia, Pa, 19104', {
            'street': '34TH ST & CIVIC CENTER BLVD', 'city': 'PHILADELPHIA', 'state': 'PA', 'zip': '19104',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '19104')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PARTIAL:19104')

    def test_short_non_us_zip_intl(self):
        unit = self._unit('12732 Clarice Ave, Tecumseh,, 816', {
            'street': '12732 CLARICE AVE', 'city': 'TECUMSEH', 'state': '', 'zip': '816',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '816')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_apo_military_shortcircuit(self):
        unit = self._unit(
            'Brian D. Allgood Army Community Hospital, Unit #15245, Apo, Ap, 96271',
            {
                'street': 'BRIAN D. ALLGOOD ARMY COMMUNITY HOSPITAL UNIT #15245',
                'city': 'APO', 'state': 'AP', 'zip': '96271',
            },
        )
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '96271')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'MILITARY:APO:96271',
        )

    def test_street_and_street_intersection_partial(self):
        unit = self._unit('2Nd Street And C Ave, Morrison, Ok, 73061', {
            'street': '2ND STREET AND C AVE', 'city': 'MORRISON', 'state': 'OK', 'zip': '73061',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '73061')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PARTIAL:73061')

    def test_dept_period_mail_drop(self):
        unit = self._unit('Dept. 4698, Carol Stream, Il, 60122', {
            'street': 'DEPT. 4698', 'city': 'CAROL STREAM', 'state': 'IL', 'zip': '60122',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '60122')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'DEPT:4698:60122')

    def test_fpo_ap_city_token_military(self):
        unit = self._unit('Uss John S. Mccain Ddg-56, Fpo Ap, Ca, 96672', {
            'street': 'USS JOHN S. MCCAIN DDG-56', 'city': 'FPO AP', 'state': 'CA', 'zip': '96672',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '96672')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'MILITARY:FPO:96672')

    def test_leading_ampersand_intersection(self):
        unit = self._unit('& Point View Terrace, Wheeling, Wv, 26003', {
            'street': '& POINT VIEW TERRACE', 'city': 'WHEELING', 'state': 'WV', 'zip': '26003',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '26003')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PARTIAL:26003')

    def test_dumc_univ_mail_code(self):
        unit = self._unit('Dumc 3034, Durham, Nc, 27710', {
            'street': 'DUMC 3034', 'city': 'DURHAM', 'state': 'NC', 'zip': '27710',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '27710')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'UNIV:27710')

    def test_po_drawer_mail_drop(self):
        unit = self._unit('P O Drawer 30, Forest, Ms, 39074', {
            'street': 'P O DRAWER 30', 'city': 'FOREST', 'state': 'MS', 'zip': '39074',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PO:30:39074')

    def test_mchj_dept_code(self):
        unit = self._unit('Madigan Army Medical Ctr, Mchj-P, Tacoma, Wa, 98431', {
            'street': 'MADIGAN ARMY MEDICAL CTR MCHJ-P', 'city': 'TACOMA', 'state': 'WA', 'zip': '98431',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '98431')
        self.assertIsNotNone(hit)

    def test_housecalls_only_bogus(self):
        unit = self._unit('Housecalls Only, East Bay, Ca, 94536', {
            'street': 'HOUSECALLS ONLY', 'city': 'EAST BAY', 'state': 'CA', 'zip': '94536',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '94536')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:94536')

    def test_psc_military_shortcircuit(self):
        unit = self._unit('Psc 482, Nmrtc Okinawa, Fpo, Ap, 96362', {
            'street': 'PSC 482', 'city': 'NMRTC OKINAWA', 'state': 'AP', 'zip': '96362',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '96362')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'MILITARY:PSC482:96362',
        )

    def test_usnh_italy_foreign(self):
        unit = self._unit('Usnh Naples, Italy, Psc 827, 09617', {
            'street': 'USNH NAPLES, ITALY', 'city': 'PSC 827', 'state': '', 'zip': '09617',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '09617')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'MILITARY:PSC827:09617',
        )

    def test_eamc_org_only_dept(self):
        unit = self._unit('Eamc, Gastroenterology, Fort Gordon, Ga, 30905', {
            'street': 'EAMC GASTROENTEROLOGY', 'city': 'FORT GORDON', 'state': 'GA', 'zip': '30905',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '30905')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'DEPT:30905')

    def test_standalone_drawer_preprocess(self):
        unit = self._unit('Drawer C, Bonham, Tx, 75418', {
            'street': 'DRAWER C', 'city': 'BONHAM', 'state': 'TX', 'zip': '75418',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PO:C:75418')

    def test_p0_drawer_preprocess(self):
        unit = self._unit('P0 Drawer 429 1301 Old Hwy 52 South, Moncks Corner, Sc, 29461', {
            'street': 'P0 DRAWER 429 1301 OLD HWY 52 SOUTH',
            'city': 'MONCKS CORNER', 'state': 'SC', 'zip': '29461',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'PO:429:29461')

    def test_gen_delivery_abbrev(self):
        unit = self._unit('Gen Delivery, Gillette, Wy, 82717', {
            'street': 'GEN DELIVERY', 'city': 'GILLETTE', 'state': 'WY', 'zip': '82717',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:82717')

    def test_marshall_islands_ajeltake(self):
        unit = self._unit('Trust Company Complex, Ajeltake Road, Majuro, 96960', {
            'street': 'Trust Company Complex Ajeltake Road',
            'city': 'Majuro', 'state': '', 'zip': '96960',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_privacy_redacted_xxxx(self):
        unit = self._unit('Xxxx, Chicago, Il, 60690', {
            'street': 'XXXX', 'city': 'CHICAGO', 'state': 'IL', 'zip': '60690',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:60690')

    def test_privacy_not_releasable(self):
        unit = self._unit('Not Releasable, Ft. Hood, Tx, 76544', {
            'street': 'Not Releasable', 'city': 'Ft. Hood', 'state': 'TX', 'zip': '76544',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:76544')

    def test_major_foreign_city_name_only(self):
        unit = self._unit('Moscow', {
            'street': 'Moscow', 'city': '', 'state': '', 'zip': '',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_major_foreign_country_name_only(self):
        unit = self._unit('Nicaragua', {
            'street': 'Nicaragua', 'city': '', 'state': '', 'zip': '',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'FA:INTL')

    def test_us_city_paris_tx_not_foreign(self):
        """Paris TX has a valid US state+ZIP anchor — not FA:INTL."""
        unit = self._unit('Paris, Tx, 75460', {
            'street': 'Paris', 'city': 'Paris', 'state': 'TX', 'zip': '75460',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '75460')
        if hit is not None:
            coloc = hit[1].data.operations[0].data['updates'][0]['colocator']
            self.assertFalse(str(coloc).startswith('FA:'), coloc)

    def test_state_zip_mismatch(self):
        unit = self._unit('1100 Circle 75 Pkwy, Atlanta, Nj, 30339', {
            'street': '1100 Circle 75 Pkwy', 'city': 'Atlanta', 'state': 'NJ', 'zip': '30339',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '30339')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(
            result.data.operations[0].data['updates'][0]['colocator'],
            'AMBIG:NJ:30339',
        )

    def test_address_model_sets_ambig_colocator(self):
        """Primary path: Address.canonicalize sets AMBIG colocator on state/ZIP conflict."""
        from models.address import Address
        addr = Address(
            address_line1='1100 Circle 75 Pkwy',
            city='Atlanta',
            state='NJ',
            zip_code='30339',
        )
        addr.canonicalize_address()
        self.assertEqual(addr.colocator, 'AMBIG:NJ:30339')

    def test_grok_prompt_bans_tool_refusal_unkn(self):
        """Complete US streets must not be UNKN for missing tools / prior API failure."""
        unit = self._unit('3645 Grand Ave, Oakland, Ca, 94610', {
            'street': '3645 Grand Ave', 'city': 'Oakland', 'state': 'CA', 'zip': '94610',
        })
        sys_p, user_p = GeocodingAPIProcessor.build_grok_geocode_messages([unit])
        self.assertIn('COMPLETE US STREET RULE', sys_p)
        self.assertIn('MUST NOT use failure_code=UNKN for a complete US street', sys_p)
        self.assertIn('NO external geocoder API', sys_p)
        self.assertIn('missing tools', user_p.lower())

    def test_state_zip_match_ok(self):
        unit = self._unit('123 Main St, Atlanta, Ga, 30339', {
            'street': '123 Main St', 'city': 'Atlanta', 'state': 'GA', 'zip': '30339',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '30339')
        self.assertIsNone(hit)

    def test_same_as_above_placeholder(self):
        unit = self._unit('Same As Above, Houston, Tx, 77002', {
            'street': 'Same As Above', 'city': 'Houston', 'state': 'TX', 'zip': '77002',
        })
        hit = self.proc._preprocess_bogus_shortcircuit(unit, unit.parsed_normalized, '77002')
        self.assertIsNotNone(hit)
        _, result = hit
        self.assertEqual(result.data.operations[0].data['updates'][0]['colocator'], 'BOGUS:77002')

    def test_momentum_place_lockbox_pattern(self):
        unit = self._unit('3781 Momentum Pl, Chicago, Il, 60689', {
            'street': '3781 Momentum Pl', 'city': 'Chicago', 'state': 'IL', 'zip': '60689',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        coloc = result.data.operations[0].data['updates'][0]['colocator']
        self.assertTrue(str(coloc).startswith('PO:MAIL'), coloc)

    def test_bny_mellon_safe_pattern(self):
        unit = self._unit('C/O Bny Mellon Na, New York, Ny, 10019', {
            'street': 'C/O Bny Mellon Na', 'city': 'New York', 'state': 'NY', 'zip': '10019',
        })
        results = self.proc._preprocess_handler([unit])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        coloc = result.data.operations[0].data['updates'][0]['colocator']
        self.assertIn('BNY Mellon', str(coloc))


if __name__ == '__main__':
    unittest.main()