#!/usr/bin/env python3
"""
process_market_data.py — Parse Home Affairs visa exports into per-country JSON + CSV.

Usage:
    python3 process_market_data.py                     # all countries in agent DB
    python3 process_market_data.py --country Thailand  # single country
    python3 process_market_data.py --country Nepal

Input files expected in visa data Feb 2026/:
    Any file whose name contains the country name and "offshore" or "onshore" (case insensitive).
    e.g. Thailand_Offshore.xlsx, Thailand_onshore.xlsx

Output:
    data/processed/market_size_2026-02.json   (all countries)
    data/processed/market_size_2026-02.csv    (flat version)

--- HOW TO SAVE FILTERED EXCEL FILES ---

For each country, two saves required:

1. Open: marketintelligencereports/bp0015l-student-visas-granted-report-locked-at-2026-02-28-v100.xlsx
2. Go to sheet: Granted (Month)
3. Set filter: Citizenship Country = Thailand  (or Nepal, etc.)
4. Set filter: Client Location = Offshore
5. File → Save a Copy → "visa data Feb 2026/Thailand_Offshore.xlsx"
6. Change filter: Client Location = Onshore
7. File → Save a Copy → "visa data Feb 2026/Thailand_Onshore.xlsx"
8. Repeat for each country.

File names just need to contain the country name and "offshore"/"onshore" anywhere (case insensitive).
Country name must match exactly what appears in the Citizenship Country filter dropdown.
Common mappings: Vietnam → "Viet Nam", China → "China (People's Republic of)"
"""

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

BASE_DIR   = Path(__file__).parent
VISA_DIR   = BASE_DIR / "visa data Feb 2026"
PROC_DIR   = BASE_DIR / "data" / "processed"
DB_PATH    = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

DATA_AS_OF     = "February 2026"
OUTPUT_TAG     = "2026-02"
COMPLETE_YEARS = ["2022-23", "2023-24", "2024-25"]
PARTIAL_YEAR   = "2025-26 to 28 February 2026"
PARTIAL_LABEL  = "2025-26 YTD (to Feb 2026)"

SECTORS = [
    "Higher Education Sector",
    "Vocational Education and Training Sector",
    "Independent ELICOS Sector",
    "Schools Sector",
    "Postgraduate Research Sector",
    "Non-Award Sector",
    "Foreign Affairs or Defence Sector",
]
SECTOR_LABELS = {
    "Higher Education Sector":                  "Higher Education",
    "Vocational Education and Training Sector": "VET",
    "Independent ELICOS Sector":                "ELICOS",
    "Schools Sector":                           "Schools",
    "Postgraduate Research Sector":             "Postgraduate Research",
    "Non-Award Sector":                         "Non-Award",
    "Foreign Affairs or Defence Sector":        "Foreign Affairs / Defence",
}

HOMEAFFAIRS_COUNTRY_MAP = {
    "Vietnam":     "Viet Nam",
    "China":       "China (People's Republic of)",
    "Hong Kong":   "Hong Kong (SAR of China)",
    "South Korea": "Korea, Republic of",
    "Taiwan":      "Taiwan",
}

AEI_URL  = "https://app.powerbi.com/view?r=eyJrIjoiNTY0NWI1ODctODA2Mi00M2VmLThkZWEtZTJlZDc4OTAzMzBiIiwidCI6ImRkMGNmZDE1LTQ1NTgtNGIxMi04YmFkLWVhMjY5ODRmYzQxNyJ9"
HA_URL   = "https://data.gov.au/data/dataset/student-visas"

# ── Helpers ───────────────────────────────────────────────────────────────────

