#!/usr/bin/env python3
"""
scrape_federation.py — Scrape Federation University agent finder via Ascentone API.

Federation uses the Ascentone agent publisher platform:
  https://eap.ascentone.com/federation

The page is a JS SPA; agent data comes from a POST to:
  POST https://eap.ascentone.com/PageHandlers/AgentPublisherV5.ashx
       ?rdnm=0.1&mapload=0&operate=GetAgentPublishersGridData

POST body:
  ClientFilter=<JSON string>

where the JSON contains the university's eKey (UniqueId).

Response: JSON with a "ClientDetails" list of agent objects.

Federation UniqueId: 80995df0-1f30-4c33-a00f-7fd7d584e143

Usage:
    python3 scrape_federation.py           # scrape all agents
    python3 scrape_federation.py --dry-run # print counts only, no DB writes
"""

import argparse
import json
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL   = (
    "https://eap.ascentone.com/PageHandlers/AgentPublisherV5.ashx"
    "?rdnm=0.1&mapload=0&operate=GetAgentPublishersGridData"
)
EKEY      = "80995df0-1f30-4c33-a00f-7fd7d584e143"
SOURCE_URL = "https://eap.ascentone.com/federation"
HEADERS   = {
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer":      SOURCE_URL,
    "X-Requested-With": "XMLHttpRequest",
}
DB_PATH   = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


# ── API ───────────────────────────────────────────────────────────────────────

def fetch_agents() -> list[dict]:
    client_filter = json.dumps({
        "eKey":             EKEY,
        "Country":          "",
        "State":            "",
        "City":             "",
        "AgentName":        "",
        "lattitude":        0,
        "longitude":        0,
        "hasMap":           0,
        "hasChinaMap":      0,
        "selectedDistance": "",
    })
    body = urllib.parse.urlencode({"ClientFilter": client_filter}).encode()
    req  = urllib.request.Request(API_URL, data=body, headers=HEADERS, method="POST")

    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode("utf-8"))

    return payload.get("ClientDetails", [])


# ── Mapping ───────────────────────────────────────────────────────────────────

def map_agent(record: dict) -> dict:
    """Map Ascentone ClientDetails fields to our agents DB schema."""
    company = (record.get("legal_name") or "").strip()
    city    = (record.get("AgentCity") or "").strip()
    state   = (record.get("AgentState") or "").strip()
    country = (record.get("AgentCountry") or "").strip()
    phone   = (record.get("Agentphone") or record.get("phone") or "").strip() or None
    email   = (record.get("email") or "").strip() or None
    website = (record.get("website") or "").strip() or None

    addr1   = (record.get("AddressLine1") or record.get("AgentStreet1") or "").strip()
    addr2   = (record.get("AddressLine2") or record.get("AgentStreet2") or "").strip()
    postcode = (record.get("post_code") or "").strip()
    addr_parts = [p for p in [addr1, addr2, city, state, postcode, country] if p]
    address = ", ".join(addr_parts) or None

    raw_text = json.dumps({
        k: v for k, v in record.items()
        if v not in (None, "", 0)
    }, ensure_ascii=False)

    return {
        "company_name": company,
        "country":      country,
        "region":       "",
        "city":         city,
        "email":        email,
        "phone":        phone,
        "website":      website,
        "address":      address,
        "raw_text":     raw_text,
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
        "SELECT id FROM universities WHERE name LIKE '%Federation%'"
    ).fetchone()
    if not row:
        print("ERROR: Federation University not found in universities table")
        conn.close()
        return
    uni_id = row[0]

    if not args.dry_run:
        # Also update the stored URL to the correct Ascentone page
        conn.execute(
            "UPDATE universities SET agent_page_url = ? WHERE id = ?",
            (SOURCE_URL, uni_id),
        )
        deleted = conn.execute("DELETE FROM agents WHERE university_id = ?", (uni_id,)).rowcount
        print(f"Cleared {deleted} existing Federation agent records")
        print(f"Updated agent_page_url → {SOURCE_URL}\n")

    print(f"Calling Ascentone API (eKey={EKEY[:8]}...) ...")
    raw_records = fetch_agents()
    print(f"API returned {len(raw_records)} records\n")

    agents = [map_agent(r) for r in raw_records if r.get("legal_name")]

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
            (f"ok:ascentone ({len(agents)})", datetime.now().isoformat(), uni_id),
        )
        conn.commit()
        print(f"\n✅ Inserted up to {len(agents)} agents (INSERT OR IGNORE). DB updated.")
    elif args.dry_run:
        print("\n(dry run — no DB writes)")

    conn.close()


if __name__ == "__main__":
    main()
