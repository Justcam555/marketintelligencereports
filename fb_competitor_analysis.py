#!/usr/bin/env python3
"""
fb_competitor_analysis.py

Analyses the Meta Ad Library Report CSV for Thailand.

Sources:
  advertisers.csv  — national advertiser spend + ad count
  locations.csv    — total spend by province (no advertiser breakdown)
  regions/*.csv    — per-province advertiser spend

Usage:
    python3 fb_competitor_analysis.py
"""

import csv
import glob
import os
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

REPO_DIR = Path(__file__).parent

COMPETITOR_GROUPS = [
    ("IDP",             ["IDP"]),
    ("AECC",            ["AECC"]),
    ("Hands On",        ["Hands On", "HandsOn", "Hands-On"]),
    ("SI-UK",           ["SI-UK", "SI UK", "SIUK"]),
    ("IEC Abroad",      ["IEC Abroad"]),
    ("Bada Global",     ["Bada Global", "Bada"]),
    ("Mango Education", ["Mango Education"]),
    ("One Education",   ["One Education", "OneEducation"]),
]

UNIVERSITIES = [
    "Monash","Melbourne","RMIT","Deakin","Swinburne","La Trobe",
    "UNSW","UTS","Macquarie","Wollongong","Newcastle",
    "ANU","Canberra","ACU","Charles Sturt","Charles Darwin","CQU",
    "Southern Cross","Griffith","QUT","Bond","JCU","USQ","UniSQ",
    "Sunshine Coast","UniSC","Murdoch","Curtin","ECU","Edith Cowan",
    "Flinders","Adelaide","UniSA","Tasmania","Federation","Torrens",
]

OUTPUT_CSV = REPO_DIR / "fb_competitor_analysis_output.csv"

# ── Helpers ───────────────────────────────────────────────────────────────────

def read_csv(path):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return list(reader.fieldnames or []), rows
        except UnicodeDecodeError:
            continue
    return [], []


