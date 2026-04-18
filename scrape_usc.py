#!/usr/bin/env python3
"""
scrape_usc.py — Scrape University of the Sunshine Coast (UniSC) agent finder.

UniSC embeds a StudyLink agent widget in an iframe:
  https://www.unisc.edu.au/international/how-to-apply/step-1-choose-a-program/unisc-agent-representatives

The widget uses source="admit" which calls StudyLink's ColdFusion endpoint:
  GET https://admissions-usc.studylink.com/webservices/public/index.cfm/institution_agencies
      ?institutionCodes=&countryInSearch=1

Returns a flat JSON array of all 962 agents.

Usage:
    python3 scrape_usc.py           # scrape all agents
    python3 scrape_usc.py --dry-run # print counts only, no DB writes
"""

import argparse
import html
import json
import re
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL    = (
    "https://admissions-usc.studylink.com"
    "/webservices/public/index.cfm/institution_agencies"
    "?institutionCodes=&countryInSearch=1"
)
SOURCE_URL = (
    "https://www.unisc.edu.au/international/how-to-apply"
    "/step-1-choose-a-program/unisc-agent-representatives"
)
HEADERS    = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://www.unisc.edu.au/",
}
DB_PATH    = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_agents() -> list[dict]:
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def clean_address(raw: str) -> str:
    """Strip HTML tags and normalise whitespace from Address field."""
    no_tags = re.sub(r"<[^>]+>", ", ", raw or "")
    cleaned = re.sub(r",\s*,", ",", no_tags)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    return html.unescape(cleaned)


def map_agent(rec: dict) -> dict:
    country = (rec.get("AddressCountry") or "").strip().title()
    address = clean_address(rec.get("Address", ""))
    return {
        "company_name": (rec.get("Name") or "").strip(),
        "country":      country,
        "region":       "",
        "city":         "",
        "email":        (rec.get("Email") or "").strip() or None,
        "phone":        (rec.get("PhoneNumber") or "").strip() or None,
        "website":      (rec.get("Website") or "").strip() or None,
        "address":      address or None,
        "raw_text":     json.dumps(
            {k: v for k, v in rec.items()
             if k not in ("LogoUrl",) and v not in (None, "", {})},
            ensure_ascii=False,
        ),
        "source_url":   SOURCE_URL,
    }


# ── Database ──────────────────────────────────────────────────────────────────

def insert_agents(conn: sqlite3.Connection, uni_id: int, agents: list[dict]) -> None:
    now = datetime.now().isoformat()
    conn.executemany("""
        INSERT OR IGNORE INTO agents
            (university_id, company_name, country, region, city,
             email, phone, website, address, raw_text, source_url, scraped_at)
        VALUES
            (:uni_id, :company_name, :country, :region, :city,
             :email, :phone, :website, :address, :raw_text, :source_url, :scraped_at)
    """, [{**a, "uni_id": uni_id, "scraped_at": now} for a in agents])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no DB writes")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT id FROM universities WHERE name LIKE '%Sunshine Coast%'"
    ).fetchone()
    if not row:
        print("ERROR: University of the Sunshine Coast not found in universities table")
        conn.close()
        return
    uni_id = row[0]

    if not args.dry_run:
        deleted = conn.execute("DELETE FROM agents WHERE university_id = ?", (uni_id,)).rowcount
        print(f"Cleared {deleted} existing USC agent records\n")
        conn.execute(
            "UPDATE universities SET agent_page_url = ? WHERE id = ?",
            (SOURCE_URL, uni_id),
        )

    print(f"Fetching StudyLink API …")
    raw_records = fetch_agents()
    print(f"API returned {len(raw_records)} records\n")

    agents = [map_agent(r) for r in raw_records if r.get("Name")]

    # Summary by country
    by_country: dict[str, int] = {}
    for a in agents:
        by_country[a["country"]] = by_country.get(a["country"], 0) + 1

    for cname, n in sorted(by_country.items()):
        print(f"  {cname:35s}  {n:3d} agents")

    print(f"\nTotal mapped: {len(agents)}")

    if not args.dry_run and agents:
        insert_agents(conn, uni_id, agents)
        conn.execute(
            "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
            (f"ok:studylink ({len(agents)})", datetime.now().isoformat(), uni_id),
        )
        conn.commit()
        print(f"\n✅ Inserted up to {len(agents)} agents (INSERT OR IGNORE). DB updated.")
    elif args.dry_run:
        print("\n(dry run — no DB writes)")

    conn.close()


if __name__ == "__main__":
    main()
