import duckdb
import urllib.request
import pathlib
import logging
import subprocess
import shutil
from typing import Dict, List, Tuple

# ====================== CONFIG ======================
DATA_DIR = pathlib.Path("fec_bulk_data")
DB_PATH = "fec.duckdb"
BASE_URL = "https://www.fec.gov/files/bulk-downloads/"

CYCLES = [str(y) for y in range(2000, 2028, 2)]   # your range — safe now

# (header_base, zip_prefix, expected_fields, master_table, min_cycle)
FILE_TYPES: List[Tuple] = [
    ("cm",     "cm",     31, "committees",             1978),
    ("indiv",  "indiv",  24, "individuals",            1980),
    ("oth",    "oth",    20, "committee_transactions", 1980),
    ("pas2",   "pas2",   22, "pas2",                   1980),
    ("oppexp", "oppexp", 23, "oppexp",                 2004),   # first available
]

FILES_TO_LOAD: List[Dict] = []
for c in CYCLES:
    yy = c[2:]
    for header_base, zip_prefix, exp_fields, master_table, min_cycle in FILE_TYPES:
        if int(c) < min_cycle:
            continue
        FILES_TO_LOAD.append({
            "cycle": int(c),
            "zip_name": f"{zip_prefix}{yy}.zip",
            "master_table": master_table,
            "expected_fields": exp_fields,
            "header_base": header_base,
            "min_cycle": min_cycle,
        })

DATA_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
conn = duckdb.connect(DB_PATH)

def get_fec_header(header_base: str) -> str:
    url = f"https://www.fec.gov/files/bulk-downloads/data_dictionaries/{header_base}_header_file.csv"
    try:
        with urllib.request.urlopen(url) as resp:
            data = resp.read().decode("utf-8").strip()
            fields = [f.strip() for f in data.split(",") if f.strip()]
            return "|".join(fields)
    except Exception:
        return ""

def download_and_extract(file_config: Dict) -> pathlib.Path | None:
    zip_url = f"{BASE_URL}{file_config['cycle']}/{file_config['zip_name']}"
    zip_path = DATA_DIR / file_config["zip_name"]

    # Download (wget with resume)
    if not zip_path.exists():
        try:
            logging.info(f"Downloading {file_config['zip_name']}")
            subprocess.check_call(["wget", "-c", "--quiet", "--show-progress", "--progress=bar:force", zip_url, "-O", str(zip_path)])
            logging.info(f"Downloaded {file_config['zip_name']}")
        except subprocess.CalledProcessError:
            logging.warning(f"File {file_config['zip_name']} not available for cycle {file_config['cycle']} — skipping")
            return None

    # Auto-detect main txt file
    result = subprocess.run(["unzip", "-l", str(zip_path)], capture_output=True, text=True)
    main_txt = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith(".txt") and "by_date/" not in line:
            main_txt = line.split()[-1]
            break

    if not main_txt:
        logging.warning(f"No main .txt found in {file_config['zip_name']} — skipping")
        return None

    file_config["txt_name"] = main_txt
    txt_path = DATA_DIR / main_txt

    if txt_path.exists():
        logging.info(f"Already cached: {main_txt}")
        return txt_path

    try:
        logging.info(f"Extracting {main_txt}...")
        subprocess.check_call(["unzip", "-o", "-qq", str(zip_path), main_txt, "-d", str(DATA_DIR)])
        logging.info(f"Extracted {main_txt}")
        return txt_path
    except subprocess.CalledProcessError:
        logging.warning(f"Could not extract {main_txt} from {file_config['zip_name']} — skipping")
        return None

# fix_dangling_newlines and load_to_master are the same as your last working version (fast prepend for big files, etc.)

def fix_dangling_newlines(txt_path: pathlib.Path, expected_fields: int, header: str) -> pathlib.Path:
    fixed_path = txt_path.with_suffix(".fixed.txt")
    if fixed_path.exists():
        return fixed_path

    file_size_gb = txt_path.stat().st_size / (1024**3)
    if file_size_gb > 2.0:
        logging.info(f"Large file ({file_size_gb:.1f} GB) — fast header prepend")
        with open(fixed_path, "w", encoding="utf-8", newline="\n") as out:
            if header:
                out.write(header + "\n")
            with open(txt_path, "r", encoding="latin1", errors="ignore") as f:
                shutil.copyfileobj(f, out)
        logging.info(f"Fast fixed → {fixed_path.name}")
        return fixed_path

    # small file full fix (unchanged)
    logging.info(f"Fixing newlines for {txt_path.name}")
    with open(txt_path, "r", encoding="latin1", errors="ignore") as f:
        lines = []
        current = ""
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            if not line.strip():
                continue
            fields = line.split("|")
            if len(fields) >= expected_fields or (fields and fields[0].startswith("C00")):
                if current:
                    lines.append(current)
                current = line
            else:
                current += "\\n" + line
        if current:
            lines.append(current)

    with open(fixed_path, "w", encoding="utf-8", newline="\n") as out:
        if header:
            out.write(header + "\n")
        out.write("\n".join(lines))
    logging.info(f"Fixed → {fixed_path.name}")
    return fixed_path

def load_to_master(file_config: Dict, header: str):
    # (your existing load_to_master function — unchanged)
    txt_path = DATA_DIR / file_config["txt_name"]
    fixed_path = fix_dangling_newlines(txt_path, file_config["expected_fields"], header)
    master_table = file_config["master_table"]
    cycle = file_config["cycle"]

    temp_table = f"{master_table}_{cycle}_temp"
    conn.execute(f"CREATE OR REPLACE TABLE {temp_table} AS SELECT * FROM read_csv('{fixed_path}', delim='|', header=True, auto_detect=True, ignore_errors=True, parallel=True)")

    conn.execute(f"CREATE TABLE IF NOT EXISTS {master_table} AS SELECT *, 0 AS report_year FROM {temp_table} LIMIT 0")
    conn.execute(f"DELETE FROM {master_table} WHERE report_year = {cycle}")
    conn.execute(f"INSERT INTO {master_table} SELECT *, {cycle} AS report_year FROM {temp_table}")

    total = conn.execute(f"SELECT COUNT(*) FROM {master_table}").fetchone()[0]
    logging.info(f"Master table {master_table} now has {total:,} rows (cycle {cycle} added)")

# ====================== RUN ======================
if __name__ == "__main__":
    for cfg in FILES_TO_LOAD:
        txt_path = download_and_extract(cfg)
        if txt_path is None:
            continue
        header = get_fec_header(cfg["header_base"])
        load_to_master(cfg, header)

    logging.info("All done. Master tables ready with report_year column.")
    conn.close()