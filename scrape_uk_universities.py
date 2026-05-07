#!/usr/bin/env python3
"""
scrape_uk_universities.py — Scrape authorised agents for 11 UK universities
across 6 priority markets: Thailand, Vietnam, Nepal, Indonesia, Sri Lanka, Cambodia.

Universities:
  bristol, warwick, bath, newcastle, exeter, lancaster, york, loughborough, swansea
  durham, cardiff  ← require Playwright (Cloudflare protected)

Usage:
    python3 scrape_uk_universities.py                            # all unis, all markets
    python3 scrape_uk_universities.py --university bristol       # one uni
    python3 scrape_uk_universities.py --country Thailand         # one market
    python3 scrape_uk_universities.py --dry-run                  # no DB writes
    python3 scrape_uk_universities.py --skip-playwright          # skip Durham + Cardiff
"""

import argparse
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error

from bs4 import BeautifulSoup, Tag

DB_PATH = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TARGET_COUNTRIES = {
    "Thailand":  "thailand",
    "Vietnam":   "vietnam",
    "Nepal":     "nepal",
    "Indonesia": "indonesia",
    "Sri Lanka": "sri-lanka",
    "Cambodia":  "cambodia",
}

# Countries whose Warwick page sits under /southasia/ instead of /seasia/
WARWICK_SOUTH_ASIA = {"nepal", "sri-lanka", "srilanka"}

UK_UNIVERSITIES = {
    "bristol": {
        "name": "University of Bristol",
        "website": "bristol.ac.uk",
        "agent_page_url": "https://www.bristol.ac.uk/international/countries/",
    },
    "warwick": {
        "name": "University of Warwick",
        "website": "warwick.ac.uk",
        "agent_page_url": "https://warwick.ac.uk/study/international/countryinformation/",
    },
    "bath": {
        "name": "University of Bath",
        "website": "bath.ac.uk",
        "agent_page_url": "https://www.bath.ac.uk/corporate-information/agents-representing-the-university-of-bath-in-asia/",
    },
    "newcastle": {
        "name": "Newcastle University",
        "website": "ncl.ac.uk",
        "agent_page_url": "https://www.ncl.ac.uk/international/country/",
    },
    "exeter": {
        "name": "University of Exeter",
        "website": "exeter.ac.uk",
        "agent_page_url": "https://www.exeter.ac.uk/international-students/university-agents/",
    },
    "lancaster": {
        "name": "Lancaster University",
        "website": "lancaster.ac.uk",
        "agent_page_url": "https://www.lancaster.ac.uk/study/international-students/find-an-agent/",
    },
    "york": {
        "name": "University of York",
        "website": "york.ac.uk",
        "agent_page_url": "https://www.york.ac.uk/study/international/your-country/",
    },
    "loughborough": {
        "name": "Loughborough University",
        "website": "lboro.ac.uk",
        "agent_page_url": "https://www.lboro.ac.uk/international/apply/educational-advisors/",
    },
    "swansea": {
        "name": "Swansea University",
        "website": "swansea.ac.uk",
        "agent_page_url": "https://www.swansea.ac.uk/international-students/our-agents/",
    },
    "durham": {
        "name": "Durham University",
        "website": "durham.ac.uk",
        "agent_page_url": "https://www.durham.ac.uk/study/international/studying-in-the-uk/agents-and-representatives/agents-by-region/",
    },
    "cardiff": {
        "name": "Cardiff University",
        "website": "cardiff.ac.uk",
        "agent_page_url": "https://www.cardiff.ac.uk/study/international/educational-advisors",
    },
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch_html(url: str, retries: int = 2) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"    HTTP {e.code} for {url}")
                return None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"    Error fetching {url}: {e}")
                return None


def get_soup(url: str) -> Optional[BeautifulSoup]:
    html = fetch_html(url)
    if html is None:
        return None
    return BeautifulSoup(html, "html.parser")


# ── Database ──────────────────────────────────────────────────────────────────

