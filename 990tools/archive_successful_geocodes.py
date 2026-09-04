#!/usr/bin/env python3

import duckdb
import os

def main():
    # Connect to the DuckDB database
    db_path = 'irs990.duckdb'
    if not os.path.exists(db_path):
        print(f"Database file {db_path} not found.")
        return

    conn = duckdb.connect(db_path, read_only=True)

    # Query for successful geocodes
    query = """
    SELECT * FROM Geocoding
    WHERE geocoding_status IN ('Match', 'Non_Exact')
    """

    # Get the count of records
    count_query = """
    SELECT COUNT(*) FROM Geocoding
    WHERE geocoding_status IN ('Match', 'Non_Exact')
    """
    count_result = conn.execute(count_query).fetchone()
    record_count = count_result[0] if count_result else 0

    # Ensure output directory exists
    output_dir = '_output'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Export to CSV
    output_path = os.path.join(output_dir, 'archived_successful_geocodes.csv')
    conn.execute(f"COPY ({query}) TO '{output_path}' (HEADER TRUE, DELIMITER ',')")

    # Close connection
    conn.close()

    print(f"Archived {record_count} records to {output_path}")

if __name__ == "__main__":
    main()