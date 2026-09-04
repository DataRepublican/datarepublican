import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import threading

file_counter_local = threading.local()

def parse_xml_file(file_path, ein_to_year):
    """
    Parse a single XML file and return a list of (filer_ein, filer_name, grant_ein, grant_amt) 
    entries if they match the latest tax year from ein_to_year.
    """
    if not hasattr(file_counter_local, 'value'):
        file_counter_local.value = 0
        file_counter_local.entries = 0
    file_counter_local.value += 1

    # Print some progress every 1000 files
    if (file_counter_local.value % 1000) == 0:
        print("Thread %s processed %s files, %s entries" % (
            threading.get_ident(), 
            file_counter_local.value, 
            file_counter_local.entries
        ))

    # Attempt to parse the XML
    try:
        tree = ET.parse(file_path)
    except ET.ParseError:
        # If the file is malformed or unparseable, skip
        return []

    root = tree.getroot()

    # Extract the TaxYr from ReturnHeader
    tax_year_elem = root.find(".//{http://www.irs.gov/efile}ReturnHeader/{http://www.irs.gov/efile}TaxYr")
    if tax_year_elem is None:
        return []

    current_tax_year = tax_year_elem.text.strip()

    # Extract filer EIN
    filer = root.find(".//{http://www.irs.gov/efile}Filer")
    if filer is None:
        return []
    filer_ein_elem = filer.find("{http://www.irs.gov/efile}EIN")
    filer_name_elem = filer.find("./{http://www.irs.gov/efile}BusinessName/{http://www.irs.gov/efile}BusinessNameLine1Txt")

    filer_ein = filer_ein_elem.text.strip() if filer_ein_elem is not None else ""
    filer_name = filer_name_elem.text.strip() if filer_name_elem is not None else ""

    # If this filer EIN is not in our dictionary, skip
    if filer_ein not in ein_to_year:
        return []

    # If the current tax year doesn't match the year in our dictionary, skip
    if current_tax_year != ein_to_year[filer_ein]:
        return []

    # Check that it's a 501(c)(3)
    c3_elem = root.find(".//{http://www.irs.gov/efile}Organization501c3Ind")
    if c3_elem is None:
        return []
    checked = c3_elem.text.strip().upper()
    if 'X' not in checked:
        return []

    # Find all <RecipientTable> elements
    recipient_tables = root.findall(".//{http://www.irs.gov/efile}RecipientTable")
    results = []

    for recipient in recipient_tables:
        cash_grant_amt_elem = recipient.find("{http://www.irs.gov/efile}CashGrantAmt")
        if cash_grant_amt_elem is None:
            continue
        try:
            from parse_utils import parse_float_field
            grant_amt = int(parse_float_field(cash_grant_amt_elem.text.strip()))
        except (TypeError, ValueError):
            continue
        if grant_amt <= 0:
            continue

        grant_ein_elem = recipient.find("{http://www.irs.gov/efile}RecipientEIN")
        if grant_ein_elem is None or not grant_ein_elem.text:
            continue

        grant_ein = grant_ein_elem.text.strip()
        file_counter_local.entries += 1
        results.append((filer_ein, filer_name, grant_ein, grant_amt))

    return results


def main(ein_to_year, input_dir, output_csv, max_workers=8):
    """
    - Recursively find all .xml files under input_dir.
    - Parse each in parallel with max_workers threads.
    - Aggregate results and write them to output_csv (filer_ein, filer_name, grant_ein, grant_amt).
    """
    # Collect all XML files under input_dir
    xml_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.lower().endswith(".xml"):
                xml_files.append(os.path.join(root, f))

    print(len(xml_files))
    print("Approximately %s files per worker" % (int(len(xml_files)/max_workers) if max_workers else 1))

    all_grants = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(parse_xml_file, fp, ein_to_year): fp for fp in xml_files}
        for future in as_completed(futures):
            file_path = futures[future]
            try:
                results = future.result()
                all_grants.extend(results)
            except Exception as e:
                print(f"Error processing {file_path}: {e}")

    # Write results to CSV
    with open(output_csv, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["filer_ein", "filer_name", "grant_ein", "grant_amt"])
        for row in all_grants:
            writer.writerow(row)


if __name__ == "__main__":
    # 1) Read CSV and build EIN -> tax_year dictionary
    ein_to_latest_year = {}
    csv_file = "charities_by_latest.csv"
    with open(csv_file, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Build the dictionary. We assume filer_ein is unique in this CSV.
            ein = row["filer_ein"].strip()
            tax_year = row["tax_year"].strip()
            ein_to_latest_year[ein] = tax_year

    # 2) Run main
    input_directory = "/Users/xero/charity"
    output_file = "/Users/xero/charity/grants_latest.csv"
    main(ein_to_latest_year, input_directory, output_file, max_workers=8)
