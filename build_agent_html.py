#!/usr/bin/env python3
"""
build_agent_html.py — Regenerate the embedded JS data in agent-network.html
from the live agents.db database.

Updates:
  - ALL_DATA        per-country agent×university breakdown
  - GLOBAL_AGENTS   cross-country agent power-broker rankings
  - COUNTRIES_META  sidebar country list with counts
  - index.html      headline stats (agents / markets / unis)

Usage:
    python3 build_agent_html.py
    python3 build_agent_html.py --dry-run   # print new data only, no file writes
"""

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH      = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
REPO_DIR     = Path(__file__).parent
NETWORK_HTML  = REPO_DIR / "agent-network.html"
PROFILE_HTML  = REPO_DIR / "agent-profile.html"
REPORT_HTML   = REPO_DIR / "market-intelligence-report.html"
INDEX_HTML    = REPO_DIR / "index.html"
LOGO_DIR      = REPO_DIR / "Uni logos"

# Manual overrides where slug can't be cleanly derived from the DB name
UNI_SLUG_OVERRIDES = {
    "CQUniversity Australia":                    "cquniversity",
    "UNSW Sydney":                               "unsw-sydney",
    "University of Southern Queensland / UniSQ": "university-of-southern-queensland",
    "University of the Sunshine Coast / UniSC":  "university-of-the-sunshine-coast",
    "University of Notre Dame Australia":         "university-of-notre-dame-australia",
    "Batchelor Institute of Indigenous Tertiary Education": None,  # no logo
}

# Universities excluded from all counts (bad data / not real agents)
EXCLUDE_COMPANIES = {"Email:", "Phone:", "Address:"}

# Minimum agents per country to appear in the sidebar (noise filter)
MIN_AGENTS_IN_COUNTRY = 3

# ISO-2 → full country name (for UWA data which stores ISO codes)
ISO2_TO_NAME = {
    "AE": "United Arab Emirates", "AR": "Argentina",     "AT": "Austria",
    "AU": "Australia",            "BD": "Bangladesh",    "BE": "Belgium",
    "BH": "Bahrain",              "BN": "Brunei",        "BO": "Bolivia",
    "BR": "Brazil",               "BT": "Bhutan",        "BW": "Botswana",
    "CA": "Canada",               "CL": "Chile",         "CN": "China",
    "CO": "Colombia",             "CR": "Costa Rica",    "DE": "Germany",
    "DK": "Denmark",              "DO": "Dominican Republic", "DZ": "Algeria",
    "EC": "Ecuador",              "EG": "Egypt",         "ES": "Spain",
    "FJ": "Fiji",                 "FR": "France",        "GB": "United Kingdom",
    "GH": "Ghana",                "GR": "Greece",        "GT": "Guatemala",
    "HK": "Hong Kong",            "HN": "Honduras",      "ID": "Indonesia",
    "IN": "India",                "IQ": "Iraq",          "IR": "Iran",
    "IT": "Italy",                "JO": "Jordan",        "JP": "Japan",
    "KE": "Kenya",                "KH": "Cambodia",      "KR": "South Korea",
    "KW": "Kuwait",               "KZ": "Kazakhstan",    "LA": "Laos",
    "LB": "Lebanon",              "LK": "Sri Lanka",     "MM": "Myanmar",
    "MN": "Mongolia",             "MO": "Macau",         "MU": "Mauritius",
    "MV": "Maldives",             "MW": "Malawi",        "MX": "Mexico",
    "MY": "Malaysia",             "NC": "New Caledonia", "NG": "Nigeria",
    "NO": "Norway",               "NP": "Nepal",         "NZ": "New Zealand",
    "OM": "Oman",                 "PA": "Panama",        "PE": "Peru",
    "PH": "Philippines",          "PK": "Pakistan",      "PL": "Poland",
    "PY": "Paraguay",             "RE": "Réunion",       "RO": "Romania",
    "RU": "Russia",               "RW": "Rwanda",        "SA": "Saudi Arabia",
    "SE": "Sweden",               "SG": "Singapore",     "SV": "El Salvador",
    "TH": "Thailand",             "TR": "Turkey",        "TW": "Taiwan",
    "TZ": "Tanzania",             "UG": "Uganda",        "US": "United States",
    "UY": "Uruguay",              "UZ": "Uzbekistan",    "VE": "Venezuela",
    "VN": "Vietnam",              "ZA": "South Africa",  "ZM": "Zambia",
    "ZW": "Zimbabwe",
}


