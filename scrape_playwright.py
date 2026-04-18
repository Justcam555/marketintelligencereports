#!/usr/bin/env python3
"""
scrape_playwright.py — Playwright-based scraper for UWA and QUT.

UWA: React SPA, auto-searches on mount via jQuery AJAX to
     /Feature/AgentsSearch/SearchResult. Alphabetical mode returns all
     agents in one call; relevance mode paginates via "Load more" button.

QUT: Behind Cloudflare JS challenge — curl always gets 403.
     Playwright's real Chromium passes the challenge. Page structure
     unknown until rendered; tries multiple parsing strategies.

Install:
    pip install playwright
    playwright install chromium

Usage:
    python3 scrape_playwright.py                     # both unis
    python3 scrape_playwright.py --university uwa    # UWA only
    python3 scrape_playwright.py --university qut    # QUT only
    python3 scrape_playwright.py --dry-run           # no DB writes
"""

import argparse
import asyncio
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

DB_PATH = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


# ── UWA ───────────────────────────────────────────────────────────────────────

UWA_URL = "https://www.uwa.edu.au/study/international-students/find-an-international-agent"
UWA_API = "/Feature/AgentsSearch/SearchResult"


async def scrape_uwa(page: Page) -> list[dict]:
    """
    Intercept all responses from /Feature/AgentsSearch/SearchResult.
    The component auto-searches on mount in alphabetical mode, returning
    all agents in one call. If pagination is needed (relevance mode),
    click "Load more" until exhausted. Falls back to direct API calls
    if hits < totalSearchResults after initial load.
    """
    all_hits: list[dict]  = []
    total_expected: list[int] = [0]   # mutable container for callback

    async def capture_response(response):
        if UWA_API not in response.url:
            return
        if response.status != 200:
            return
        try:
            data   = await response.json()
            sr     = data.get("state", {}).get("searchResult", {})
            hits   = sr.get("hits", [])
            total  = sr.get("totalSearchResults", 0)
            total_expected[0] = total
            all_hits.extend(hits)
            print(f"    API → {len(hits)} hits  (total={total}, collected={len(all_hits)})")
        except Exception as e:
            print(f"    API parse error: {e}")

    page.on("response", capture_response)

    print(f"  Navigating to UWA agent page …")
    await page.goto(UWA_URL, wait_until="load", timeout=60_000)
    await page.wait_for_timeout(5_000)

    # Extract the country list embedded in the React hydration payload
    country_keys: list[str] = await page.evaluate("""
        () => {
            const scripts = Array.from(document.querySelectorAll('script'));
            for (const s of scripts) {
                const t = s.textContent || '';
                const m = t.match(/React\\.createElement\\(AgentSearchResult,\\s*(\\{.+\\})\\s*\\)/s);
                if (m) {
                    try {
                        const data = JSON.parse(m[1]);
                        return (data.filter?.allCountriesList || [])
                            .map(c => c.key)
                            .filter(k => k && k !== 'NA');
                    } catch(e) { return []; }
                }
            }
            return [];
        }
    """)
    print(f"  Found {len(country_keys)} country codes — querying each …")

    # The API requires country[] to be set; without it returns 0
    seen_ids: set = set()
    for i, code in enumerate(country_keys):
        result = await page.evaluate(f"""
            async () => {{
                const params = new URLSearchParams({{json: 'true', pageNumber: '1', sortByRelevance: 'false'}});
                params.append('country[]', '{code}');
                const r = await fetch('/Feature/AgentsSearch/SearchResult', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    }},
                    body: params
                }});
                return r.json();
            }}
        """)
        sr   = result.get("state", {}).get("searchResult", {})
        hits = sr.get("hits", [])
        new  = [h for h in hits if h.get("id") not in seen_ids]
        for h in new:
            seen_ids.add(h.get("id"))
        all_hits.extend(new)
        if new:
            print(f"    {code}: {len(hits)} hits, {len(new)} new  (total={len(all_hits)})")
        await asyncio.sleep(0.2)

    agents = []
    for hit in all_hits:
        addr_parts = [hit.get("addressLine1", ""), hit.get("addressLine2", "")]
        addr_parts = [p.strip() for p in addr_parts if p and p.strip()]

        agents.append({
            "company_name": (hit.get("name") or "").strip(),
            "country":      (hit.get("country") or "").strip(),
            "region":       "",
            "city":         (hit.get("city") or "").strip(),
            "email":        (hit.get("emailContact") or "").strip() or None,
            "phone":        (hit.get("phoneContact") or "").strip() or None,
            "website":      (hit.get("agentUrl") or "").strip() or None,
            "address":      ", ".join(addr_parts) or None,
            "raw_text":     json.dumps(
                {k: v for k, v in hit.items() if v not in (None, "", 0)},
                ensure_ascii=False
            ),
            "source_url":   UWA_URL,
        })

    return agents