def read_csv_clean(path: Path) -> tuple[list[str], list[dict]]:
    """Read CSV, stripping BOM from header names."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                content = f.read()
            lines = content.splitlines()
            if not lines:
                return [], []
            reader = csv.DictReader(lines)
            rows = list(reader)
            headers = [h.lstrip("﻿") for h in (reader.fieldnames or [])]
            clean_rows = [{h.lstrip("﻿"): v for h, v in r.items()} for r in rows]
            return headers, clean_rows
        except UnicodeDecodeError:
            continue
    return [], []


def match_competitor(text):
    t = text.lower()
    for label, keywords in COMPETITOR_GROUPS:
        if any(kw.lower() in t for kw in keywords):
            return label
    return None


def find_unis(text):
    t = text.lower()
    return [u for u in UNIVERSITIES if u.lower() in t]


def thb(val: str) -> int:
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0


def fmt_thb(n: int) -> str:
    if n == 0:
        return "—"
    if n >= 1_000_000:
        return f"฿{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"฿{n/1_000:.0f}K"
    return f"฿{n:,}"


def find_report_dir():
    for p in sorted(REPO_DIR.glob("FacebookAdLibraryReport*"), reverse=True):
        if p.is_dir():
            return p
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    report_dir = find_report_dir()
    if not report_dir:
        print("ERROR: FacebookAdLibraryReport folder not found in project directory.")
        sys.exit(1)

    prefix = report_dir.name
    adv_file = report_dir / f"{prefix}_advertisers.csv"
    loc_file = report_dir / f"{prefix}_locations.csv"
    regions_dir = report_dir / "regions"

    if not adv_file.exists():
        print(f"ERROR: {adv_file.name} not found.")
        sys.exit(1)

    print(f"Report folder : {report_dir.name}")

    # ── 1. Advertisers ────────────────────────────────────────────────────────

    headers, adv_rows = read_csv_clean(adv_file)
    print(f"Advertisers   : {len(adv_rows):,} rows  |  columns: {', '.join(headers)}")

    matched_adv = []
    for row in adv_rows:
        page_name  = (row.get("Page name") or "").strip()
        disclaimer = (row.get("Disclaimer") or "").strip()
        combined   = f"{page_name} {disclaimer}"
        label = match_competitor(combined)
        if not label:
            continue
        matched_adv.append({
            "competitor": label,
            "page_name":  page_name,
            "disclaimer": disclaimer,
            "page_id":    row.get("Page ID", ""),
            "spend_thb":  thb(row.get("Amount spent (THB)", 0)),
            "ad_count":   row.get("Number of ads in Library", "?"),
            "unis":       find_unis(combined),
        })

    matched_adv.sort(key=lambda r: (-r["spend_thb"], r["competitor"]))

    # ── 2. Regional breakdown (regions/*.csv) ─────────────────────────────────

    region_hits: dict[str, dict] = {}   # page_name → {province: spend_thb}

    if regions_dir.exists():
        region_files = sorted(regions_dir.glob("*.csv"))
        print(f"Region files  : {len(region_files)}")

        for rf in region_files:
            # Province name is between last "_" and ".csv"
            province = rf.stem.replace(f"{prefix}_", "").strip()
            _, rows = read_csv_clean(rf)
            for row in rows:
                page_name = (row.get("Page name") or "").strip()
                label = match_competitor(f"{page_name} {row.get('Disclaimer','')}")
                if not label:
                    continue
                if page_name not in region_hits:
                    region_hits[page_name] = {}
                region_hits[page_name][province] = thb(row.get("Amount spent (THB)", 0))

    # ── 3. Locations summary (total spend per province, all advertisers) ──────

    loc_data: dict[str, int] = {}
    if loc_file.exists():
        _, loc_rows = read_csv_clean(loc_file)
        for row in loc_rows:
            loc_data[row.get("Location name", "")] = thb(row.get("Amount spent (THB)", 0))

    # ── Print advertiser report ───────────────────────────────────────────────

    print()
    print("=" * 74)
    print("  META AD LIBRARY — THAILAND (last 30 days)")
    print("  Spend in Thai Baht (THB).  Exchange rate ≈ ฿35 = $1 USD")
    print("=" * 74)

    if not matched_adv:
        print("\n  No competitors matched. Keywords searched:")
        for label, kws in COMPETITOR_GROUPS:
            print(f"    {label}: {kws}")
        sys.exit(0)

    print(f"\n  {'Competitor':<18} {'Page Name':<32} {'Ads':>4}  {'Spend (THB)':>10}  {'Unis'}")
    print(f"  {'-'*18} {'-'*32} {'-'*4}  {'-'*10}  {'-'*20}")

    for r in matched_adv:
        unis = ", ".join(r["unis"]) if r["unis"] else "—"
        print(f"  {r['competitor']:<18} {r['page_name'][:32]:<32} "
              f"{str(r['ad_count']):>4}  {fmt_thb(r['spend_thb']):>10}  {unis}")

    total_spend = sum(r["spend_thb"] for r in matched_adv)
    total_ads   = sum(int(r["ad_count"]) for r in matched_adv
                      if str(r["ad_count"]).isdigit())
    print(f"\n  Total matched pages : {len(matched_adv)}")
    print(f"  Total ads in library: {total_ads:,}")
    print(f"  Total spend (THB)   : {fmt_thb(total_spend)}  (~${total_spend//35:,} USD)")

    # ── Print regional breakdown ──────────────────────────────────────────────

    if region_hits:
        print()
        print("=" * 74)
        print("  REGIONAL SPEND BREAKDOWN  (provinces where competitors appear)")
        print("=" * 74)

        for r in matched_adv:
            pname = r["page_name"]
            provs = region_hits.get(pname)
            if not provs:
                continue
            top = sorted(provs.items(), key=lambda x: -x[1])[:8]
            prov_str = "  ".join(f"{p}: {fmt_thb(s)}" for p, s in top)
            print(f"\n  {r['competitor']} — {pname}")
            print(f"    {prov_str}")

    # ── Save output CSV ───────────────────────────────────────────────────────

    out_rows = []
    for r in matched_adv:
        provs = region_hits.get(r["page_name"], {})
        top_provinces = "; ".join(
            f"{p}:{fmt_thb(s)}" for p, s in
            sorted(provs.items(), key=lambda x: -x[1])[:5]
        )
        out_rows.append({
            "competitor":      r["competitor"],
            "page_name":       r["page_name"],
            "disclaimer":      r["disclaimer"],
            "page_id":         r["page_id"],
            "ad_count":        r["ad_count"],
            "spend_thb":       r["spend_thb"],
            "spend_usd_est":   r["spend_thb"] // 35,
            "unis_detected":   "; ".join(r["unis"]),
            "top_provinces":   top_provinces,
        })

    if out_rows:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
        print(f"\n  ✅  Saved: {OUTPUT_CSV.name}")


if __name__ == "__main__":
    main()
