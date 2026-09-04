#!/bin/sh

# IRS 990 Data Processor - Unified Pipeline
# This script runs the new unified 990processor.py instead of individual scripts

export ZIPS_DIR="/Volumes/Data/irs_zips"
export OUT_DIR="/Volumes/Data/tsvs"
export ANAL_DIR="/Volumes/Data/atsvs"
export FINAL_DIR="/Volumes/Data/final"
export DR_ROOT="$HOME/Development/datarepublican"
export TOOLS=$DR_ROOT/990tools
export BROWSE=$DR_ROOT/browse

cd $TOOLS

# Install dependencies if needed
echo "Installing dependencies..."
pip install censusgeocode lxml nameparser tqdm psutil

# Step 1: Download ZIP files from IRS website (if not already downloaded)
echo "Step 1: Downloading ZIP files..."
python download_IRS_990_zips.py 2017 2025 --dest $ZIPS_DIR

# Step 2: Recompress any problematic ZIP files
echo "Step 2: Recompressing ZIP files..."
cd $ZIPS_DIR
python $TOOLS/recompress_irs_zips.py
cd $TOOLS

# Step 3: Process ZIP files and register XML contents
echo "Step 3: Processing ZIP files..."
python 990processor.py 2017 2025 --step zip --verbose

# Step 4: Parse XML files and extract data to database
echo "Step 4: Parsing XML files..."
python 990processor.py 2017 2025 --step xml --verbose

# Step 5: Geocode addresses for fraud detection
echo "Step 5: Geocoding addresses..."
python 990processor.py 2017 2025 --step geolocate --verbose

# Step 6: Match grants to recipients by EIN or address
echo "Step 6: Matching grants to recipients..."
python 990processor.py 2017 2025 --step match --verbose

# Step 7: Calculate percentile rankings
echo "Step 7: Calculating percentiles..."
python 990processor.py 2017 2025 --step percentiles --verbose

# Step 8: Export final TSV files
echo "Step 8: Exporting final TSV files..."
python 990processor.py 2017 2025 --step export --verbose

# Step 9: Generate reports (optional legacy step)
echo "Step 9: Generating reports..."
if [ -f "$FINAL_DIR/grants_latest.tsv" ]; then
    ./grant_report.py --input-file $FINAL_DIR/grants_latest.tsv --report-file $FINAL_DIR/final_report.md
fi

# Step 10: Move files to browse directory
echo "Step 10: Moving files to browse directory..."
cp $FINAL_DIR/charities_latest.tsv $BROWSE/charities.tsv
cp $FINAL_DIR/grants_latest.tsv $BROWSE/grants_final.tsv
cp $FINAL_DIR/contractors_latest.tsv $BROWSE/ 2>/dev/null || true
cp $FINAL_DIR/political_contributions_latest.tsv $BROWSE/ 2>/dev/null || true

# Step 11: Split TSVs for web interface
echo "Step 11: Splitting TSVs for web interface..."
pushd $BROWSE
rm -rf tsv_chunks
$TOOLS/split_tsvs.sh
popd

echo "Processing complete! Files available in:"
echo "- Charities: $FINAL_DIR/charities_latest.tsv"
echo "- Grants: $FINAL_DIR/grants_latest.tsv"
echo "- Contractors: $FINAL_DIR/contractors_latest.tsv"
echo "- Political Contributions: $FINAL_DIR/political_contributions_latest.tsv"
echo "- Database: $TOOLS/irs990.db"
echo "- Web interface: $BROWSE/"



 