def normalise_country(raw: str) -> str:
    """Convert ISO-2 codes to full names; strip and title-case everything else."""
    s = (raw or "").strip()
    if len(s) == 2 and s.upper() in ISO2_TO_NAME:
        return ISO2_TO_NAME[s.upper()]
    return s


def load_data(conn: sqlite3.Connection):
    """
    Returns:
        uni_names   : {uni_id: name}
        agents_rows : list of (company_name, country, city, email, website, uni_id)
    """
    uni_names = {
        row[0]: row[1]
        for row in conn.execute("SELECT id, name FROM universities").fetchall()
    }

    rows = conn.execute("""
        SELECT COALESCE(parent_company, company_name) AS company_name,
               country, city, email, website, university_id
        FROM   agents
        WHERE  company_name IS NOT NULL
          AND  TRIM(company_name) != ''
        ORDER BY company_name
    """).fetchall()

    # Filter noise; normalise country codes
    clean = []
    for company, country, city, email, website, uni_id in rows:
        company = (company or "").strip()
        if company in EXCLUDE_COMPANIES:
            continue
        if re.match(r'^[\+\d\s\(\)\-]{5,}$', company):
            continue
        if len(company) <= 2:
            continue
        clean.append((company, normalise_country(country), city, email, website, uni_id))
    return uni_names, clean


def build_all_data(rows, uni_names):
    """
    ALL_DATA = {
      country: {
        agents: [ {name, city, email, website, unis:[uni_name,...]} ],
        universities: [uni_name, ...]
      }
    }
    Agents sorted by uni count desc; universities sorted alphabetically.
    For each (country, company_name) combo, pick best available contact info.
    """
    # Group by (country, company_name) → set of uni_names, best contact info
    agent_unis = defaultdict(set)      # (country, company) → {uni_name}
    agent_info = {}                    # (country, company) → {city, email, website}

    for company, country, city, email, website, uni_id in rows:
        country = (country or "").strip()
        if not country:
            continue
        key = (country, company)
        uni_name = uni_names.get(uni_id, "")
        if uni_name:
            agent_unis[key].add(uni_name)
        # Keep best available contact
        existing = agent_info.get(key, {})
        agent_info[key] = {
            "city":    existing.get("city") or (city or "").strip() or "",
            "email":   existing.get("email") or (email or "").strip() or "",
            "website": existing.get("website") or (website or "").strip() or "",
        }

    # Build per-country structure
    country_agents = defaultdict(list)
    for (country, company), unis in agent_unis.items():
        if len(unis) == 0:
            continue
        info = agent_info.get((country, company), {})
        country_agents[country].append({
            "name":    company,
            "city":    info.get("city", ""),
            "email":   info.get("email", ""),
            "website": info.get("website", ""),
            "parent":  company,   # no reliable parent data; use name as-is
            "unis":    sorted(unis),
        })

    all_data = {}
    for country, agents in sorted(country_agents.items()):
        if len(agents) < MIN_AGENTS_IN_COUNTRY:
            continue
        agents_sorted = sorted(agents, key=lambda a: -len(a["unis"]))
        all_unis = sorted({u for a in agents_sorted for u in a["unis"]})
        all_data[country] = {
            "agents":       agents_sorted,
            "universities": all_unis,
            "total_links":  sum(len(a["unis"]) for a in agents_sorted),
        }

    return all_data


