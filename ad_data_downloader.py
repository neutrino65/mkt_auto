"""
download_ad_data.py
────────────────────────────────────────────────────────────────────
Downloads ad-source enquiry data from the Ezyschooling API in rolling
30-day windows, starting from today back to 2024-12-24, then compiles
everything into a single CSV file.

Usage:
    python download_ad_data.py

Requirements:
    pip install requests pandas
"""

import requests
import pandas as pd
from datetime import date, timedelta
import time
import os
import json

# ─── CONFIGURATION ────────────────────────────────────────────────
BASE_URL   = "https://api.main.ezyschooling.com/custom-admin/get-ad-source-enquiry-status/"
AD_SOURCE  = "Google"
END_DATE   = date.today()                   # Start downloading from today
##STOP_DATE  = date(2024, 12, 24)             # Go all the way back to this date
STOP_DATE  = date(2026, 1, 2)             # Go all the way back to this date
WINDOW     = 30                             # Max days per request
OUTPUT_DIR = "downloaded_chunks"            # Folder to save each chunk
FINAL_CSV  = "ad_source_data_compiled.csv" # Final compiled output file
SLEEP_SEC  = 1                             # Pause between requests (be polite to the API)
# ──────────────────────────────────────────────────────────────────


def generate_date_windows(end: date, stop: date, window: int):
    """
    Generates (start_date, end_date) tuples going backwards in time.

    Example for window=30, end=2026-03-24, stop=2024-12-24:
      Window 1 → (2026-02-22, 2026-03-24)
      Window 2 → (2026-01-23, 2026-02-21)
      Window 3 → (2025-12-24, 2026-01-22)
      ...and so on until start_date <= stop

    Yields:
        tuple(date, date): (start_date, end_date) for each window
    """
    current_end = end
    while current_end >= stop:
        current_start = current_end - timedelta(days=window - 1)
        # Clamp start so we never go past the stop date
        if current_start < stop:
            current_start = stop
        yield current_start, current_end
        # Move end to the day before current window's start
        current_end = current_start - timedelta(days=1)


def fetch_data(start: date, end: date) -> list:
    """
    Calls the API for the given date range and returns the data as a list.

    The function handles:
      - Both list responses  → [ {...}, {...} ]
      - Dict with a results key  → { "results": [...], "count": N }
      - Unexpected formats (returns empty list with a warning)

    Args:
        start (date): Start date of the window
        end   (date): End date of the window

    Returns:
        list: Records fetched from the API
    """
    params = {
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date":   end.strftime("%Y-%m-%d"),
        "ad_source":  AD_SOURCE,
    }

    print(f"  → Requesting {params['start_date']}  to  {params['end_date']} ...", end=" ")

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()  # Raise an error for 4xx / 5xx status codes
    except requests.exceptions.RequestException as e:
        print(f"FAILED ✗  ({e})")
        return []

    try:
        data = response.json()
    except json.JSONDecodeError:
        print("FAILED ✗  (Invalid JSON response)")
        return []

    # ── Normalise response shape ───────────────────────────────────
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Common Django REST Framework pagination shape
        records = data.get("results", data.get("data", []))
        if not isinstance(records, list):
            # The dict itself might be a single record
            records = [data]
    else:
        print(f"WARN ✗  Unexpected response type: {type(data)}")
        return []

    print(f"OK ✓  ({len(records)} records)")
    return records


def save_chunk(records: list, start: date, end: date, directory: str):
    """
    Saves a list of records to a CSV file named by the date range.

    Args:
        records   (list): Data rows to save
        start     (date): Start date (used in filename)
        end       (date): End date (used in filename)
        directory (str):  Folder to save into

    Returns:
        str | None: Path of the saved file, or None if nothing to save
    """
    if not records:
        return None

    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, f"{start}_{end}.csv")
    df = pd.DataFrame(records)
    df.to_csv(filename, index=False)
    return filename


def compile_chunks(directory: str, output_file: str) -> int:
    """
    Reads every CSV chunk from the directory, stacks them into one
    DataFrame, and writes it to a single compiled CSV.

    Args:
        directory   (str): Folder containing chunk CSV files
        output_file (str): Path for the final compiled CSV

    Returns:
        int: Total number of rows compiled
    """
    csv_files = sorted([
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".csv")
    ])

    if not csv_files:
        print("No chunk files found to compile.")
        return 0

    frames = []
    for f in csv_files:
        df = pd.read_csv(f)
        frames.append(df)

    compiled = pd.concat(frames, ignore_index=True)
    compiled.to_csv(output_file, index=False)
    return len(compiled)


# ─── MAIN ─────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(" Ezyschooling Ad-Source Enquiry Downloader")
    print("=" * 60)
    print(f" Ad Source  : {AD_SOURCE}")
    print(f" From       : {END_DATE}  back to  {STOP_DATE}")
    print(f" Window     : {WINDOW} days per request")
    print(f" Output dir : {OUTPUT_DIR}/")
    print(f" Final CSV  : {FINAL_CSV}")
    print("=" * 60)

    windows       = list(generate_date_windows(END_DATE, STOP_DATE, WINDOW))
    total_windows = len(windows)
    saved_files   = []
    total_records = 0

    for i, (start, end) in enumerate(windows, start=1):
        print(f"[{i}/{total_windows}]", end=" ")
        records = fetch_data(start, end)
        total_records += len(records)

        path = save_chunk(records, start, end, OUTPUT_DIR)
        if path:
            saved_files.append(path)

        if i < total_windows:
            time.sleep(SLEEP_SEC)  # Polite delay between API calls

    print()
    print("-" * 60)
    print(f" Download complete.")
    print(f"   Windows fetched : {total_windows}")
    print(f"   Total records   : {total_records}")
    print(f"   Chunks saved    : {len(saved_files)}")

    # ── Compile all chunks ─────────────────────────────────────────
    print()
    print(f" Compiling all chunks into '{FINAL_CSV}' ...")
    total_compiled = compile_chunks(OUTPUT_DIR, FINAL_CSV)
    print(f" Done! {total_compiled} total rows written to '{FINAL_CSV}'.")
    print("=" * 60)


if __name__ == "__main__":
    main()