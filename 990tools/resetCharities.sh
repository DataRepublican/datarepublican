#!/bin/sh
duckdb /Volumes/Data/final/irs990.duckdb -c "Update XmlFiles set processed=true where processed=false and filename in (select xml_name from Charities)"