def ensure_universities(conn: sqlite3.Connection, dry_run: bool) -> dict[str, int]:
    """Insert UK universities if not present. Returns {slug: uni_id}."""
    uni_ids = {}
    for slug, info in UK_UNIVERSITIES.items():
        row = conn.execute(
            "SELECT id FROM universities WHERE name = ?", (info["name"],)
        ).fetchone()
        if row:
            uni_ids[slug] = row[0]
            print(f"  {info['name']} — already in DB (id={row[0]})")
        else:
            if not dry_run:
                cur = conn.execute(
                    """INSERT INTO universities (name, website, agent_page_url, country, scrape_status)
                       VALUES (?, ?, ?, 'United Kingdom', 'pending')""",
                    (info["name"], info["website"], info["agent_page_url"]),
                )
                uni_ids[slug] = cur.lastrowid
                print(f"  {info['name']} — inserted (id={cur.lastrowid})")
            else:
                uni_ids[slug] = -1
                print(f"  {info['name']} — would insert (dry run)")
    if not dry_run:
        conn.commit()
    return uni_ids


def insert_agents(
    conn: sqlite3.Connection,
    uni_id: int,
    agents: list[dict],
    dry_run: bool,
) -> int:
    if dry_run or not agents:
        return 0
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT OR IGNORE INTO agents
               (university_id, company_name, country, city, email, phone,
                website, address, raw_text, source_url, scraped_at)
           VALUES
               (:uni_id, :company_name, :country, :city, :email, :phone,
                :website, :address, :raw_text, :source_url, :scraped_at)""",
        [
            {
                **a,
                "uni_id": uni_id,
                "scraped_at": now,
                "raw_text": a.get("raw_text") or "",
            }
            for a in agents
        ],
    )
    conn.commit()
    return len(agents)


def make_agent(name: str, country: str, **kwargs) -> dict:
    return {
        "company_name": name.strip(),
        "country": country,
        "city": kwargs.get("city", ""),
        "email": kwargs.get("email"),
        "phone": kwargs.get("phone"),
        "website": kwargs.get("website"),
        "address": kwargs.get("address"),
        "source_url": kwargs.get("source_url", ""),
        "raw_text": kwargs.get("raw_text", ""),
    }


# ── Bristol ───────────────────────────────────────────────────────────────────
# Per-country static HTML. Agents in <ul> after <h2 id="agents">

def scrape_bristol(uni_id: int, countries: dict, dry_run: bool) -> int:
    total = 0
    for country, slug in countries.items():
        url = f"https://www.bristol.ac.uk/international/countries/{slug}.html"
        soup = get_soup(url)
        if soup is None:
            print(f"    {country}: page not found — skipping")
            continue

        agents_h2 = soup.find(id="agents")
        if not agents_h2:
            print(f"    {country}: no #agents section found")
            continue

        # Walk forward from the heading to find the <ul>
        ul = agents_h2.find_next("ul")
        if not ul:
            print(f"    {country}: no <ul> after #agents")
            continue

        agents = []
        for li in ul.find_all("li", recursive=False):
            name = li.get_text(separator=" ", strip=True)
            a_tag = li.find("a")
            website = a_tag["href"] if a_tag and a_tag.get("href") else None
            if name:
                agents.append(make_agent(name, country, website=website, source_url=url))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
        time.sleep(0.5)
    return total


# ── Warwick ───────────────────────────────────────────────────────────────────
# Per-country static HTML. Agents as <a> links in prose under <h5>Applying to Warwick</h5>.
# Exclude non-agent links (warwick.ac.uk, educationuk.org, britishcouncil, ucas, etc.)

WARWICK_EXCLUDE_DOMAINS = {
    "warwick.ac.uk", "educationuk.org", "britishcouncil.org", "ucas.com",
    "ielts.org", "ukcisa.org.uk", "gov.uk", "ukcisa", "visa",
}


def warwick_slug(country_slug: str) -> tuple[str, str]:
    """Return (region, slug) for Warwick URL."""
    if country_slug in WARWICK_SOUTH_ASIA or country_slug == "sri-lanka":
        region = "southasia"
        # Warwick uses 'srilanka' not 'sri-lanka'
        slug = "srilanka" if country_slug == "sri-lanka" else country_slug
    else:
        region = "seasia"
        slug = country_slug
    return region, slug


def scrape_warwick(uni_id: int, countries: dict, dry_run: bool) -> int:
    total = 0
    for country, slug in countries.items():
        region, wslug = warwick_slug(slug)
        url = f"https://warwick.ac.uk/study/international/countryinformation/{region}/{wslug}/"
        soup = get_soup(url)
        if soup is None:
            print(f"    {country}: page not found — skipping")
            continue

        # Find <h5> containing "Applying to Warwick"
        heading = soup.find(lambda t: t.name in ("h5", "h4", "h3", "h2")
                            and "applying to warwick" in t.get_text().lower())
        if not heading:
            print(f"    {country}: no 'Applying to Warwick' section")
            continue

        # Grab the next sibling <p> element(s)
        agents = []
        node = heading.find_next_sibling()
        while node and node.name in ("p", "ul"):
            for a in node.find_all("a", href=True):
                href = a["href"]
                name = a.get_text(strip=True)
                # Skip known non-agent links
                if any(d in href for d in WARWICK_EXCLUDE_DOMAINS):
                    continue
                # Skip very short names (navigation artifacts)
                if len(name) < 3:
                    continue
                # Skip if the link text looks like a generic description
                if any(kw in name.lower() for kw in ["education uk", "british council", "ucas"]):
                    continue
                agents.append(make_agent(name, country, website=href, source_url=url))
            node = node.find_next_sibling()

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
        time.sleep(0.5)
    return total


# ── Bath ──────────────────────────────────────────────────────────────────────
# Single Asia page. Each country has <h1 id="{slug}"> then <table> with columns
# Agent | Website | Email

BATH_URL = "https://www.bath.ac.uk/corporate-information/agents-representing-the-university-of-bath-in-asia/"


def scrape_bath(uni_id: int, countries: dict, dry_run: bool) -> int:
    soup = get_soup(BATH_URL)
    if soup is None:
        print("    Bath Asia page unreachable")
        return 0

    total = 0
    for country, slug in countries.items():
        # Bath uses the country name as anchor id (lowercase, hyphenated)
        heading = soup.find(id=slug)
        if not heading:
            # Try alternate forms
            for alt in [slug.replace("-", ""), country.lower(), country.lower().replace(" ", "-")]:
                heading = soup.find(id=alt)
                if heading:
                    break
        if not heading:
            print(f"    {country}: no anchor found in Bath page")
            continue

        table = heading.find_next("table")
        if not table:
            print(f"    {country}: no table after heading")
            continue

        agents = []
        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header row
            cells = row.find_all("td")
            if len(cells) < 1:
                continue
            name = cells[0].get_text(strip=True)
            website = None
            email = None
            if len(cells) > 1:
                a = cells[1].find("a")
                if a:
                    website = a.get("href", "").strip()
            if len(cells) > 2:
                a = cells[2].find("a")
                if a:
                    email = a.get("href", "").replace("mailto:", "").strip()
            if name:
                agents.append(make_agent(
                    name, country, website=website, email=email, source_url=BATH_URL
                ))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)

    return total


# ── Newcastle ─────────────────────────────────────────────────────────────────
# Per-country page. Agents in <details class="accordionBanner"> →
# <div class="accordionContent"> → <p><strong>Name</strong></p> + <ul> details.

def parse_newcastle_agents(soup: BeautifulSoup, country: str, url: str) -> list[dict]:
    # There are multiple accordionBanner elements; find the one for agents
    details = None
    for d in soup.find_all("details", class_="accordionBanner"):
        summary = d.find("summary")
        if summary and "education agent" in summary.get_text().lower():
            details = d
            break
    if not details:
        return []
    content = details.find("div", class_="accordionContent")
    if not content:
        return []

    agents = []
    # Walk paragraphs — each agent starts with a <p> containing <strong>
    paragraphs = content.find_all("p")
    for p in paragraphs:
        strong = p.find("strong")
        if not strong:
            continue
        name = strong.get_text(strip=True)
        if not name or len(name) < 3:
            continue

        # Website from <a> wrapping the <strong>
        a_tag = strong.find_parent("a")
        website = a_tag["href"].strip() if a_tag and a_tag.get("href") else None

        # Gather contact info from the sibling <ul> immediately after
        email = phone = address = None
        ul = p.find_next_sibling("ul")
        if ul:
            for li in ul.find_all("li"):
                text = li.get_text(separator=" ", strip=True)
                a = li.find("a", href=True)
                if a and a["href"].startswith("mailto:"):
                    email = a["href"].replace("mailto:", "").strip()
                elif "Tel:" in text or "Phone:" in text:
                    phone = re.sub(r"(?i)Tel:|Phone:", "", text).strip()
                elif "Address:" in text:
                    address = re.sub(r"(?i)Address:", "", text).strip()

        agents.append(make_agent(
            name, country,
            website=website, email=email, phone=phone, address=address,
            source_url=url,
        ))
    return agents


def scrape_newcastle(uni_id: int, countries: dict, dry_run: bool) -> int:
    total = 0
    for country, slug in countries.items():
        url = f"https://www.ncl.ac.uk/international/country/{slug}/"
        soup = get_soup(url)
        if soup is None:
            print(f"    {country}: page not found — skipping")
            continue

        agents = parse_newcastle_agents(soup, country, url)
        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
        time.sleep(0.5)
    return total


# ── Exeter ────────────────────────────────────────────────────────────────────
# Per-country page. Agents in <ul class="menu responsive-list"> after <a id="agents">.

def scrape_exeter(uni_id: int, countries: dict, dry_run: bool) -> int:
    total = 0
    for country, slug in countries.items():
        url = f"https://www.exeter.ac.uk/international-students/{slug}/"
        soup = get_soup(url)
        if soup is None:
            print(f"    {country}: page not found — skipping")
            continue

        # Find <a id="agents"> anchor
        anchor = soup.find(id="agents")
        if not anchor:
            print(f"    {country}: no #agents anchor")
            continue

        # Agent list is the first <ul> directly after the anchor (before any heading)
        ul = anchor.find_next("ul")
        if not ul:
            print(f"    {country}: no agent list")
            continue

        agents = []
        for li in ul.find_all("li", recursive=False):
            name = li.get_text(separator=" ", strip=True)
            a_tag = li.find("a")
            website = a_tag["href"].strip() if a_tag and a_tag.get("href") else None
            if name:
                agents.append(make_agent(name, country, website=website, source_url=url))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
        time.sleep(0.5)
    return total


# ── Lancaster ─────────────────────────────────────────────────────────────────
# Single page. Structure: <h3><button>Country</button></h3> → <div class="accordion-content"> → <ul>

LANCASTER_URL = "https://www.lancaster.ac.uk/study/international-students/find-an-agent/"


def scrape_lancaster(uni_id: int, countries: dict, dry_run: bool) -> int:
    soup = get_soup(LANCASTER_URL)
    if soup is None:
        print("    Lancaster page unreachable")
        return 0

    total = 0
    for country, slug in countries.items():
        # Find <button> whose text matches the country name
        btn = soup.find(
            "button",
            string=lambda s: s and country.lower() in s.lower()
        )
        if not btn:
            # Try by id pattern like "thailand-..."
            div = soup.find("div", id=lambda x: x and slug in x.lower())
            if div:
                ul = div.find("ul")
            else:
                print(f"    {country}: not found in Lancaster page")
                continue
        else:
            # The accordion content is the next sibling div
            h3 = btn.find_parent("h3") or btn.find_parent("h2")
            content_div = h3.find_next_sibling("div") if h3 else btn.find_next("div")
            ul = content_div.find("ul") if content_div else None

        if not ul:
            print(f"    {country}: no agent list")
            continue

        agents = []
        for li in ul.find_all("li"):
            name = li.get_text(separator=" ", strip=True)
            a_tag = li.find("a")
            website = a_tag["href"].strip() if a_tag and a_tag.get("href") else None
            if name:
                agents.append(make_agent(name, country, website=website,
                                         source_url=LANCASTER_URL))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)

    return total


# ── York ──────────────────────────────────────────────────────────────────────
# Per-country page. Agents in <div class="uoy_accordion_content"> after
# <summary>Agent Representatives</summary>.

def scrape_york(uni_id: int, countries: dict, dry_run: bool) -> int:
    total = 0
    for country, slug in countries.items():
        url = f"https://www.york.ac.uk/study/international/your-country/{slug}/"
        soup = get_soup(url)
        if soup is None:
            print(f"    {country}: page not found — skipping")
            continue

        # Find <summary> containing "Agent Representatives"
        summary = soup.find(
            "summary",
            string=lambda s: s and "agent" in s.lower() and "representative" in s.lower(),
        )
        if not summary:
            # Try broader search
            summary = soup.find(lambda t: t.name == "summary"
                                and "agent" in t.get_text().lower())
        if not summary:
            print(f"    {country}: no 'Agent Representatives' section")
            continue

        content = summary.find_next_sibling("div")
        if not content:
            print(f"    {country}: no accordion content")
            continue

        ul = content.find("ul")
        if not ul:
            print(f"    {country}: no agent list")
            continue

        agents = []
        for li in ul.find_all("li"):
            name = li.get_text(separator=" ", strip=True)
            a_tag = li.find("a")
            website = a_tag["href"].strip() if a_tag and a_tag.get("href") else None
            if name:
                agents.append(make_agent(name, country, website=website, source_url=url))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
        time.sleep(0.5)
    return total


# ── Loughborough ──────────────────────────────────────────────────────────────
# Single page. Agent cards: <div class="agent {country-slug} ...">
# Name in <span class="agent--content agent--content-name">

LOUGHBOROUGH_URL = "https://www.lboro.ac.uk/international/apply/educational-advisors/"


def scrape_loughborough(uni_id: int, countries: dict, dry_run: bool) -> int:
    soup = get_soup(LOUGHBOROUGH_URL)
    if soup is None:
        print("    Loughborough page unreachable")
        return 0

    total = 0
    for country, slug in countries.items():
        # Cards have class "agent {slug}" (may also have city variant classes)
        cards = soup.find_all("div", class_=lambda c: c and "agent" in c.split()
                              and slug in c.split())
        if not cards:
            print(f"    {country}: no agent cards found (class='agent {slug}')")
            continue

        agents = []
        seen = set()
        for card in cards:
            name_span = card.find("span", class_="agent--content-name")
            if not name_span:
                continue
            name = name_span.get_text(strip=True)
            if not name or name in seen:
                continue
            seen.add(name)

            email_span = card.find("span", class_="agent--content-email")
            email = email_span.get_text(strip=True) if email_span else None

            phone_span = card.find("span", class_="agent--content-phone")
            phone = phone_span.get_text(strip=True) if phone_span else None

            # Website: look for external link
            a_tag = card.find("a", href=lambda h: h and h.startswith("http"))
            website = a_tag["href"].strip() if a_tag else None

            city_span = card.find("span", class_="agent--content-city")
            city = city_span.get_text(strip=True) if city_span else None

            agents.append(make_agent(
                name, country,
                email=email, phone=phone, website=website, city=city,
                source_url=LOUGHBOROUGH_URL,
            ))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)

    return total


# ── Swansea ───────────────────────────────────────────────────────────────────
# Single page. Regional tables: "South East Asia" and "South Asia".
# Each table row: Agency Name | Countries/Regions
# Filter rows where Countries/Regions contains the target country.

SWANSEA_URL = "https://www.swansea.ac.uk/international-students/our-agents/"

SWANSEA_REGIONS = {
    "Thailand":  "South East Asia",
    "Vietnam":   "South East Asia",
    "Indonesia": "South East Asia",
    "Cambodia":  "South East Asia",
    "Nepal":     "South Asia",
    "Sri Lanka": "South Asia",
}


def scrape_swansea(uni_id: int, countries: dict, dry_run: bool) -> int:
    soup = get_soup(SWANSEA_URL)
    if soup is None:
        print("    Swansea page unreachable")
        return 0

    # Build a map of region_name → table soup
    region_tables: dict[str, BeautifulSoup] = {}
    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(strip=True)
        table = heading.find_next("table")
        if table:
            region_tables[text.lower()] = table

    total = 0
    for country, _ in countries.items():
        region = SWANSEA_REGIONS.get(country, "")
        region_key = region.lower()

        table = None
        for key, tbl in region_tables.items():
            if region_key in key:
                table = tbl
                break

        if not table:
            print(f"    {country}: no table found for region '{region}'")
            continue

        agents = []
        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            name_cell = cells[0]
            countries_cell = cells[1]
            countries_text = countries_cell.get_text(separator=" ", strip=True)

            # Check if this agent covers our target country or is Global
            if (country.lower() in countries_text.lower()
                    or "global" in countries_text.lower()):
                name = name_cell.get_text(strip=True)
                a_tag = name_cell.find("a")
                website = a_tag["href"].strip() if a_tag and a_tag.get("href") else None
                if name:
                    agents.append(make_agent(
                        name, country,
                        website=website, source_url=SWANSEA_URL,
                        raw_text=f"Countries: {countries_text}",
                    ))

        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)

    return total


# ── Durham (Playwright) ───────────────────────────────────────────────────────
# Cloudflare protected. Single page with agents grouped by region.

DURHAM_URL = "https://www.durham.ac.uk/study/international/studying-in-the-uk/agents-and-representatives/agents-by-region/"

DURHAM_REGIONS = {
    "Thailand":  ["south east asia", "southeast asia"],
    "Vietnam":   ["south east asia", "southeast asia"],
    "Indonesia": ["south east asia", "southeast asia"],
    "Cambodia":  ["south east asia", "southeast asia"],
    "Nepal":     ["south asia"],
    "Sri Lanka": ["south asia"],
}


def scrape_durham_from_html(html: str, countries: dict) -> dict[str, list[dict]]:
    """
    Parse Durham agents page HTML. Returns {country: [agents]}.

    Structure: <h4>Region</h4> → <table> with Country | Agent columns.
    Countries use rowspan — the country cell spans N rows; subsequent rows
    contain only one cell (the agent name). Track current_country across rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: dict[str, list[dict]] = {c: [] for c in countries}

    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(strip=True).lower()
        applicable_countries = [
            c for c, region_kws in DURHAM_REGIONS.items()
            if any(kw in heading_text for kw in region_kws)
        ]
        if not applicable_countries:
            continue

        table = heading.find_next_sibling("table")
        if not table:
            continue

        current_country = None   # matched target country name
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            if len(cells) == 2:
                # New country row: cells[0] = country, cells[1] = first agent
                country_text = cells[0].get_text(separator=" ", strip=True).strip("\xa0")
                # Skip header row
                if country_text.lower() in ("country", ""):
                    continue
                # Match against our target countries
                current_country = None
                for c in applicable_countries:
                    if c.lower() in country_text.lower():
                        current_country = c
                        break
                agent_cell = cells[1]

            elif len(cells) == 1:
                # Continuation row: only agent cell, country came from rowspan above
                agent_cell = cells[0]

            else:
                continue

            if current_country is None:
                continue

            # Extract agent name and website from the agent cell
            name = agent_cell.get_text(separator=" ", strip=True).strip("\xa0").strip()
            if not name or len(name) < 3:
                continue
            a_tag = agent_cell.find("a", href=True)
            website = a_tag["href"].strip() if a_tag else None

            results[current_country].append(make_agent(
                name, current_country, website=website, source_url=DURHAM_URL
            ))

    return results


