# iso3166_1_alpha_2.py
# Complete list of ISO 3166-1 alpha-2 country codes with number (starting from 002) and name
import re
from typing import Optional

iso3166_alpha2 = {
    "AF": {"number": "002", "name": "Afghanistan"},
    "AL": {"number": "003", "name": "Albania"},
    "DZ": {"number": "004", "name": "Algeria"},
    "AG": {"number": "004", "name": "Algeria"}, # FIPS
    "AS": {"number": "005", "name": "American Samoa"},
    "AD": {"number": "006", "name": "Andorra"},
    "AN": {"number": "006", "name": "Andorra"}, # FIPS
    "AO": {"number": "007", "name": "Angola"},
    "AI": {"number": "008", "name": "Anguilla"},
    "AQ": {"number": "009", "name": "Antarctica"},
    "AY": {"number": "009", "name": "Antarctica"}, #FIPS
    "AG": {"number": "010", "name": "Antigua and Barbuda"},
    "AR": {"number": "011", "name": "Argentina"},
    "AM": {"number": "012", "name": "Armenia"},
    "AW": {"number": "013", "name": "Aruba"},
    "AA": {"number": "013", "name": "Aruba"}, #FIPS
    "AU": {"number": "014", "name": "Australia"},
    "AT": {"number": "015", "name": "Austria"},
    "AZ": {"number": "016", "name": "Azerbaijan"},
    "BS": {"number": "017", "name": "Bahamas"},
    "BH": {"number": "018", "name": "Bahrain"},
    "BD": {"number": "019", "name": "Bangladesh"},
    "BB": {"number": "020", "name": "Barbados"},
    "BY": {"number": "021", "name": "Belarus"},
    "BE": {"number": "022", "name": "Belgium"},
    "BZ": {"number": "023", "name": "Belize"},
    "BJ": {"number": "024", "name": "Benin"},
    "BM": {"number": "025", "name": "Bermuda"},
    "BT": {"number": "026", "name": "Bhutan"},
    "BO": {"number": "027", "name": "Bolivia"},
    "BA": {"number": "028", "name": "Bosnia and Herzegovina"},
    "BW": {"number": "029", "name": "Botswana"},
    "BR": {"number": "030", "name": "Brazil"},
    "IO": {"number": "031", "name": "British Indian Ocean Territory"},
    "VG": {"number": "032", "name": "British Virgin Islands"},
    "BN": {"number": "033", "name": "Brunei"},
    "BG": {"number": "034", "name": "Bulgaria"},
    "BU": {"number": "034", "name": "Bulgaria (Ployvid city)"},
    "BF": {"number": "035", "name": "Burkina Faso"},
    "BI": {"number": "036", "name": "Burundi"},
    "KH": {"number": "037", "name": "Cambodia"},
    "CM": {"number": "038", "name": "Cameroon"},
    "CA": {"number": "039", "name": "Canada"},
    "CV": {"number": "040", "name": "Cape Verde"},
    "KY": {"number": "041", "name": "Cayman Islands"},
    "CF": {"number": "042", "name": "Central African Republic"},
    "TD": {"number": "043", "name": "Chad"},
    "CL": {"number": "044", "name": "Chile"},
    "CN": {"number": "045", "name": "China"},
    "CX": {"number": "046", "name": "Christmas Island"},
    "CC": {"number": "047", "name": "Cocos (Keeling) Islands"},
    "CO": {"number": "048", "name": "Colombia"},
    "KM": {"number": "049", "name": "Comoros"},
    "CG": {"number": "050", "name": "Congo"},
    "CD": {"number": "051", "name": "Congo (Democratic Republic)"},
    "CK": {"number": "052", "name": "Cook Islands"},
    "CR": {"number": "053", "name": "Costa Rica"},
    "HR": {"number": "054", "name": "Croatia"},
    "CU": {"number": "055", "name": "Cuba"},
    "CW": {"number": "056", "name": "Curaçao"},
    "CY": {"number": "057", "name": "Cyprus"},
    "CZ": {"number": "058", "name": "Czech Republic"},
    "DK": {"number": "059", "name": "Denmark"},
    "DJ": {"number": "060", "name": "Djibouti"},
    "DM": {"number": "061", "name": "Dominica"},
    "DO": {"number": "062", "name": "Dominican Republic"},
    "EC": {"number": "063", "name": "Ecuador"},
    "EG": {"number": "064", "name": "Egypt"},
    "SV": {"number": "065", "name": "El Salvador"},
    "GQ": {"number": "066", "name": "Equatorial Guinea"},
    "ER": {"number": "067", "name": "Eritrea"},
    "EE": {"number": "068", "name": "Estonia"},
    "ET": {"number": "069", "name": "Ethiopia"},
    "FK": {"number": "070", "name": "Falkland Islands"},
    "FO": {"number": "071", "name": "Faroe Islands"},
    "FJ": {"number": "072", "name": "Fiji"},
    "FI": {"number": "073", "name": "Finland"},
    "FR": {"number": "074", "name": "France"},
    "GF": {"number": "075", "name": "French Guiana"},
    "PF": {"number": "076", "name": "French Polynesia"},
    "TF": {"number": "077", "name": "French Southern Territories"},
    "GA": {"number": "078", "name": "Gabon"},
    "GM": {"number": "079", "name": "Gambia"},
    "GE": {"number": "080", "name": "Georgia"},
    "DE": {"number": "081", "name": "Germany"},
    "GH": {"number": "082", "name": "Ghana"},
    "GI": {"number": "083", "name": "Gibraltar"},
    "GR": {"number": "084", "name": "Greece"},
    "GL": {"number": "085", "name": "Greenland"},
    "GD": {"number": "086", "name": "Grenada"},
    "GP": {"number": "087", "name": "Guadeloupe"},
    "GU": {"number": "088", "name": "Guam"},
    "GT": {"number": "089", "name": "Guatemala"},
    "GG": {"number": "090", "name": "Guernsey"},
    "GN": {"number": "091", "name": "Guinea"},
    "GW": {"number": "092", "name": "Guinea-Bissau"},
    "GY": {"number": "093", "name": "Guyana"},
    "HT": {"number": "094", "name": "Haiti"},
    "HN": {"number": "095", "name": "Honduras"},
    "HK": {"number": "096", "name": "Hong Kong"},
    "HU": {"number": "097", "name": "Hungary"},
    "IS": {"number": "098", "name": "Iceland"},
    "IN": {"number": "099", "name": "India"},
    "ID": {"number": "100", "name": "Indonesia"},
    "IR": {"number": "101", "name": "Iran"},
    "IQ": {"number": "102", "name": "Iraq"},
    "IE": {"number": "103", "name": "Ireland"},
    "EI": {"number": "103", "name": "Ireland"}, #Dublin is in Ireland
    "IM": {"number": "104", "name": "Isle of Man"},
    "IL": {"number": "105", "name": "Israel"},
    "IT": {"number": "106", "name": "Italy"},
    "CI": {"number": "107", "name": "Ivory Coast"},
    "JM": {"number": "108", "name": "Jamaica"},
    "JP": {"number": "109", "name": "Japan"},
    "JE": {"number": "110", "name": "Jersey"},
    "JO": {"number": "111", "name": "Jordan"},
    "KZ": {"number": "112", "name": "Kazakhstan"},
    "KE": {"number": "113", "name": "Kenya"},
    "KI": {"number": "114", "name": "Kiribati"},
    "KP": {"number": "115", "name": "North Korea"},
    "KR": {"number": "116", "name": "South Korea"},
    "KW": {"number": "117", "name": "Kuwait"},
    "KG": {"number": "118", "name": "Kyrgyzstan"},
    "LA": {"number": "119", "name": "Laos"},
    "LV": {"number": "120", "name": "Latvia"},
    "LB": {"number": "121", "name": "Lebanon"},
    "LE": {"number": "121", "name": "Lebanon"}, # Beirut is in Lebanon
    "LS": {"number": "122", "name": "Lesotho"},
    "LR": {"number": "123", "name": "Liberia"},
    "LY": {"number": "124", "name": "Libya"},
    "LI": {"number": "125", "name": "Liechtenstein"},
    "LT": {"number": "126", "name": "Lithuania"},
    "LU": {"number": "127", "name": "Luxembourg"},
    "MO": {"number": "128", "name": "Macao"},
    "MK": {"number": "129", "name": "North Macedonia"},
    "MG": {"number": "130", "name": "Madagascar"},
    "MW": {"number": "131", "name": "Malawi"},
    "MY": {"number": "132", "name": "Malaysia"},
    "MV": {"number": "133", "name": "Maldives"},
    "ML": {"number": "134", "name": "Mali"},
    "MT": {"number": "135", "name": "Malta"},
    "MH": {"number": "136", "name": "Marshall Islands"},
    "MQ": {"number": "137", "name": "Martinique"},
    "MR": {"number": "138", "name": "Mauritania"},
    "MU": {"number": "139", "name": "Mauritius"},
    "YT": {"number": "140", "name": "Mayotte"},
    "MX": {"number": "141", "name": "Mexico"},
    "FM": {"number": "142", "name": "Micronesia"},
    "MD": {"number": "143", "name": "Moldova"},
    "MC": {"number": "144", "name": "Monaco"},
    "MN": {"number": "145", "name": "Mongolia"},
    "ME": {"number": "146", "name": "Montenegro"},
    "MS": {"number": "147", "name": "Montserrat"},
    "MA": {"number": "148", "name": "Morocco"},
    "MZ": {"number": "149", "name": "Mozambique"},
    "MM": {"number": "150", "name": "Myanmar"},
    "NA": {"number": "151", "name": "Namibia"},
    "NR": {"number": "152", "name": "Nauru"},
    "NP": {"number": "153", "name": "Nepal"},
    "NL": {"number": "154", "name": "Netherlands"},
    "NC": {"number": "155", "name": "New Caledonia"},
    "NZ": {"number": "156", "name": "New Zealand"},
    "NI": {"number": "157", "name": "Nicaragua"},
    "NE": {"number": "158", "name": "Niger"},
    "NG": {"number": "159", "name": "Nigeria"},
    "NU": {"number": "160", "name": "Niue"},
    "NF": {"number": "161", "name": "Norfolk Island"},
    "MP": {"number": "162", "name": "Northern Mariana Islands"},
    "NO": {"number": "163", "name": "Norway"},
    "OM": {"number": "164", "name": "Oman"},
    "PK": {"number": "165", "name": "Pakistan"},
    "PW": {"number": "166", "name": "Palau"},
    "PS": {"number": "167", "name": "Palestine"},
    "PA": {"number": "168", "name": "Panama"},
    "PG": {"number": "169", "name": "Papua New Guinea"},
    "PY": {"number": "170", "name": "Paraguay"},
    "PE": {"number": "171", "name": "Peru"},
    "PH": {"number": "172", "name": "Philippines"},
    "PN": {"number": "173", "name": "Pitcairn"},
    "PL": {"number": "174", "name": "Poland"},
    "PT": {"number": "175", "name": "Portugal"},
    "PO": {"number": "175", "name": "Portugal"},
    "PR": {"number": "176", "name": "Puerto Rico"},
    "RQ": {"number": "176", "name": "Puerto Rico"}, # ?
    "QA": {"number": "177", "name": "Qatar"},
    "RE": {"number": "178", "name": "Réunion"},
    "RO": {"number": "179", "name": "Romania"},
    "RU": {"number": "180", "name": "Russia"},
    "RW": {"number": "181", "name": "Rwanda"},
    "BL": {"number": "182", "name": "Saint Barthélemy"},
    "SH": {"number": "183", "name": "Saint Helena"},
    "KN": {"number": "184", "name": "Saint Kitts and Nevis"},
    "LC": {"number": "185", "name": "Saint Lucia"},
    "MF": {"number": "186", "name": "Saint Martin"},
    "PM": {"number": "187", "name": "Saint Pierre and Miquelon"},
    "VC": {"number": "188", "name": "Saint Vincent and the Grenadines"},
    "WS": {"number": "189", "name": "Samoa"},
    "SM": {"number": "190", "name": "San Marino"},
    "ST": {"number": "191", "name": "São Tomé and Príncipe"},
    "SA": {"number": "192", "name": "Saudi Arabia"},
    "SN": {"number": "193", "name": "Senegal"},
    "RS": {"number": "194", "name": "Serbia"},
    "SC": {"number": "195", "name": "Seychelles"},
    "SL": {"number": "196", "name": "Sierra Leone"},
    "SG": {"number": "197", "name": "Singapore"},
    "SX": {"number": "198", "name": "Sint Maarten"},
    "SK": {"number": "199", "name": "Slovakia"},
    "SI": {"number": "200", "name": "Slovenia"},
    "SB": {"number": "201", "name": "Solomon Islands"},
    "SO": {"number": "202", "name": "Somalia"},
    "ZA": {"number": "203", "name": "South Africa"},
    "GS": {"number": "204", "name": "South Georgia"},
    "SS": {"number": "205", "name": "South Sudan"},
    "ES": {"number": "206", "name": "Spain"},
    "LK": {"number": "207", "name": "Sri Lanka"},
    "SD": {"number": "208", "name": "Sudan"},
    "SR": {"number": "209", "name": "Suriname"},
    "SJ": {"number": "210", "name": "Svalbard and Jan Mayen"},
    "SZ": {"number": "211", "name": "Eswatini"},
    "SE": {"number": "212", "name": "Sweden"},
    "CH": {"number": "213", "name": "Switzerland"},
    "SY": {"number": "214", "name": "Syria"},
    "TW": {"number": "215", "name": "Taiwan"},
    "TJ": {"number": "216", "name": "Tajikistan"},
    "TZ": {"number": "217", "name": "Tanzania"},
    "TH": {"number": "218", "name": "Thailand"},
    "TL": {"number": "219", "name": "Timor-Leste"},
    "TG": {"number": "220", "name": "Togo"},
    "TK": {"number": "221", "name": "Tokelau"},
    "TO": {"number": "222", "name": "Tonga"},
    "TT": {"number": "223", "name": "Trinidad and Tobago"},
    "TN": {"number": "224", "name": "Tunisia"},
    "TR": {"number": "225", "name": "Turkey"},
    "TM": {"number": "226", "name": "Turkmenistan"},
    "TC": {"number": "227", "name": "Turks and Caicos Islands"},
    "TV": {"number": "228", "name": "Tuvalu"},
    "UG": {"number": "229", "name": "Uganda"},
    "UA": {"number": "230", "name": "Ukraine"},
    "AE": {"number": "231", "name": "United Arab Emirates"},
    "GB": {"number": "232", "name": "United Kingdom"},
    "UK": {"number": "232", "name": "United Kingdom-as UK"},
    "EN": {"number": "232", "name": "United Kingdom-as EN"},
    "WL": {"number": "232", "name": "United Kingdom-as Wales"},
    "SC": {"number": "232", "name": "United Kingdom-as Scotland"},
    "NI": {"number": "232", "name": "United Kingdom-as Northern Ireland"},
    "US": {"number": "233", "name": "United States"},
    "UM": {"number": "234", "name": "United States Minor Outlying Islands"},
    "UY": {"number": "235", "name": "Uruguay"},
    "UZ": {"number": "236", "name": "Uzbekistan"},
    "VU": {"number": "237", "name": "Vanuatu"},
    "VE": {"number": "238", "name": "Venezuela"},
    "VN": {"number": "239", "name": "Vietnam"},
    "VI": {"number": "240", "name": "Virgin Islands (U.S.)"},
    "WF": {"number": "241", "name": "Wallis and Futuna"},
    "EH": {"number": "242", "name": "Western Sahara"},
    "YE": {"number": "243", "name": "Yemen"},
    "ZM": {"number": "244", "name": "Zambia"},
    "ZW": {"number": "245", "name": "Zimbabwe"},
    "ZI": {"number": "245", "name": "Zimbabwe"}, # FIPS code for Zimbabwe
    "AX": {"number": "246", "name": "Åland Islands"},
    "BQ": {"number": "247", "name": "Bonaire, Sint Eustatius and Saba"},
    "SS": {"number": "248", "name": "South Sudan"},
    "XK": {"number": "249", "name": "Kosovo"},
    # Continents / regions for vague foreign reporting (e.g. IRI-style grants by continent or portion)
    # Use high numbers (900+) so they stand out as synthetics. Simple "AFRICA" etc. matches are fine per user.
    "AFRICA": {"number": "900", "name": "Africa (vague/continent or sub-region)"},
    "SUB-SAHARAN AFRICA": {"number": "900", "name": "Sub-Saharan Africa"},
    "ASIA": {"number": "901", "name": "Asia (vague/continent or sub-region)"},
    "EUROPE": {"number": "902", "name": "Europe (vague/continent or sub-region)"},
    "LATIN AMERICA": {"number": "903", "name": "Latin America (vague/continent or sub-region)"},
    "CARIBBEAN": {"number": "904", "name": "Caribbean (vague/region)"},
    "MIDDLE EAST": {"number": "905", "name": "Middle East (vague/region)"},
    "ZZ": {"number": "999", "name": "Unknown Country Code"},
    "OC": {"number": "999", "name": "Unknown Country Code-2"},
    "PC": {"number": "999", "name": "Unknown Country Code-2"},
}

