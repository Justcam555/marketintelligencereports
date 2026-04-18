#!/usr/bin/env python3
"""
scrape_uts.py — Scrape University of Technology Sydney agent finder.

UTS uses a two-level regional structure on a separate subdomain:

  Region index:  https://web-tools.uts.edu.au/agents/agents.cfm?region={region}
  Country page:  https://web-tools.uts.edu.au/agents/agents.cfm?region={region}&country={country}

Each country page lists agents as alternating:
  <h2>{Company} - {Country} - {City}</h2>
  <p>{address}<br> T: {phone}<br> Email: <a>...<br> Website: <a>...</p>

The main UTS page (uts.edu.au) contains no agent data — it just links out to
this subdomain. The original scraper hit the main page and got 0 results.

Usage:
    python3 scrape_uts.py           # scrape all regions
    python3 scrape_uts.py --dry-run # print counts only, no DB writes
"""

import argparse
import re
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

BASE_URL = "https://web-tools.uts.edu.au"
REGIONS  = [
    "africa",
    "asia",
    "europe",
    "middle east",
    "north america",
    "oceania",
    "south america",
]
HEADERS  = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DB_PATH  = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
DELAY    = 0.3   # seconds between requests


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ── Discovery ─────────────────────────────────────────────────────────────────

def get_country_urls(region: str) -> list[tuple[str, str]]:
    """Return [(country_name, full_url), ...] for one region."""
    encoded = region.replace(" ", "%20")
    html    = fetch(f"{BASE_URL}/agents/agents.cfm?region={encoded}")
    soup    = BeautifulSoup(html, "html.parser")
    main    = soup.find("main")
    if not main:
        return []
    results = []
    for a in main.find_all("a", href=True):
        if "country=" in a["href"]:
            results.append((
                a.get_text(strip=True),
                BASE_URL + a["href"],
            ))
    return results


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_country_page(url: str, region: str) -> list[dict]:
    """
    Parse all agent entries from one country page.

    h2 format:  "{Company} - {Country} - {City}"
    Uses rsplit(" - ", 2) so company names containing " - " are preserved.
    """
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if not main:
        return []

    agents = []
    for h2 in main.find_all("h2"):
        heading = h2.get_text(strip=True)
        if not heading or heading == "Agents":
            continue

        # Split from the right so company names with " - " are preserved
        parts = [p.strip() for p in heading.rsplit(" - ", 2)]
        if len(parts) == 3:
            company, country, city = parts
        elif len(parts) == 2:
            company, country, city = parts[0], parts[1], ""
        else:
            company, country, city = heading, "", ""

        # Details are in the immediately following <p>
        p = h2.find_next_sibling("p")
        if not p:
            continue

        raw = p.get_text(separator="\n", strip=True)

        # Phone: "T: +66 ..."
        phone_m = re.search(r'T:\s*(.+)', raw)
        phone   = phone_m.group(1).strip() if phone_m else None

        # Email: mailto: link
        email_a = p.find("a", href=lambda h: h and h.startswith("mailto:"))
        email   = email_a["href"].replace("mailto:", "").strip() if email_a else None

        # Website: http(s) link
        web_a   = p.find("a", href=lambda h: h and h.startswith(("http://", "https://")))
        website = web_a["href"].strip() if web_a else None

        # Address: lines before "T:", "Email:", "Website:"
        address_lines = []
        for line in raw.split("\n"):
            if re.match(r'(T:|Email:|Website:)', line):
                break
            stripped = line.strip().rstrip(",")
            if stripped:
                address_lines.append(stripped)
        address = ", ".join(address_lines) if address_lines else None

        agents.append({
            "company_name": company,
            "country":      country,
            "region":       region,
            "city":         city,
            "email":        email,
            "phone":        phone,
            "website":      website,
            "address":      address,
            "raw_text":     raw,
            "source_url":   url,
        })

    return agents


# ── Database ──────────────────────────────────────────────────────────────────

def insert_agents(conn: sqlite3.Connection, uni_id: int, agents: list[dict]) -> int:
    now = datetime.now().isoformat()
    conn.executemany("""
        INSERT OR IGNORE INTO agents
            (university_id, company_name, country, region, city,
             email, phone, website, address, raw_text, source_url, scraped_at)
        VALUES
            (:uni_id, :company_name, :country, :region, :city,
             :email, :phone, :website, :address, :raw_text, :source_url, :scraped_at)
    """, [{**a, "uni_id": uni_id, "scraped_at": now} for a in agents])
    return len(agents)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no DB writes")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT id FROM universities WHERE name = 'University of Technology Sydney'"
    ).fetchone()
    if not row:
        print("ERROR: 'University of Technology Sydney' not found in universities table")
        conn.close()
        return
    uni_id = row[0]

    if not args.dry_run:
        deleted = conn.execute("DELETE FROM agents WHERE university_id = ?", (uni_id,)).rowcount
        print(f"Cleared {deleted} existing UTS agent records\n")

    grand_total = 0
    by_region   = {}

    for region in REGIONS:
        print(f"Region: {region}")
        try:
            country_urls = get_country_urls(region)
        except Exception as e:
            print(f"  ERROR fetching region index: {e}")
            continue
        time.sleep(DELAY)

        region_total = 0
        for country_name, url in country_urls:
            try:
                agents = parse_country_page(url, region)
            except Exception as e:
                print(f"  {country_name}: ERROR — {e}")
                time.sleep(DELAY)
                continue

            if agents and not args.dry_run:
                insert_agents(conn, uni_id, agents)

            if agents:
                print(f"  {country_name:30s}  {len(agents):3d} agents")
            region_total += len(agents)
            time.sleep(DELAY)

        by_region[region] = region_total
        grand_total += region_total

    print(f"\n{'─'*50}")
    print(f"{'Region':<20}  Agents")
    for r, n in by_region.items():
        print(f"  {r:<18}  {n:,}")
    print(f"{'─'*50}")
    print(f"  {'TOTAL':<18}  {grand_total:,}")

    if not args.dry_run:
        conn.execute(
            "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
            (f"ok:uts_regional ({grand_total})", datetime.now().isoformat(), uni_id),
        )
        conn.commit()
        print(f"\n✅ Inserted {grand_total} agents. DB updated.")
    else:
        print("\n(dry run — no DB writes)")

    conn.close()


if __name__ == "__main__":
    main()
