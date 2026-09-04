import requests
from bs4 import BeautifulSoup
import os
import argparse

def download_file(url, dest_folder):
    filename = url.split('/')[-1]
    dest_path = os.path.join(dest_folder, filename)
    if os.path.exists(dest_path):
        print(f"Skipping {filename} - already exists")
        return
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Downloaded {filename}")

def download_990_zips(start_year, end_year, dest_folder):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    base_url = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
    response = requests.get(base_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    for year in range(start_year, end_year + 1):
        year_str = str(year)
        # Find links containing the year and ending in .zip
        zip_links = [a['href'] for a in soup.find_all('a', href=True) 
                     if year_str in a['href'] and a['href'].endswith('.zip') and 'TEOS_XML' in a['href']]
        
        if not zip_links:
            print(f"No ZIP files found for {year}")
            continue

        for link in zip_links:
            full_url = f"https://www.irs.gov{link}" if link.startswith('/') else link
            download_file(full_url, dest_folder)

def valid_year(year):
    try:
        year = int(year)
        if 2015 <= year <= 2025:
            return year
        raise argparse.ArgumentTypeError("Year must be between 2020 and 2025.")
    except ValueError:
        raise argparse.ArgumentTypeError("Year must be an integer.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download IRS 990 ZIP files.")
    parser.add_argument("start_year", type=valid_year, help="Start year (e.g., 2022)")
    parser.add_argument("end_year", type=valid_year, help="End year (e.g., 2024)")
    parser.add_argument("--dest", type=str, default="irs_zips", help="Destination folder (default: irs_zips)")

    args = parser.parse_args()
    if args.start_year > args.end_year:
        raise argparse.ArgumentError(None, "Start year must be less than or equal to end year.")

    download_990_zips(args.start_year, args.end_year, args.dest)