# Dictionary mapping FIPS 10-4 country codes to ISO 3166-1 alpha-2 codes
# Excludes entries where FIPS code is identical to ISO code
# Data sourced from various references including FIPS 10-4 and ISO 3166 standards
FIPS_TO_ISO = {
    "AA": "AW",  # Aruba
    "AC": "AG",  # Antigua and Barbuda
    "AG": "DZ",  # Algeria
    "AJ": "AZ",  # Azerbaijan
    "AN": "AD",  # Andorra
    "AV": "AO",  # Angola
    "AY": "AQ",  # Antarctica
    "BA": "BH",  # Bahrain
    "BB": "BD",  # Barbados
    "BC": "BW",  # Botswana
    "BF": "BS",  # Bahamas, The
    "BH": "BZ",  # Belize
    "BK": "BA",  # Bosnia and Herzegovina
    "BL": "BO",  # Bolivia
    "BN": "BJ",  # Benin
    "BP": "SB",  # Solomon Islands
    "BU": "BG",  # Bulgaria
    "BX": "BN",  # Brunei
    "CB": "KH",  # Cambodia
    "CD": "TD",  # Chad
    "CE": "LK",  # Sri Lanka
    "CF": "CG",  # Congo (Brazzaville)
    "CH": "CN",  # China
    "CJ": "KY",  # Cayman Islands
    "CM": "KM",  # Comoros
    "CN": "CK",  # Cook Islands
    "CS": "CR",  # Costa Rica
    "CT": "CF",  # Central African Republic
    "CV": "CV",  # Cape Verde
    "DA": "DK",  # Denmark
    "DJ": "DJ",  # Djibouti
    "DO": "DM",  # Dominica
    "DR": "DO",  # Dominican Republic
    "EC": "EC",  # Ecuador
    "EG": "EG",  # Egypt
    "EI": "IE",  # Ireland
    "EK": "GQ",  # Equatorial Guinea
    "EN": "EE",  # Estonia
    "ER": "ER",  # Eritrea
    "ET": "ET",  # Ethiopia
    "EZ": "CZ",  # Czechia
    "FG": "GF",  # French Guiana
    "FJ": "FJ",  # Fiji
    "FM": "FM",  # Micronesia, Federated States of
    "FP": "PF",  # French Polynesia
    "FR": "FR",  # France
    "FS": "TF",  # French Southern Territories
    "GA": "GM",  # Gambia, The
    "GB": "GA",  # Gabon
    "GG": "GE",  # Georgia
    "GH": "GH",  # Ghana
    "GJ": "GD",  # Grenada
    "GK": "GG",  # Guernsey
    "GL": "GL",  # Greenland
    "GM": "DE",  # Germany
    "GP": "GP",  # Guadeloupe
    "GR": "GR",  # Greece
    "GT": "GT",  # Guatemala
    "GV": "GN",  # Guinea
    "GY": "GY",  # Guyana
    "HA": "HT",  # Haiti
    "HK": "HK",  # Hong Kong
    "HO": "HN",  # Honduras
    "HR": "HR",  # Croatia
    "HU": "HU",  # Hungary
    "IC": "IS",  # Iceland
    "IM": "IM",  # Isle of Man
    "IN": "IN",  # India
    "IO": "IO",  # British Indian Ocean Territory
    "IR": "IR",  # Iran
    "IS": "IL",  # Israel
    "IV": "CI",  # Côte d'Ivoire
    "IZ": "IQ",  # Iraq
    "JA": "JP",  # Japan
    "JE": "JE",  # Jersey
    "JM": "JM",  # Jamaica
    "JN": "SJ",  # Svalbard and Jan Mayen
    "JO": "JO",  # Jordan
    "KE": "KE",  # Kenya
    "KG": "KG",  # Kyrgyzstan
    "KN": "KP",  # Korea, North
    "KR": "KI",  # Kiribati
    "KS": "KR",  # Korea, South
    "KT": "CX",  # Christmas Island
    "KU": "KW",  # Kuwait
    "KZ": "KZ",  # Kazakhstan
    "LA": "LA",  # Laos
    "LE": "LB",  # Lebanon
    "LG": "LV",  # Latvia
    "LH": "LT",  # Lithuania
    "LI": "LR",  # Liberia
    "LO": "SK",  # Slovakia
    "LS": "LS",  # Lesotho
    "LT": "LY",  # Libya
    "LU": "LU",  # Luxembourg
    "LY": "LI",  # Liechtenstein
    "MA": "MG",  # Madagascar
    "MB": "MQ",  # Martinique
    "MC": "MC",  # Monaco
    "MD": "MD",  # Moldova
    "MF": "YT",  # Mayotte
    "MG": "MN",  # Mongolia
    "MI": "MW",  # Malawi
    "MJ": "ME",  # Montenegro
    "MK": "MK",  # North Macedonia
    "ML": "ML",  # Mali
    "MN": "MO",  # Macao
    "MO": "MA",  # Morocco
    "MP": "MP",  # Northern Mariana Islands
    "MQ": "MZ",  # Mozambique
    "MR": "MR",  # Mauritania
    "MT": "MT",  # Malta
    "MU": "MU",  # Mauritius
    "MV": "MV",  # Maldives
    "MW": "MS",  # Montserrat
    "MX": "MX",  # Mexico
    "MY": "MY",  # Malaysia
    "MZ": "MM",  # Myanmar
    "NA": "NA",  # Namibia
    "NC": "NC",  # New Caledonia
    "NE": "NE",  # Niger
    "NF": "NF",  # Norfolk Island
    "NG": "NG",  # Nigeria
    "NH": "VU",  # Vanuatu
    "NI": "NI",  # Nicaragua
    "NL": "NL",  # Netherlands
    "NO": "NO",  # Norway
    "NP": "NP",  # Nepal
    "NR": "NR",  # Nauru
    "NS": "SR",  # Suriname
    "NU": "NU",  # Niue
    "NZ": "NZ",  # New Zealand
    "PA": "PA",  # Panama
    "PE": "PE",  # Peru
    "PK": "PK",  # Pakistan
    "PL": "PL",  # Poland
    "PM": "PM",  # Saint Pierre and Miquelon
    "PN": "PN",  # Pitcairn
    "PO": "PT",  # Portugal
    "PP": "PG",  # Papua New Guinea
    "PS": "PS",  # Palestine, State of
    "PU": "GW",  # Guinea-Bissau
    "QA": "QA",  # Qatar
    "RE": "RE",  # Réunion
    "RI": "RS",  # Serbia
    "RM": "MH",  # Marshall Islands
    "RN": "NE",  # Niger (duplicate entry in some sources)
    "RO": "RO",  # Romania
    "RP": "PH",  # Philippines
    "RQ": "PR",  # Puerto Rico
    "RS": "RU",  # Russia
    "RW": "RW",  # Rwanda
    "SA": "SA",  # Saudi Arabia
    "SB": "PM",  # Saint Pierre and Miquelon (duplicate entry)
    "SC": "SC",  # Seychelles
    "SF": "ZA",  # South Africa
    "SG": "SG",  # Singapore
    "SH": "SH",  # Saint Helena, Ascension and Tristan da Cunha
    "SI": "SI",  # Slovenia
    "SL": "SL",  # Sierra Leone
    "SM": "SM",  # San Marino
    "SN": "SN",  # Senegal
    "SO": "SO",  # Somalia
    "SP": "ES",  # Spain
    "SR": "LC",  # Saint Lucia
    "ST": "ST",  # Sao Tome and Principe
    "SU": "SD",  # Sudan
    "SV": "SV",  # El Salvador
    "SW": "SE",  # Sweden
    "SX": "GS",  # South Georgia and the South Sandwich Islands
    "SY": "SY",  # Syria
    "SZ": "CH",  # Switzerland
    "TB": "BL",  # Saint Barthélemy
    "TC": "TC",  # Turks and Caicos Islands
    "TD": "TT",  # Trinidad and Tobago
    "TH": "TH",  # Thailand
    "TI": "TJ",  # Tajikistan
    "TK": "TK",  # Tokelau
    "TL": "TM",  # Turkmenistan
    "TN": "TN",  # Tunisia
    "TO": "TO",  # Tonga
    "TS": "AE",  # United Arab Emirates
    "TU": "TR",  # Turkey
    "TV": "TV",  # Tuvalu
    "TW": "TW",  # Taiwan
    "TX": "TM",  # Turkmenistan (duplicate entry)
    "TZ": "TZ",  # Tanzania
    "UG": "UG",  # Uganda
    "UK": "GB",  # United Kingdom
    "UP": "UA",  # Ukraine
    "US": "US",  # United States
    "UV": "BF",  # Burkina Faso
    "UY": "UY",  # Uruguay
    "UZ": "UZ",  # Uzbekistan
    "VC": "VC",  # Saint Vincent and the Grenadines
    "VE": "VE",  # Venezuela
    "VI": "VG",  # Virgin Islands, British
    "VM": "VN",  # Vietnam
    "VQ": "VI",  # Virgin Islands, U.S.
    "VT": "VA",  # Holy See (Vatican City)
    "WA": "EH",  # Western Sahara
    "WF": "WF",  # Wallis and Futuna
    "WI": "WI",  # Western Sahara (duplicate entry)
    "WS": "WS",  # Samoa
    "WZ": "SZ",  # Eswatini
    "YM": "YE",  # Yemen
    "ZA": "ZM",  # Zambia
    "ZI": "ZW",  # Zimbabwe
}

