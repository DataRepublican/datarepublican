import os
import zipfile
import glob
import shutil
import subprocess
from pathlib import Path

# Directory to store recompressed ZIPs
OUTPUT_DIR = "recompressed_zips"
# Local temporary directory for extraction
TEMP_DIR = "temp"
# Error log file
ERROR_LOG = "zip_error.log"

def check_tools():
    """Check if required tools (7z, zip) are available."""
    for tool in ["7z", "zip"]:
        if shutil.which(tool) is None:
            raise RuntimeError(f"Error: {tool} is not installed. Install with 'brew install {tool}'.")

def ensure_permissions(base_dir):
    """Ensure output and temp directories and error log are writable."""
    for directory in [OUTPUT_DIR, TEMP_DIR]:
        os.makedirs(os.path.join(base_dir, directory), exist_ok=True)
        if not os.access(os.path.join(base_dir, directory), os.W_OK):
            raise PermissionError(
                f"Error: {directory} is not writable. Fix with 'chmod u+w {directory}' or 'sudo chown $USER {directory}'."
            )
    error_log_path = os.path.join(base_dir, ERROR_LOG)
    try:
        with open(error_log_path, "a") as f:
            pass
    except PermissionError:
        raise PermissionError(
            f"Error: Cannot write to {ERROR_LOG}. Fix permissions in {base_dir}."
        )

def check_compression(zip_file):
    """Check if ZIP file uses unsupported compression methods."""
    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            for file_info in zf.infolist():
                if file_info.compress_type not in (0, 8):  # ZIP_STORED=0, ZIP_DEFLATED=8
                    return True, f"Unsupported compression type {file_info.compress_type} in {file_info.filename}"
        return False, "All files use supported compression (Stored or Deflated)"
    except zipfile.BadZipFile as e:
        return True, f"Malformed ZIP file: {e}"
    except Exception as e:
        return True, f"Error reading ZIP: {e}"

def scan_zips(base_dir):
    """Scan ZIP files and return a list of those needing recompression."""
    zip_files = glob.glob(os.path.join(base_dir, "20*.zip"))
    if not zip_files:
        raise FileNotFoundError("No ZIP files found matching pattern '20*.zip'.")

    print(f"Found {len(zip_files)} ZIP files to check.")
    to_recompress = []
    error_log_path = os.path.join(base_dir, ERROR_LOG)
    with open(error_log_path, "a") as log:
        for zip_file in zip_files:
            print(f"Checking {zip_file}...")
            needs_recompress, reason = check_compression(zip_file)
            if needs_recompress:
                print(f"  {reason}")
                to_recompress.append(zip_file)
            else:
                print(f"  {reason}. Skipping.")
            log.write(f"{zip_file}: {reason}\n")

    return to_recompress

def clean_temp_dir(base_dir):
    """Clean the local temp directory."""
    temp_path = os.path.join(base_dir, TEMP_DIR)
    if os.path.exists(temp_path):
        for item in Path(temp_path).glob("*"):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

def recompress_zip(zip_file, base_dir):
    """Recompress a single ZIP file using Deflate."""
    base_name = os.path.basename(zip_file)
    print(f"Recompressing {zip_file}...")
    print(f"Current working directory: {os.getcwd()}")
    
    # Clean temp directory
    clean_temp_dir(base_dir)
    temp_path = os.path.join(base_dir, TEMP_DIR)
    print(f"Using temp directory: {temp_path}")

    # Extract with 7z
    try:
        subprocess.run(
            ["7z", "x", zip_file, f"-o{temp_path}", "-y"],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = f"Error extracting {zip_file}: {e.stderr}"
        print(error_msg)
        error_log_path = os.path.join(base_dir, ERROR_LOG)
        with open(error_log_path, "a") as log:
            log.write(f"{error_msg}\n")
        clean_temp_dir(base_dir)
        return False

    # Count extracted files
    extracted_files = len(list(Path(temp_path).rglob("*.xml")))
    print(f"Extracted {extracted_files} files from {zip_file}.")

    # Recompress with zip in one go
    temp_zip = os.path.join(temp_path, "temp.zip")
    print(f"Creating temp ZIP: {temp_zip}")
    os.chdir(temp_path)
    print(f"Changed to directory: {os.getcwd()}")
    try:
        # Compress all XML files in one zip command
        subprocess.run(
            ["zip", "-r", "-Z", "deflate", temp_zip, "."],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = f"Error recompressing {zip_file}: {e.stderr}"
        print(error_msg)
        error_log_path = os.path.join(base_dir, ERROR_LOG)
        with open(error_log_path, "a") as log:
            log.write(f"{error_msg}\n")
        os.chdir(base_dir)
        clean_temp_dir(base_dir)
        return False

    # Verify temp.zip exists
    if not os.path.exists(temp_zip):
        error_msg = f"Error: {temp_zip} was not created for {zip_file}."
        print(error_msg)
        error_log_path = os.path.join(base_dir, ERROR_LOG)
        with open(error_log_path, "a") as log:
            log.write(f"{error_msg}\n")
        os.chdir(base_dir)
        clean_temp_dir(base_dir)
        return False

    # Move to output directory using absolute path
    output_zip = os.path.join(base_dir, OUTPUT_DIR, base_name)
    print(f"Moving {temp_zip} to {output_zip}")
    try:
        shutil.move(temp_zip, output_zip)
    except (OSError, shutil.Error) as e:
        error_msg = f"Error moving {temp_zip} to {output_zip}: {e}"
        print(error_msg)
        error_log_path = os.path.join(base_dir, ERROR_LOG)
        with open(error_log_path, "a") as log:
            log.write(f"{error_msg}\n")
        os.chdir(base_dir)
        clean_temp_dir(base_dir)
        return False

    # Return to base directory and clean up
    os.chdir(base_dir)
    clean_temp_dir(base_dir)
    print(f"Successfully recompressed {zip_file} to {OUTPUT_DIR}/{base_name}")
    return True

def main():
    """Main function to scan and recompress ZIPs."""
    check_tools()

    # Get base directory (e.g., /Volumes/Data/irs_zips)
    base_dir = os.getcwd()
    ensure_permissions(base_dir)

    # Pass 1: Scan ZIPs
    print("=== Scan Pass ===")
    try:
        to_recompress = scan_zips(base_dir)
    except Exception as e:
        print(f"Error during scan: {e}")
        return

    if not to_recompress:
        print("No ZIP files need recompression.")
        return

    print("\nZIP files to recompress:")
    for zip_file in to_recompress:
        print(f"  {zip_file}")

    # Pass 2: Recompress
    print("\n=== Recompress Pass ===")
    for zip_file in to_recompress:
        if recompress_zip(zip_file, base_dir):
            continue
        print(f"Failed to recompress {zip_file}. See {ERROR_LOG} for details.")

    print(f"\nProcessing complete. Recompressed ZIPs are in {OUTPUT_DIR}/")
    print(f"Total recompressed files: {len(list(Path(OUTPUT_DIR).glob('*.zip')))}")
    if os.path.exists(os.path.join(base_dir, ERROR_LOG)) and os.path.getsize(os.path.join(base_dir, ERROR_LOG)) > 0:
        print(f"Warnings or errors were logged to {ERROR_LOG}.")

if __name__ == "__main__":
    main()