# ── QUT ───────────────────────────────────────────────────────────────────────

QUT_URL     = "https://www.qut.edu.au/study/international/find-a-representative"
QUT_API_PATH = "/study/international/find-a-representative/qcr-international-agents-rest"


async def scrape_qut(page: Page) -> list[dict]:
    """
    QUT is behind Cloudflare — Playwright passes the JS challenge.
    Once the page loads, the browser calls /qcr-international-agents-rest
    which returns all agents as JSON. We fetch that endpoint from inside
    the browser context (session cookies already set) via page.evaluate.
    """
    print("  Navigating to QUT agent page (Cloudflare may challenge) …")
    await page.goto(QUT_URL, wait_until="domcontentloaded", timeout=90_000)

    # Wait for Cloudflare JS challenge to resolve
    for _ in range(6):
        title = await page.title()
        if "just a moment" in title.lower() or "checking" in title.lower():
            print(f"    Cloudflare challenge ({title!r}) — waiting …")
            await page.wait_for_timeout(5_000)
        else:
            break

    await page.wait_for_timeout(2_000)
    print(f"  Page title: {await page.title()!r}")

    # Fetch the REST endpoint from inside the browser (has CF session cookies)
    print(f"  Fetching {QUT_API_PATH} …")
    raw = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{QUT_API_PATH}', {{
                headers: {{'X-Requested-With': 'XMLHttpRequest'}}
            }});
            return r.text();
        }}
    """)

    print(f"  Response: {len(raw):,} chars")

    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"  JSON parse error: {e}")
        print(f"  First 300 chars: {raw[:300]}")
        return []

    # Normalise — could be a list or a dict with a list inside
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Try common wrapper keys
        records = (data.get("agents") or data.get("results") or
                   data.get("data") or data.get("items") or [])
        if not records:
            print(f"  Unknown dict shape, keys: {list(data.keys())}")
            return []
    else:
        print(f"  Unexpected type: {type(data)}")
        return []

    print(f"  {len(records)} country records returned")

    # Structure (XML→JSON):
    #   [ { COUNTRY_NAME, CITY: <city_or_list> }, ... ]
    #   CITY: { CITY_NAME, AGENTS: { AGENT: <agent_or_list> } }
    #   AGENT: { AGENT_NAME, AGENT_COUNTRY, CONTACT: { CONTACT_NAME,
    #            CONTACT_PHONE, CONTACT_EMAIL, CONTACT_ADDRESS, CONTACT_WEBSITE } }
    def as_list(val):
        """Normalise XML-to-JSON single-item vs multi-item fields."""
        if val is None:
            return []
        return val if isinstance(val, list) else [val]

    agents = []
    for country_rec in records:
        country_name = (country_rec.get("COUNTRY_NAME") or "").strip()

        for city_rec in as_list(country_rec.get("CITY")):
            city_name = (city_rec.get("CITY_NAME") or "").strip()

            for agent in as_list((city_rec.get("AGENTS") or {}).get("AGENT")):
                company = (agent.get("AGENT_NAME") or "").strip()
                if not company:
                    continue

                contact = agent.get("CONTACT") or {}
                # CONTACT may itself be a list (multiple contacts per agent)
                if isinstance(contact, list):
                    contact = contact[0] if contact else {}

                phone   = (contact.get("CONTACT_PHONE") or "").strip() or None
                email   = (contact.get("CONTACT_EMAIL") or "").strip() or None
                website = (contact.get("CONTACT_WEBSITE") or "").strip() or None
                address = (contact.get("CONTACT_ADDRESS") or "").strip() or None

                agents.append({
                    "company_name": company,
                    "country":      country_name,
                    "region":       "",
                    "city":         city_name,
                    "email":        email,
                    "phone":        phone,
                    "website":      website,
                    "address":      address,
                    "raw_text":     json.dumps(agent, ensure_ascii=False),
                    "source_url":   QUT_URL,
                })

    return agents


# ── Notre Dame ────────────────────────────────────────────────────────────────

# Country names used to infer country from embedded addresses
_COUNTRIES = {
    "Afghanistan", "Albania", "Algeria", "Argentina", "Armenia", "Australia",
    "Austria", "Azerbaijan", "Bahrain", "Bangladesh", "Belgium", "Bhutan",
    "Bolivia", "Brazil", "Cambodia", "Cameroon", "Canada", "Chile", "China",
    "Colombia", "Congo", "Croatia", "Cyprus", "Czech Republic", "Denmark",
    "Ecuador", "Egypt", "Ethiopia", "Finland", "France", "Georgia", "Germany",
    "Ghana", "Greece", "Guatemala", "Honduras", "Hong Kong", "Hungary", "India",
    "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Japan",
    "Jordan", "Kazakhstan", "Kenya", "Kosovo", "Kuwait", "Kyrgyzstan", "Laos",
    "Lebanon", "Libya", "Lithuania", "Luxembourg", "Malaysia", "Maldives",
    "Malta", "Mauritius", "Mexico", "Moldova", "Mongolia", "Morocco",
    "Mozambique", "Myanmar", "Nepal", "Netherlands", "New Zealand", "Nigeria",
    "Norway", "Oman", "Pakistan", "Palestine", "Panama", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia",
    "Rwanda", "Saudi Arabia", "Senegal", "Serbia", "Singapore", "Slovakia",
    "South Africa", "South Korea", "Spain", "Sri Lanka", "Sudan", "Sweden",
    "Switzerland", "Taiwan", "Tajikistan", "Tanzania", "Thailand", "Tunisia",
    "Turkey", "Turkiye", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "United States", "Uruguay", "Uzbekistan", "Venezuela",
    "Vietnam", "Yemen", "Zambia", "Zimbabwe",
}

NOTREDAME_URL = "https://www.notredame.edu.au/study/applications-and-admissions/how-to-apply/international-applicants/agents"


async def scrape_notredame(page: Page) -> list[dict]:
    """
    Notre Dame Australia is behind Cloudflare — Playwright passes the JS challenge.
    Agent data appears to be HTML-rendered (table or list); we monitor network calls
    for any JSON endpoint and fall back to DOM parsing.
    """
    captured_json: list[dict] = []

    async def capture_response(response):
        if response.status != 200:
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            data = await response.json()
            if isinstance(data, list) and data:
                print(f"    JSON API → {len(data)} records  ({response.url})")
                captured_json.extend(data)
            elif isinstance(data, dict):
                for key in ("agents", "results", "data", "items", "Results"):
                    if isinstance(data.get(key), list) and data[key]:
                        print(f"    JSON API ({key}) → {len(data[key])} records  ({response.url})")
                        captured_json.extend(data[key])
                        break
        except Exception:
            pass

    page.on("response", capture_response)

    print("  Navigating to Notre Dame agent page (Cloudflare may challenge) …")
    await page.goto(NOTREDAME_URL, wait_until="domcontentloaded", timeout=90_000)

    for _ in range(6):
        title = await page.title()
        if "just a moment" in title.lower() or "checking" in title.lower():
            print(f"    Cloudflare challenge ({title!r}) — waiting …")
            await page.wait_for_timeout(5_000)
        else:
            break

    await page.wait_for_timeout(3_000)
    print(f"  Page title: {await page.title()!r}")

    # If a JSON API was found during page load, try to parse it generically
    if captured_json:
        print(f"  Using {len(captured_json)} records from captured JSON API")
        agents = []
        for rec in captured_json:
            if not isinstance(rec, dict):
                continue
            name = (
                rec.get("name") or rec.get("Name") or rec.get("company") or
                rec.get("agent_name") or rec.get("agentName") or ""
            ).strip()
            if not name:
                continue
            agents.append({
                "company_name": name,
                "country":  (rec.get("country") or rec.get("Country") or "").strip(),
                "region":   "",
                "city":     (rec.get("city") or rec.get("City") or "").strip(),
                "email":    (rec.get("email") or rec.get("Email") or "").strip() or None,
                "phone":    (rec.get("phone") or rec.get("Phone") or "").strip() or None,
                "website":  (rec.get("website") or rec.get("Website") or "").strip() or None,
                "address":  (rec.get("address") or rec.get("Address") or "").strip() or None,
                "raw_text": json.dumps(rec, ensure_ascii=False),
                "source_url": NOTREDAME_URL,
            })
        return agents

    # Fall back to HTML parsing
    html_content = await page.content()
    soup = BeautifulSoup(html_content, "html.parser")

    # Debug: show page structure
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1","h2","h3","h4"])]
    print(f"  Headings: {headings[:10]}")

    # Check for iframe
    iframes = soup.find_all("iframe")
    for iframe in iframes:
        src = iframe.get("src", "")
        if src and "google" not in src:
            print(f"  IFRAME found: {src}")

    agents = []

    # Try table parsing
    # Notre Dame table columns: Agent Name | Country | Location | Contact
    #   Location = "City,Address"
    #   Contact  = "ContactName<email>Phone:<number>" all mashed together
    tables = soup.find_all("table")
    if tables:
        print(f"  Found {len(tables)} tables — trying table parse")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue
            # Detect header row
            header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th","td"])]
            has_agent_header = any("agent" in h or "name" in h for h in header_cells)
            if not has_agent_header and len(header_cells) < 2:
                continue
            for row in rows[1:]:  # skip header
                cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
                if len(cells) < 2:
                    continue
                # Column 0: Agent Name (strip icon chars like \uf08e)
                company = re.sub(r"[\uf000-\uf8ff]", "", cells[0]).strip()
                if not company:
                    continue
                country = cells[1].strip() if len(cells) > 1 else ""
                # Column 2: "City,Address[, Country]"
                location_raw = cells[2].strip() if len(cells) > 2 else ""
                city, address = "", None
                if location_raw:
                    parts = location_raw.split(",", 1)
                    city = parts[0].strip()
                    address = location_raw  # keep full as address
                    # Try to infer country from any segment matching known country names
                    if not country:
                        segs = [s.strip() for s in location_raw.replace("\n", ", ").split(",")]
                        for seg in reversed(segs):
                            if seg.title() in _COUNTRIES:
                                country = seg.title()
                                break
                # Column 3: contact name + email + phone
                contact_raw = cells[3].strip() if len(cells) > 3 else ""
                email_m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", contact_raw)
                phone_m = re.search(r"(?:Phone:|Tel:)\s*([\d\s\+\-\(\)]+)", contact_raw, re.I)
                email   = email_m.group(0).strip() if email_m else None
                phone   = phone_m.group(1).strip() if phone_m else None

                agents.append({
                    "company_name": company,
                    "country":  country,
                    "region":   "",
                    "city":     city,
                    "email":    email,
                    "phone":    phone,
                    "website":  None,
                    "address":  address,
                    "raw_text": " | ".join(cells),
                    "source_url": NOTREDAME_URL,
                })
        if agents:
            print(f"  Parsed {len(agents)} agents from table")
            return agents

    # Try accordion / definition list / card patterns
    # Look for country-heading → agent-list structure
    country = ""
    for el in soup.find_all(["h2","h3","h4","li","p","div"]):
        cls = " ".join(el.get("class", []))
        text = el.get_text(strip=True)
        if not text:
            continue
        if el.name in ("h2","h3","h4") and len(text) > 3 and len(text) < 60:
            country = text
            continue
        if country and el.name in ("li","p") and len(text) > 5:
            agents.append({
                "company_name": text[:200],
                "country":  country,
                "region":   "",
                "city":     "",
                "email":    None,
                "phone":    None,
                "website":  None,
                "address":  None,
                "raw_text": text,
                "source_url": NOTREDAME_URL,
            })

    print(f"  HTML fallback parsed {len(agents)} candidates")
    if agents:
        # Show first few
        for a in agents[:5]:
            print(f"    [{a['country']}] {a['company_name']}")
    return agents


# ── Database ──────────────────────────────────────────────────────────────────

def get_uni_id(conn: sqlite3.Connection, name_pattern: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM universities WHERE name LIKE ?", (f"%{name_pattern}%",)
    ).fetchone()
    return row[0] if row else None


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


# ── Runner ────────────────────────────────────────────────────────────────────

TARGETS = {
    "uwa":       ("University of Western Australia",  scrape_uwa),
    "qut":       ("Queensland University of Technology", scrape_qut),
    "notredame": ("Notre Dame",                        scrape_notredame),
}


async def run(targets: list[str], dry_run: bool) -> None:
    conn = sqlite3.connect(DB_PATH)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-AU",
        )

        for key in targets:
            name_fragment, scrape_fn = TARGETS[key]
            print(f"\n{'=' * 60}")
            print(f"  {name_fragment}")
            print(f"{'=' * 60}")

            uni_id = get_uni_id(conn, name_fragment)
            if not uni_id:
                print(f"  ERROR: '{name_fragment}' not found in universities table")
                continue

            page = await context.new_page()
            try:
                agents = await scrape_fn(page)
            except Exception as exc:
                import traceback
                print(f"  FATAL: {exc}")
                traceback.print_exc()
                await page.close()
                continue
            await page.close()

            # Summary
            by_country: dict[str, int] = {}
            for a in agents:
                by_country[a["country"]] = by_country.get(a["country"], 0) + 1
            for cname, n in sorted(by_country.items()):
                print(f"  {cname:35s}  {n:3d}")
            print(f"\n  Total parsed: {len(agents)}")

            if not dry_run and agents:
                deleted = conn.execute(
                    "DELETE FROM agents WHERE university_id = ?", (uni_id,)
                ).rowcount
                print(f"  Cleared {deleted} existing records")
                insert_agents(conn, uni_id, agents)
                conn.execute(
                    "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
                    (f"ok:playwright ({len(agents)})", datetime.now().isoformat(), uni_id),
                )
                conn.commit()
                print(f"  ✅ Written to DB")
            elif dry_run:
                print("  (dry run — no DB writes)")
            else:
                print("  (no agents found — DB unchanged)")

        await browser.close()
    conn.close()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--university", choices=list(TARGETS), help="Run one university only"
    )
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    args = parser.parse_args()

    targets = [args.university] if args.university else list(TARGETS)
    asyncio.run(run(targets, args.dry_run))


if __name__ == "__main__":
    main()