async def scrape_durham_playwright(uni_id: int, countries: dict, dry_run: bool) -> int:
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        print("    Durham: playwright/playwright-stealth not installed — skipping")
        return 0

    html = None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        ctx = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)
        try:
            print(f"    Navigating to Durham agents page …")
            await page.goto(DURHAM_URL, wait_until="load", timeout=60_000)
            await page.wait_for_timeout(4_000)
            html = await page.content()
        except Exception as e:
            print(f"    Durham Playwright error: {e}")
        finally:
            await browser.close()

    if not html:
        return 0

    results = scrape_durham_from_html(html, countries)
    total = 0
    for country, agents in results.items():
        print(f"    {country}: {len(agents)} agents")
        total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
    return total


# ── Cardiff (Playwright) ──────────────────────────────────────────────────────
# Cloudflare protected. Per-country URLs.

CARDIFF_COUNTRIES = {
    "Thailand":  "thailand",
    "Vietnam":   "vietnam",
    "Nepal":     "nepal",
    "Indonesia": "indonesia",
    "Sri Lanka": "sri-lanka",
    "Cambodia":  "cambodia",
}


def parse_cardiff_agents(soup: BeautifulSoup, country: str, url: str) -> list[dict]:
    """
    Cardiff page structure:
      <h1>Advisors in {Country}</h1>
      <div>intro paragraph</div>
      <div id="content_container_..."><ul><li><a>Agent Name</a></li>...</ul></div>
    """
    agents = []
    h1 = soup.find("h1", string=lambda s: s and "advisor" in s.lower())
    if not h1:
        return agents

    # Walk siblings to find a <div> containing a <ul> with agent links
    node = h1.find_next_sibling()
    while node:
        if node.name == "div":
            ul = node.find("ul")
            if ul:
                for li in ul.find_all("li"):
                    a_tag = li.find("a")
                    name = li.get_text(strip=True)
                    # Skip the "contact us" link and other nav items
                    if (not name or len(name) < 3
                            or "contact us" in name.lower()
                            or "cardiff.ac.uk" in (a_tag["href"] if a_tag else "")):
                        continue
                    website = a_tag["href"].strip() if a_tag else None
                    agents.append(make_agent(name, country, website=website, source_url=url))
                if agents:
                    break  # found the right div
        elif node.name in ("h2", "h3"):
            break  # moved past the advisor section
        node = node.find_next_sibling()

    return agents