def build_global_agents(rows, uni_names):
    """
    GLOBAL_AGENTS: agents ranked by (uni_count desc, country_count desc).
    For each unique company_name, aggregate across all countries + universities.
    Pick best contact info across all rows for that agent.
    """
    agent_unis      = defaultdict(set)    # company → {uni_name}
    agent_countries = defaultdict(set)    # company → {country}
    agent_info      = {}                  # company → {email, website}

    for company, country, city, email, website, uni_id in rows:
        country  = (country or "").strip()
        uni_name = uni_names.get(uni_id, "")
        if uni_name:
            agent_unis[company].add(uni_name)
        if country:
            agent_countries[company].add(country)
        existing = agent_info.get(company, {})
        agent_info[company] = {
            "email":   existing.get("email") or (email or "").strip() or "",
            "website": existing.get("website") or (website or "").strip() or "",
        }

    global_list = []
    for company, unis in agent_unis.items():
        countries = agent_countries[company]
        info = agent_info.get(company, {})
        global_list.append({
            "name":          company,
            "parent":        company,
            "uni_count":     len(unis),
            "country_count": len(countries),
            "countries":     sorted(countries),
            "universities":  sorted(unis),
            "email":         info.get("email", ""),
            "website":       info.get("website", ""),
        })

    global_list.sort(key=lambda a: (-a["uni_count"], -a["country_count"], a["name"]))
    return global_list


def build_countries_meta(all_data):
    """Sidebar list: [{name, agents, unis}] sorted by agent count desc."""
    meta = []
    for country, d in all_data.items():
        meta.append({
            "name":   country,
            "agents": len(d["agents"]),
            "unis":   len(d["universities"]),
        })
    meta.sort(key=lambda x: -x["agents"])
    return meta


def replace_js_const(html: str, const_name: str, new_value: str) -> str:
    """Replace a single-line JS const assignment (safe for unicode content)."""
    prefix = f"const {const_name} = "
    # Find the line and replace it entirely
    lines = html.split('\n')
    found = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{new_value};"
            found = True
            break
    if not found:
        raise ValueError(f"const {const_name} not found in HTML")
    return '\n'.join(lines)


def update_index_html(path: Path, total_agents: int, total_markets: int, total_unis: int):
    """Update the headline stats in index.html."""
    html = path.read_text()

    # Update the report card description
    desc_old = re.search(
        r'(Interactive intelligence across )[\d,]+ authorised education agents, '
        r'[\d]+ Australian universities, and [\d]+ markets\.',
        html
    )
    if desc_old:
        new_desc = (
            f'Interactive intelligence across {total_agents:,} authorised education agents, '
            f'{total_unis} Australian universities, and {total_markets} markets.'
        )
        html = html[:desc_old.start()] + new_desc + html[desc_old.end():]

    # Update the card-meta line  "X Markets · Y Agents"
    html = re.sub(
        r'<span>\d[\d,]* Markets</span>',
        f'<span>{total_markets} Markets</span>',
        html
    )
    html = re.sub(
        r'<span>[\d,]+ Agents</span>',
        f'<span>{total_agents:,} Agents</span>',
        html
    )

    path.write_text(html)
    print(f"  index.html updated: {total_agents:,} agents · {total_markets} markets · {total_unis} unis")


def uni_name_to_slug(name: str) -> str:
    """Derive logo filename slug from a university DB name."""
    if name in UNI_SLUG_OVERRIDES:
        return UNI_SLUG_OVERRIDES[name]
    s = name.lower()
    s = re.sub(r'\s*/.*$', '', s)          # drop "/ UniSQ" suffixes
    s = re.sub(r'[^a-z0-9\s-]', '', s)    # strip punctuation
    s = re.sub(r'\s+', '-', s.strip())     # spaces → hyphens
    return s


