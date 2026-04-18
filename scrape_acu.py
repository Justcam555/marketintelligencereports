#!/usr/bin/env python3
"""
scrape_acu.py — Scrape Australian Catholic University agent list.

ACU embeds a search widget on:
  https://www.acu.edu.au/international-students/find-an-acu-education-agent

The widget calls:
  GET https://www.acu.edu.au/webapi/internationalagentsearch/get

Returns all 1,283 agents in one call as UTF-8-BOM JSON.

Fields: Agent_Company_Name, Office_Street_City, Office_Mail_Addr1-4,
        Country, Office_Phone1, Office_Email3, Office_Web

Usage:
    python3 scrape_acu.py           # scrape all agents
    python3 scrape_acu.py --dry-run # print counts only, no DB writes
"""

import argparse
import json
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL    = "https://www.acu.edu.au/webapi/internationalagentsearch/get"
SOURCE_URL = "https://www.acu.edu.au/international-students/find-an-acu-education-agent"
HEADERS    = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": SOURCE_URL,
}
DB_PATH    = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


# ── API ───────────────────────────────────────────────────────────────────────

def fetch_agents() -> list[dict]:
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    # API returns UTF-8 with BOM
    data = json.loads(raw.decode("utf-8-sig"))
    return data.get("Results", [])


# ── Mapping ───────────────────────────────────────────────────────────────────

def map_agent(rec: dict) -> dict:
    addr_parts = [
        rec.get("Office_Mail_Addr1", "").strip(),
        rec.get("Office_Mail_Addr2", "").strip(),
        rec.get("Office_Mail_Addr3", "").strip(),
        rec.get("Office_Mail_Addr4", "").strip(),
    ]
    address = ", ".join(p for p in addr_parts if p) or None

    website = (rec.get("Office_Web") or "").strip() or None
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website

    return {
        "company_name": (rec.get("Agent_Company_Name") or "").strip(),
        "country":      (rec.get("Country") or "").strip(),
        "region":       "",
        "city":         (rec.get("Office_Street_City") or "").strip(),
        "email":        (rec.get("Office_Email3") or "").strip() or None,
        "phone":        (rec.get("Office_Phone1") or "").strip() or None,
        "website":      website,
        "address":      address,
        "raw_text":     json.dumps(
            {k: v for k, v in rec.items() if v not in (None, "")},
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
        "SELECT id FROM universities WHERE name LIKE '%Catholic%'"
    ).fetchone()
    if not row:
        print("ERROR: Australian Catholic University not found in universities table")
        conn.close()
        return
    uni_id = row[0]

    if not args.dry_run:
        deleted = conn.execute("DELETE FROM agents WHERE university_id = ?", (uni_id,)).rowcount
        print(f"Cleared {deleted} existing ACU agent records\n")

    print("Fetching ACU agent API …")
    raw_records = fetch_agents()
    print(f"API returned {len(raw_records)} records\n")

    agents = [map_agent(r) for r in raw_records if r.get("Agent_Company_Name")]

    # Summary by country
    by_country: dict[str, int] = {}
    for a in agents:
        by_country[a["country"]] = by_country.get(a["country"], 0) + 1

    for cname, n in sorted(by_country.items()):
        print(f"  {cname:40s}  {n:3d} agents")

    print(f"\nTotal mapped: {len(agents)}")

    if not args.dry_run and agents:
        insert_agents(conn, uni_id, agents)
        conn.execute(
            "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
            (f"ok:acu_api ({len(agents)})", datetime.now().isoformat(), uni_id),
        )
        conn.commit()
        print(f"\n✅ Inserted up to {len(agents)} agents (INSERT OR IGNORE). DB updated.")
    elif args.dry_run:
        print("\n(dry run — no DB writes)")

    conn.close()


if __name__ == "__main__":
    main()