async def scrape_cardiff_playwright(uni_id: int, countries: dict, dry_run: bool) -> int:
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        print("    Cardiff: playwright/playwright-stealth not installed — skipping")
        return 0

    total = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        ctx = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)

        for country, slug in countries.items():
            cardiff_slug = CARDIFF_COUNTRIES.get(country, slug)
            url = f"https://www.cardiff.ac.uk/study/international/your-country/asia/{cardiff_slug}/advisors"
            try:
                await page.goto(url, wait_until="load", timeout=30_000)
                await page.wait_for_timeout(3_000)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                agents = parse_cardiff_agents(soup, country, url)
                print(f"    {country}: {len(agents)} agents")
                total += insert_agents(conn_ref[0], uni_id, agents, dry_run)
            except Exception as e:
                print(f"    Cardiff {country}: {e}")
            time.sleep(1)

        await browser.close()
    return total


# ── Dispatch ──────────────────────────────────────────────────────────────────

SCRAPERS = {
    "bristol":      scrape_bristol,
    "warwick":      scrape_warwick,
    "bath":         scrape_bath,
    "newcastle":    scrape_newcastle,
    "exeter":       scrape_exeter,
    "lancaster":    scrape_lancaster,
    "york":         scrape_york,
    "loughborough": scrape_loughborough,
    "swansea":      scrape_swansea,
}

