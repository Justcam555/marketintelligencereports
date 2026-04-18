#!/usr/bin/env python3
"""
scrape_scu.py — Scrape Southern Cross University agent finder.

SCU loads agent data in an iframe from a separate subdomain:
  https://ioa.scu.edu.au/agent/SCUI/heads

Structure:
  <h2 class="h4 mt-2">{Country}</h2>
  <div class="card mb-3 w-100 ms-3">
    <h5 class="card-title">{Company} - {City}</h5>
    <address>
      <strong>T:</strong><span> {phone}</span>
      <strong>E:</strong><a href="mailto:{email}">...</a>
      <strong>W:</strong><a href="{website}">...</a>
      ...
    </address>
  </div>

Usage:
    python3 scrape_scu.py           # scrape all agents
    python3 scrape_scu.py --dry-run # print counts only, no DB writes
"""

import argparse
import re
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

IFRAME_URL = "https://ioa.scu.edu.au/agent/SCUI/heads"
HEADERS    = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DB_PATH    = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_agents() -> list[dict]:
    html = fetch(IFRAME_URL)
    soup = BeautifulSoup(html, "html.parser")

    agents  = []
    country = ""

    for tag in soup.find_all(["h2", "div"]):
        # Country heading
        if tag.name == "h2" and "h4" in tag.get("class", []):
            text = tag.get_text(strip=True)
            if text:
                country = text
            continue

        # Agent card
        if tag.name == "div" and "card" in tag.get("class", []):
            h5 = tag.find("h5", class_="card-title")
            if not h5:
                continue

            heading = h5.get_text(strip=True)
            parts   = [p.strip() for p in heading.rsplit(" - ", 1)]
            company = parts[0]
            city    = parts[1] if len(parts) == 2 else ""

            addr_tag = tag.find("address")
            phone    = None
            email    = None
            website  = None
            address  = None

            if addr_tag:
                raw = addr_tag.get_text(separator="\n", strip=True)

                # Phone: strong "T:" followed by span
                t_span = None
                for strong in addr_tag.find_all("strong"):
                    if strong.get_text(strip=True) == "T:":
                        nxt = strong.find_next_sibling()
                        if nxt:
                            t_span = nxt.get_text(strip=True)
                        break
                phone = t_span or None

                # Email: mailto: link
                email_a = addr_tag.find("a", href=lambda h: h and h.startswith("mailto:"))
                email   = email_a["href"].replace("mailto:", "").strip() if email_a else None

                # Website: http link
                web_a   = addr_tag.find("a", href=lambda h: h and h.startswith(("http://", "https://")))
                website = web_a["href"].strip() if web_a else None

                # Address: lines before T:, E:, W:, "Registered", "Principal"
                address_lines = []
                for line in raw.split("\n"):
                    if re.match(r"(T:|E:|W:|Registered|Principal)", line):
                        break
                    stripped = line.strip().rstrip(",")
                    if stripped:
                        address_lines.append(stripped)
                address = ", ".join(address_lines) if address_lines else None

            agents.append({
                "company_name": company,
                "country":      country,
                "region":       "",
                "city":         city,
                "email":        email,
                "phone":        phone,
                "website":      website,
                "address":      address,
                "raw_text":     addr_tag.get_text(separator="\n", strip=True) if addr_tag else heading,
                "source_url":   IFRAME_URL,
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no DB writes")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT id FROM universities WHERE name LIKE '%Southern Cross%'"
    ).fetchone()
    if not row:
        print("ERROR: Southern Cross University not found in universities table")
        conn.close()
        return
    uni_id = row[0]

    if not args.dry_run:
        deleted = conn.execute("DELETE FROM agents WHERE university_id = ?", (uni_id,)).rowcount
        print(f"Cleared {deleted} existing SCU agent records\n")

    print(f"Fetching {IFRAME_URL} ...")
    agents = parse_agents()

    # Summary by country
    by_country: dict[str, int] = {}
    for a in agents:
        by_country[a["country"]] = by_country.get(a["country"], 0) + 1

    for cname, n in sorted(by_country.items()):
        print(f"  {cname:35s}  {n:3d} agents")

    print(f"\nTotal parsed: {len(agents)}")

    if not args.dry_run and agents:
        insert_agents(conn, uni_id, agents)
        conn.execute(
            "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
            (f"ok:scu_iframe ({len(agents)})", datetime.now().isoformat(), uni_id),
        )
        conn.commit()
        print(f"\n✅ Inserted up to {len(agents)} agents (INSERT OR IGNORE). DB updated.")
    elif args.dry_run:
        print("\n(dry run — no DB writes)")

    conn.close()


if __name__ == "__main__":
    main()
