#!/usr/bin/env python3
"""
batch_process_markets.py — Process all visa data exports in 'visa data Feb 2026/'
and write a combined market_size JSON + CSV covering all available markets.

Derives country list directly from filenames — no DB required.
"""

import csv
import json
import re
import sys
from pathlib import Path

# Import shared parsing/building logic from process_market_data
sys.path.insert(0, str(Path(__file__).parent))
from process_market_data import (
    find_visa_file,
    build_market_data,
    render_text_block,
    to_csv_rows,
    OUTPUT_TAG,
    PROC_DIR,
)

VISA_DIR = Path(__file__).parent / "visa data Feb 2026"


def countries_from_files() -> list[str]:
    """Extract sorted unique country names from offshore/onshore filename pairs."""
    names = set()
    for f in VISA_DIR.iterdir():
        if f.suffix.lower() != ".xlsx":
            continue
        country = re.sub(r"[_\s]*(offshore|onshore)\s*$", "", f.stem, flags=re.I).strip()
        if country:
            names.add(country)
    return sorted(names)


def main():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    countries = countries_from_files()
    print(f"Found {len(countries)} countries in '{VISA_DIR.name}'\n")

    all_data: list[dict] = []
    skipped:  list[str]  = []

    for country in countries:
        offshore_file = find_visa_file(country, "offshore")
        onshore_file  = find_visa_file(country, "onshore")

        if not offshore_file or not onshore_file:
            missing = []
            if not offshore_file: missing.append("offshore")
            if not onshore_file:  missing.append("onshore")
            print(f"  SKIP  {country} — missing {'/'.join(missing)}")
            skipped.append(country)
            continue

        print(f"── {country} ──")
        try:
            d = build_market_data(country, offshore_file, onshore_file)
            all_data.append(d)
            print(render_text_block(d))
        except Exception as e:
            print(f"  ERROR: {e}")
            skipped.append(country)

    # ── Write JSON ────────────────────────────────────────────────────────────
    json_path = PROC_DIR / f"market_size_{OUTPUT_TAG}.json"
    with open(json_path, "w") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ JSON → {json_path}  ({len(all_data)} countries)")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    csv_path = PROC_DIR / f"market_size_{OUTPUT_TAG}.csv"
    rows = to_csv_rows(all_data)
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"✅ CSV  → {csv_path}  ({len(rows)} rows)")

    if skipped:
        print(f"\n⚠  Skipped ({len(skipped)}): {', '.join(skipped)}")

    print(f"\nProcessed {len(all_data)} / {len(countries)} countries.")


if __name__ == "__main__":
    main()