def lookupCC(code):
    if code in iso3166_alpha2:
        return iso3166_alpha2[code]
    else:
        if code in FIPS_TO_ISO:
            return iso3166_alpha2[FIPS_TO_ISO[code]]
    return None


# --- Foreign synthetic EIN support (for named foreign orgs in no-EIN grantee text) ---
# These get fake "99-NNN0000" style EINs (consistent with other 99- synthetics like 99-7777777)
# so they can be rolled up for visualization, totals by country/region, fraud detection, etc.
# instead of staying as unmatchable hard no-EIN or wasting Grok calls.
# Detection is heuristic (keywords + country name mentions); not perfect but targets the
# common cases like STICHTING (NL), IMPERIAL COLLEGE / OXFORD (GB), AGENCE (FR), MINISTRY OF ... NIGERIA (NG),
# PTY/GMBH foreign, etc. Vague continent reports (e.g. from orgs like International Republican Institute)
# can map to "ZZ" / 999.

FOREIGN_TRIGGERS = [
    (re.compile(r"\bSTICHTING\b", re.IGNORECASE), "NL"),
    (re.compile(r"\bIMPERIAL COLLEGE\b", re.IGNORECASE), "GB"),
    (re.compile(r"\bUNIVERSITY OF OXFORD\b", re.IGNORECASE), "GB"),
    (re.compile(r"\bAGENCE FRANCAISE\b", re.IGNORECASE), "FR"),
    (re.compile(r"FEDERAL MINISTRY.*NIGERIA|NIGERIA.*MINISTRY OF HEALTH", re.IGNORECASE), "NG"),
    (re.compile(r"\bWITS\b.*(PTY|HEALTH|CONSORTIUM)", re.IGNORECASE), "ZA"),
    (re.compile(r"\(PTY\)\s*LTD|PTY\s*LTD", re.IGNORECASE), "ZA"),
    (re.compile(r"\bHELMHOLTZ\b", re.IGNORECASE), "DE"),
    (re.compile(r"\bGMBH\b", re.IGNORECASE), "DE"),
    (re.compile(r"\bISLAMIC DEVELOPMENT BANK\b", re.IGNORECASE), "SA"),
    (re.compile(r"\bAGA KHAN\b", re.IGNORECASE), "PK"),
    (re.compile(r"\bTARA CLIMATE\b", re.IGNORECASE), "GB"),  # or other; often UK registered
    (re.compile(r"\bKAROLINSKA\b", re.IGNORECASE), "SE"),
    (re.compile(r"\bUNIVERSITE DE MONTREAL\b", re.IGNORECASE), "CA"),
    (re.compile(r"\bAUSVET\b", re.IGNORECASE), "AU"),
    # Expanded from 1M/ by_dollars hard review (foreign unis, stiftungen, associations, bureaus, corporacions)
    (re.compile(r"\bUNIVERSITAET\b", re.IGNORECASE), "DE"),  # or AT for Vienna etc.
    (re.compile(r"\bKATHOLIEKE UNIVERSITEIT\b", re.IGNORECASE), "BE"),
    (re.compile(r"\bSTIFTELSEN\b", re.IGNORECASE), "NO"),  # Norwegian foundation
    (re.compile(r"\bSTOWARZYSZENIE\b", re.IGNORECASE), "PL"),  # Polish association
    (re.compile(r"\bCORPORACION\b.*(AFRO|COLOMBIANA|PASTORAL)", re.IGNORECASE), "CO"),
    (re.compile(r"\bTIGRAY\b.*(HEALTH|BUREAU|REGIONAL)", re.IGNORECASE), "ET"),
    (re.compile(r"\bAMHARA\b.*(HEALTH|BUREAU|REGIONAL)", re.IGNORECASE), "ET"),
    (re.compile(r"\b(OROMIA|SIDAMA|AFAR|SOMALI)\s+REGIONAL\s+HEALTH\s+BUREAU\b", re.IGNORECASE), "ET"),
    (re.compile(r"\bFRIEDRICH-ALEXANDER\b", re.IGNORECASE), "DE"),
    (re.compile(r"\bFLYKTNINGHJELPEN\b", re.IGNORECASE), "NO"),
    (re.compile(r"\bREGIONAL HEALTH BUREAU\b", re.IGNORECASE), "ZZ"),  # generic foreign bureau
    (re.compile(r"\bOTWARTE KLATKI\b", re.IGNORECASE), "PL"),
    # Add more as seen in hards / grants. Vague foreign: map to continent/region keys (simple "AFRICA" match ok)
    (re.compile(r"\b(SUB[-\s]?SAHARAN\s+)?AFRICA\b", re.IGNORECASE), "AFRICA"),
    (re.compile(r"\bLATIN\s+AMERICA\b", re.IGNORECASE), "LATIN AMERICA"),
    (re.compile(r"\bMIDDLE\s+EAST\b", re.IGNORECASE), "MIDDLE EAST"),
    (re.compile(r"\bASIA\b", re.IGNORECASE), "ASIA"),
    (re.compile(r"\bEUROPE\b", re.IGNORECASE), "EUROPE"),
    (re.compile(r"\bCARIBBEAN\b", re.IGNORECASE), "CARIBBEAN"),
    (re.compile(r"\bVARIOUS\s+(COUNTRIES|CONTINENTS|REGIONS)\b", re.IGNORECASE), "ZZ"),
]