def build_uni_logos(uni_names: dict) -> dict:
    """
    Return {uni_name: relative_logo_path} for all universities.
    Value is None when no logo file is available.
    Paths are relative to agent-network.html (i.e. "Uni logos/slug.svg").
    """
    logos = {}
    for uni_name in uni_names.values():
        if not uni_name:
            continue
        slug = uni_name_to_slug(uni_name)
        if not slug:
            logos[uni_name] = None
            continue
        found = None
        for ext in (".svg", ".png"):
            candidate = LOGO_DIR / f"{slug}{ext}"
            if candidate.exists():
                # URL-encode the space in "Uni logos"
                found = f"Uni%20logos/{slug}{ext}"
                break
        logos[uni_name] = found
    return logos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    print("Loading agent data from DB …")
    uni_names, rows = load_data(conn)
    conn.close()
    print(f"  {len(rows):,} cleaned agent rows across {len(uni_names)} universities")

    print("Building ALL_DATA …")
    all_data = build_all_data(rows, uni_names)
    total_markets = len(all_data)
    total_agents_in_markets = sum(len(d["agents"]) for d in all_data.values())
    print(f"  {total_markets} countries, {total_agents_in_markets:,} unique agents in markets")

    print("Building GLOBAL_AGENTS …")
    global_agents = build_global_agents(rows, uni_names)
    print(f"  {len(global_agents):,} global agents")

    print("Building COUNTRIES_META …")
    countries_meta = build_countries_meta(all_data)

    # Stats for index.html
    # unique agents across all markets (distinct company names per country)
    total_agents = sum(len(d["agents"]) for d in all_data.values())
    total_unis   = len([u for u in uni_names.values() if u])  # all universities in DB

    if args.dry_run:
        print(f"\n[dry run] Would write:")
        print(f"  ALL_DATA:      {total_markets} countries, {sum(len(d['agents']) for d in all_data.values()):,} agents")
        print(f"  GLOBAL_AGENTS: {len(global_agents):,} agents")
        print(f"  COUNTRIES_META:{len(countries_meta)} countries")
        print(f"  index.html:    {total_agents:,} agents · {total_markets} markets · {total_unis} unis")
        top5 = global_agents[:5]
        print("\nTop 5 global agents:")
        for a in top5:
            print(f"  {a['name']:50s}  {a['uni_count']} unis · {a['country_count']} countries")
        return

    # ── Build UNI_LOGOS mapping ───────────────────────────────────────────────
    uni_logos = build_uni_logos(uni_names)
    print(f"  {sum(1 for v in uni_logos.values() if v)} of {len(uni_logos)} universities have logos")

    # ── Update agent-network.html ─────────────────────────────────────────────
    print(f"\nReading {NETWORK_HTML.name} …")
    html = NETWORK_HTML.read_text()

    print("Replacing UNI_LOGOS …")
    html = replace_js_const(html, "UNI_LOGOS", json.dumps(uni_logos, ensure_ascii=False, separators=(',', ':')))

    print("Replacing GLOBAL_AGENTS …")
    html = replace_js_const(html, "GLOBAL_AGENTS", json.dumps(global_agents, ensure_ascii=False, separators=(',', ':')))

    print("Replacing ALL_DATA …")
    html = replace_js_const(html, "ALL_DATA", json.dumps(all_data, ensure_ascii=False, separators=(',', ':')))

    print("Replacing COUNTRIES_META …")
    html = replace_js_const(html, "COUNTRIES_META", json.dumps(countries_meta, ensure_ascii=False, separators=(',', ':')))

    NETWORK_HTML.write_text(html)
    print(f"  ✅ {NETWORK_HTML.name} written ({len(html):,} bytes)")

    # ── Update agent-profile.html ─────────────────────────────────────────────
    print(f"\nReading {PROFILE_HTML.name} …")
    phtml = PROFILE_HTML.read_text()
    print("Replacing UNI_LOGOS in agent-profile …")
    phtml = replace_js_const(phtml, "UNI_LOGOS", json.dumps(uni_logos, ensure_ascii=False, separators=(',', ':')))
    PROFILE_HTML.write_text(phtml)
    print(f"  ✅ {PROFILE_HTML.name} written ({len(phtml):,} bytes)")

    # ── Update market-intelligence-report.html ────────────────────────────────
    print(f"\nReading {REPORT_HTML.name} …")
    rhtml = REPORT_HTML.read_text()
    print("Replacing ALL_DATA and UNI_LOGOS in market-intelligence-report …")
    rhtml = replace_js_const(rhtml, "ALL_DATA", json.dumps(all_data, ensure_ascii=False, separators=(',', ':')))
    rhtml = replace_js_const(rhtml, "UNI_LOGOS", json.dumps(uni_logos, ensure_ascii=False, separators=(',', ':')))
    REPORT_HTML.write_text(rhtml)
    print(f"  ✅ {REPORT_HTML.name} written ({len(rhtml):,} bytes)")

    # ── Update index.html ─────────────────────────────────────────────────────
    print(f"\nUpdating {INDEX_HTML.name} …")
    update_index_html(INDEX_HTML, total_agents, total_markets, total_unis)

    print("\nDone.")


if __name__ == "__main__":
    main()
