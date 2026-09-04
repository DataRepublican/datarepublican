#!/usr/bin/env python3
"""generate_foreign_update.py - Generate SQL for foreign EIN updates from countryCodes.py"""

# Path to countryCodes.py (adjust if needed)
from sys import path
# Reverse FIPS to ISO for lookup (multiple FIPS can map to one ISO)
from countryCodes import FIPS_TO_ISO,iso3166_alpha2
iso_to_fips = {}
for fips, iso in FIPS_TO_ISO.items():
    if iso not in iso_to_fips:
        iso_to_fips[iso] = []
    iso_to_fips[iso].append(fips)

for fips, iso in FIPS_TO_ISO.items():
    if iso not in iso_to_fips:
        iso_to_fips[iso] = []
    iso_to_fips[iso].append(fips)

def generate_sql():
    sql_lines = []
    for iso, data in iso3166_alpha2.items():
        ein = data["number"]
        conditions = [f"colocator = 'FA:{iso}'"]
        if iso in iso_to_fips:
            for fips in iso_to_fips[iso]:
                conditions.append(f"colocator = 'FA:{fips}'")
        where = ' OR '.join(conditions)
        sql_lines.append(f"UPDATE Grants SET recipient_ein = '{ein}' WHERE {where};")
    return '\n'.join(sql_lines)

sql = generate_sql()

with open('foreign_ein_update.sql', 'w') as f:
    f.write(sql)

print("Generated foreign_ein_update.sql with " + str(len(iso3166_alpha2)) + " updates.")