def detect_foreign_country(name: str) -> Optional[str]:
    """Return ISO alpha2 (or ZZ for unknown/vague) if name looks like a foreign org reference.
    Uses triggers + country name mentions from the iso list. Skips US.
    """
    if not name:
        return None
    upper = name.upper()
    for pat, cc in FOREIGN_TRIGGERS:
        if pat.search(name):
            return cc
    # Fallback: explicit country name in the grantee text (e.g. "... Nigeria", "... London") -- word bounded to avoid "INDIA" in "INDIANA..."
    for cc, info in iso3166_alpha2.items():
        cname = info.get("name", "").upper()
        if cname and cc not in ("US", "United States"):
            if len(cname) > 5 or cname in ("NIGERIA", "FRANCE", "GERMANY", "KENYA", "INDIA", "CHINA", "BRAZIL", "MEXICO", "ISRAEL", "JAPAN", "KOREA", "EGYPT", "GHANA", "KENYA"):
                # word boundary check
                if re.search(r"\b" + re.escape(cname) + r"\b", upper):
                    return cc
    # Common non-US english speaking or obvious
    if re.search(r"\b(LONDON|PARIS|GENEVA|AMSTERDAM|TORONTO|SYDNEY|JOHANNESBURG)\b", upper):
        # rough city -> country; improve later with city db if needed
        if "LONDON" in upper: return "GB"
        if "PARIS" in upper: return "FR"
        if "AMSTERDAM" in upper: return "NL"
        if "JOHANNESBURG" in upper or "CAPE TOWN" in upper: return "ZA"
        if "TORONTO" in upper: return "CA"
        if "SYDNEY" in upper: return "AU"
    return None

def get_synthetic_foreign_ein(name: str) -> Optional[str]:
    """Return literally just the 3-digit country/region number from countryCodes (no 99-, no dash).
    E.g. "232" for UK, "900" for Africa/vague, "154" for NL.
    These are intentionally the bare 3-digit codes for foreign rollups/synthetics in hard cases.
    (We don't use the - or 99- prefix in the data for these.)
    """
    cc = detect_foreign_country(name)
    if not cc:
        return None
    info = lookupCC(cc)
    if info:
        num = info.get("number", "999")
        return num  # literally just the 3 digits, e.g. 232
    return "999"