PLAYWRIGHT_SCRAPERS = {
    "durham":  scrape_durham_playwright,
    "cardiff": scrape_cardiff_playwright,
}

# Ugly but necessary — share conn across module-level scraper functions
conn_ref: list[sqlite3.Connection] = [None]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape UK university agents for 6 priority markets")
    parser.add_argument("--university", help="Slug of one university to scrape (e.g. bristol)")
    parser.add_argument("--country", help="One country to scrape (e.g. Thailand)")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    parser.add_argument("--skip-playwright", action="store_true",
                        help="Skip Durham + Cardiff (require Playwright)")
    args = parser.parse_args()

    # Filter countries
    if args.country:
        if args.country not in TARGET_COUNTRIES:
            print(f"Unknown country: {args.country}. Choose from: {', '.join(TARGET_COUNTRIES)}")
            return
        countries = {args.country: TARGET_COUNTRIES[args.country]}
    else:
        countries = TARGET_COUNTRIES

    # Filter universities
    all_scrapers = {**SCRAPERS}
    if not args.skip_playwright:
        all_scrapers.update({k: None for k in PLAYWRIGHT_SCRAPERS})  # placeholder
    if args.university:
        slug = args.university.lower()
        if slug not in UK_UNIVERSITIES:
            print(f"Unknown university: {slug}. Choose from: {', '.join(UK_UNIVERSITIES)}")
            return
        unis_to_run = [slug]
    else:
        unis_to_run = list(UK_UNIVERSITIES.keys())

    conn = sqlite3.connect(DB_PATH)
    conn_ref[0] = conn

    print("=== Setting up UK university records ===")
    uni_ids = ensure_universities(conn, args.dry_run)
    print()

    grand_total = 0
    for slug in unis_to_run:
        info = UK_UNIVERSITIES[slug]
        uni_id = uni_ids.get(slug, -1)
        print(f"=== {info['name']} ===")

        if slug in PLAYWRIGHT_SCRAPERS and not args.skip_playwright:
            import asyncio
            fn = PLAYWRIGHT_SCRAPERS[slug]
            n = asyncio.run(fn(uni_id, countries, args.dry_run))
        elif slug in SCRAPERS:
            fn = SCRAPERS[slug]
            n = fn(uni_id, countries, args.dry_run)
        else:
            print(f"  Skipped (requires Playwright — use without --skip-playwright)")
            n = 0

        if not args.dry_run:
            conn.execute(
                "UPDATE universities SET scrape_status = ?, last_scraped = ? WHERE id = ?",
                (f"ok:uk_scraper ({n})", datetime.now().isoformat(), uni_id),
            )
            conn.commit()

        grand_total += n
        print(f"  → {n} agents inserted\n")

    conn.close()

    if args.dry_run:
        print("(dry run — no DB writes)")
    else:
        print(f"✅ Done. {grand_total} total agent rows inserted across {len(unis_to_run)} universities.")


if __name__ == "__main__":
    main()