def country_slug(country: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", country.lower()).strip("_")


def find_visa_file(country: str, loc: str) -> Optional[Path]:
    """
    Scan VISA_DIR for a file whose name contains `country` and `loc`
    (either "offshore" or "onshore"), both case-insensitive.
    Returns the first match, or None.
    """
    country_lower = country.lower()
    loc_lower = loc.lower()
    for f in VISA_DIR.iterdir():
        name = f.name.lower()
        if country_lower in name and loc_lower in name:
            return f
    return None


def yoy_pct(current, previous):
    if not current or not previous or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def trend_arrow(yoy):
    if yoy is None:
        return "—"
    if yoy > 5:
        return "↑"
    if yoy < -5:
        return "↓"
    return "→"


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_visa_export(filepath: Path) -> tuple[dict, dict, dict]:
    """
    Parse a single filtered visa Excel export (offshore or onshore).

    Returns:
        filters       — active filter values from the header block
        primary_total — {fy: grant_count} for Primary Total row
        sector_data   — {sector_label: {fy: grant_count}}
    """
    df = pd.read_excel(filepath, sheet_name='Granted (Month)', header=None)
    rows = df.values.tolist()

    # Active filters — scan early rows for string key/value pairs
    filters: dict[str, str] = {}
    for row in rows[:15]:
        k = row[0] if len(row) > 0 else None
        v = row[1] if len(row) > 1 else None
        if isinstance(k, str) and isinstance(v, str):
            filters[k.strip()] = v.strip()

    # FY header row — first row that contains a "YYYY-YY" pattern in any cell;
    # record its index so we can limit sector scanning to the Primary block below it.
    fy_index: dict[str, int] = {}
    header_idx: int = 0
    for i, row in enumerate(rows):
        candidates = {
            col: str(cell).strip()
            for col, cell in enumerate(row)
            if isinstance(cell, str) and re.search(r'\d{4}-\d{2}', cell)
        }
        if candidates:
            fy_index = {label: col for col, label in candidates.items()}
            header_idx = i
            break

    all_years = COMPLETE_YEARS + [PARTIAL_YEAR]

    def cell_val(row, yr):
        if yr not in fy_index:
            return None
        v = row[fy_index[yr]] if fy_index[yr] < len(row) else None
        return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v

    # Scan the Primary block only — rows immediately after the FY header.
    # The sheet has a Secondary (dependants) block directly below; stop there
    # so we never overwrite Primary values with dependant counts.
    sector_data: dict[str, dict] = {}
    primary_total: dict = {}

    for row in rows[header_idx + 1:]:
        col_a = row[0] if len(row) > 0 else None
        col_b = row[1] if len(row) > 1 else None

        if isinstance(col_a, str) and col_a.strip() == "Secondary":
            break

        if isinstance(col_b, str) and col_b.strip() in SECTORS:
            canonical = SECTOR_LABELS[col_b.strip()]
            sector_data[canonical] = {yr: cell_val(row, yr) for yr in all_years}

        if isinstance(col_a, str) and col_a.strip() == "Primary Total":
            primary_total = {yr: cell_val(row, yr) for yr in all_years}

    return filters, primary_total, sector_data


# ── Builder ───────────────────────────────────────────────────────────────────

def build_market_data(country: str, offshore_file: Path, onshore_file: Path) -> dict:
    off_filters, offshore_total, offshore_sectors = parse_visa_export(offshore_file)
    on_filters,  onshore_total,  _                = parse_visa_export(onshore_file)

    # Confirm filters look right
    cc_off = off_filters.get("Citizenship Country", "?")
    cc_on  = on_filters.get("Citizenship Country", "?")
    loc_off = off_filters.get("Client Location", "?")
    loc_on  = on_filters.get("Client Location", "?")
    print(f"    Offshore file: Citizenship={cc_off}, Location={loc_off}")
    print(f"    Onshore file:  Citizenship={cc_on},  Location={loc_on}")

    # Offshore trend — last 3 complete years
    offshore_trend = {}
    for i, yr in enumerate(COMPLETE_YEARS):
        prev = offshore_total.get(COMPLETE_YEARS[i - 1]) if i > 0 else None
        curr = offshore_total.get(yr)
        yoy  = yoy_pct(curr, prev)
        offshore_trend[yr] = {
            "grants": curr,
            "yoy_pct": yoy,
            "trend": trend_arrow(yoy),
        }

    # Onshore — last 3 complete years
    onshore_trend = {
        yr: {"grants": onshore_total.get(yr)}
        for yr in COMPLETE_YEARS
    }

    # % offshore per year
    pct_offshore = {}
    for yr in COMPLETE_YEARS:
        off = offshore_total.get(yr) or 0
        on  = onshore_total.get(yr) or 0
        total = off + on
        pct_offshore[yr] = round(off / total * 100, 1) if total else None

    # Sector breakdown — offshore, latest complete year only
    by_level = {
        label: data.get("2024-25")
        for label, data in offshore_sectors.items()
    }

    return {
        "country": country,
        "data_as_of": DATA_AS_OF,
        "complete_years": COMPLETE_YEARS,
        "partial_year": {
            "label": PARTIAL_LABEL,
            "offshore": offshore_total.get(PARTIAL_YEAR),
            "onshore":  onshore_total.get(PARTIAL_YEAR),
        },
        "offshore": offshore_trend,
        "onshore":  onshore_trend,
        "pct_offshore": pct_offshore,
        "by_level_offshore_latest": by_level,
        "sources": {
            "visa_data": {
                "label": "Australian Department of Home Affairs",
                "url":   HA_URL,
            },
            "aei_interactive": {
                "label": "Explore commencements by sector — Australian Dept of Education",
                "url":   AEI_URL,
            },
        },
    }


# ── Display ───────────────────────────────────────────────────────────────────

def render_text_block(d: dict) -> str:
    """Print a formatted market size block to the terminal."""
    yrs  = d["complete_years"]
    off  = d["offshore"]
    on   = d["onshore"]
    pct  = d["pct_offshore"]
    lvl  = d["by_level_offshore_latest"]
    ytd  = d["partial_year"]

    def f(v):
        return f"{v:>7,}" if v else "      —"

    yoy_cells = '  '.join(
        f"{'  ' + trend_arrow(off[y]['yoy_pct']) + ' ' + (str(off[y]['yoy_pct']) + '%' if off[y]['yoy_pct'] else '—'):>9}"
        for y in yrs
    )
    pct_cells = '  '.join(
        f"{(str(pct[y]) + '%' if pct[y] else '—'):>9}"
        for y in yrs
    )

    lines = [
        f"\nMARKET SIZE — {d['country'].upper()}",
        f"Student visas granted  |  FY (Jul–Jun)  |  Data to {d['data_as_of']}",
        "",
        f"  {'':25} {'  '.join(f'{y:>9}' for y in yrs)}",
        "  " + "─" * 62,
        f"  {'OFFSHORE GRANTS':<25} {'  '.join(f(off[y]['grants']) for y in yrs)}",
        f"  {'YoY %':<25} {yoy_cells}",
        "",
        f"  {'Onshore grants':<25} {'  '.join(f(on[y]['grants']) for y in yrs)}",
        f"  {'% Offshore':<25} {pct_cells}",
        "  " + "─" * 62,
        "",
        "  BY LEVEL — Offshore 2024-25",
    ]
    for label, val in sorted(lvl.items(), key=lambda x: -(x[1] or 0)):
        lines.append(f"    {label:<32} {f(val)}")
    lines += [
        "",
        f"  {ytd['label']}",
        f"    Offshore: {ytd['offshore']:,}  |  Onshore: {ytd['onshore']:,}" if ytd['offshore'] and ytd['onshore'] else "    (no YTD data)",
        "    ── Partial year — not used for trend ──",
        "",
        "  Explore commencements by sector →",
        "  Australian Dept of Education — Interactive Report",
        f"  {AEI_URL[:70]}...",
        "",
        f"  Source: Australian Dept of Home Affairs  |  {HA_URL}",
    ]
    return "\n".join(lines)


# ── CSV export ────────────────────────────────────────────────────────────────

def to_csv_rows(all_data: list[dict]) -> list[dict]:
    rows = []
    for d in all_data:
        country = d["country"]
        for yr in d["complete_years"]:
            rows.append({
                "country":          country,
                "financial_year":   yr,
                "type":             "offshore",
                "grants":           d["offshore"][yr]["grants"],
                "yoy_pct":          d["offshore"][yr]["yoy_pct"],
            })
            rows.append({
                "country":          country,
                "financial_year":   yr,
                "type":             "onshore",
                "grants":           d["onshore"][yr]["grants"],
                "yoy_pct":          None,
            })
        # YTD row
        ytd = d["partial_year"]
        rows.append({
            "country":          country,
            "financial_year":   ytd["label"],
            "type":             "offshore_ytd",
            "grants":           ytd["offshore"],
            "yoy_pct":          None,
        })
        rows.append({
            "country":          country,
            "financial_year":   ytd["label"],
            "type":             "onshore_ytd",
            "grants":           ytd["onshore"],
            "yoy_pct":          None,
        })
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def get_countries() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT country FROM agent_social ORDER BY country"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", help="Single country to process")
    args = parser.parse_args()

    countries = [args.country] if args.country else get_countries()

    all_data = []
    skipped  = []

    for country in countries:
        offshore_file = find_visa_file(country, "offshore")
        onshore_file  = find_visa_file(country, "onshore")

        if not offshore_file or not onshore_file:
            missing = []
            if not offshore_file: missing.append("offshore")
            if not onshore_file:  missing.append("onshore")
            print(f"\n── {country} — SKIPPED (no {'/'.join(missing)} file found in '{VISA_DIR.name}')")
            skipped.append(country)
            continue

        print(f"\n── {country} ─────────────────")
        try:
            d = build_market_data(country, offshore_file, onshore_file)
            all_data.append(d)
            print(render_text_block(d))
        except Exception as e:
            print(f"  ✗ Error: {e}")
            skipped.append(country)

    if not all_data:
        print("\nNo data processed.")
        if skipped:
            print(f"\nSkipped {len(skipped)} countries — Excel exports not found.")
            print("See DOWNLOAD_INSTRUCTIONS.md to create filtered exports.")
        return

    # JSON
    json_path = PROC_DIR / f"market_size_{OUTPUT_TAG}.json"
    with open(json_path, "w") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ JSON → {json_path}")

    # CSV
    csv_path = PROC_DIR / f"market_size_{OUTPUT_TAG}.csv"
    rows = to_csv_rows(all_data)
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"✅ CSV  → {csv_path}")

    if skipped:
        print(f"\n⚠  Skipped: {', '.join(skipped)} — Excel exports not found")

    print(f"\nProcessed {len(all_data)} countries.")


if __name__ == "__main__":
    main()
