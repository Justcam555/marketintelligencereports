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
REPORT_HTML    = REPO_DIR / "market-intelligence-report.html"
MENTIONS_HTML  = REPO_DIR / "mentions-report.html"
INDEX_HTML     = REPO_DIR / "index.html"
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


_BKK_DISTRICTS = {
    "pathum wan","watthana","bang rak","ratchathewi","khlong toei",
    "chatuchak","huai khwang","silom","khan na yao","bang bon",
    "laksi","pathumwan","din daeng","bang phlat","lat phrao",
    "sathon","phra nakhon","pom prap sattru phai","samphanthawong",
    "bang sue","phaya thai","dusit","thawi watthana","taling chan",
    "bang khae","nong khaem","rat burana","thon buri","khlong san",
    "bangkok noi","bangkok yai","phra khanong","min buri","lat krabang",
    "bang na","bueng kum","saphan sung","wang thonglang","klong luang","klongluang",
}

def normalise_city(raw: str) -> str:
    """Collapse Bangkok districts to Bangkok, strip Mueang prefix."""
    c = (raw or "").strip()
    c = c.split("(")[0].strip()
    if c.lower().startswith("mueang "):
        c = c[7:].strip()
    if c.lower() in _BKK_DISTRICTS:
        c = "Bangkok"
    if c.lower() in ("thailand", ""):
        return ""
    return c


def load_data(conn: sqlite3.Connection):
    """
    Returns:
        uni_names   : {uni_id: name}
        agents_rows : list of (company_name, country, city, email, website, uni_id, canonical_name)
    """
    uni_names = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT id, name FROM universities WHERE COALESCE(country,'Australia') = 'Australia'"
        ).fetchall()
    }

    rows = conn.execute("""
        SELECT COALESCE(parent_company, company_name) AS company_name,
               country, city, email, website, university_id,
               COALESCE(canonical_name, company_name) AS canonical_name
        FROM   agents
        WHERE  company_name IS NOT NULL
          AND  TRIM(company_name) != ''
        ORDER BY company_name
    """).fetchall()

    # Filter noise; normalise country codes
    clean = []
    for company, country, city, email, website, uni_id, canonical in rows:
        company = (company or "").strip()
        if company in EXCLUDE_COMPANIES:
            continue
        if re.match(r'^[\+\d\s\(\)\-]{5,}$', company):
            continue
        if len(company) <= 2:
            continue
        clean.append((company, normalise_country(country), city, email, website, uni_id, (canonical or company).strip()))
    return uni_names, clean


def build_social_data(conn: sqlite3.Connection) -> dict:
    """
    SOCIAL_DATA = {country: {canonical_name: {presence_score, tiktok, facebook, instagram, youtube, google}}}
    Deduplicates by canonical_name per country — keeps row with highest presence_score.
    """
    rows = conn.execute("""
        SELECT country, canonical_name, presence_score,
               tiktok_followers, tiktok_total_views, tiktok_last_post, tiktok_engagement_rate,
               facebook_url, facebook_followers,
               instagram_handle, instagram_followers, ig_last_post,
               yt_subscribers, yt_total_views, yt_video_count,
               google_rating, google_reviews,
               line_oa_handle, line_oa_friends, line_oa_verified
        FROM agent_social
        WHERE canonical_name IS NOT NULL AND TRIM(canonical_name) != ''
        ORDER BY presence_score DESC
    """).fetchall()

    seen = {}   # (country, canonical_name) → best row
    for row in rows:
        country, name = row[0], row[1]
        if not country or not name:
            continue
        country = normalise_country(country)
        key = (country, name)
        if key not in seen:
            seen[key] = row

    social: dict = {}
    for (country, name), row in seen.items():
        (_, _, score,
         tt_fol, tt_views, tt_last, tt_eng,
         fb_url, fb_fol,
         ig_handle, ig_fol, ig_last,
         yt_subs, yt_views, yt_vids,
         g_rating, g_reviews,
         line_handle, line_friends, line_verified) = row

        if country not in social:
            social[country] = {}
        social[country][name] = {
            "presence_score": score,
            "tiktok": {
                "followers":        tt_fol,
                "total_views":      tt_views,
                "last_post":        tt_last,
                "engagement_rate":  tt_eng,
            },
            "facebook": {
                "url":       fb_url,
                "followers": fb_fol,
            },
            "instagram": {
                "handle":    ig_handle,
                "followers": ig_fol,
                "last_post": ig_last,
            },
            "youtube": {
                "subscribers": yt_subs,
                "total_views": yt_views,
                "videos":      yt_vids,
            },
            "google": {
                "rating":  g_rating,
                "reviews": g_reviews,
            },
            "line": {
                "handle":   line_handle,
                "friends":  line_friends,
                "verified": line_verified,
            },
        }

    return social


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
    agent_unis  = defaultdict(set)   # (country, company) → {uni_name}
    agent_cities = defaultdict(set)  # (country, company) → {city}
    agent_info  = {}                 # (country, company) → {email, website}
    agent_canonical = {}             # (country, company) → canonical_name

    for row in rows:
        company, country, city, email, website, uni_id = row[0], row[1], row[2], row[3], row[4], row[5]
        canonical = row[6] if len(row) > 6 else company
        country = (country or "").strip()
        if not country:
            continue
        key = (country, company)
        uni_name = uni_names.get(uni_id, "")
        if uni_name:
            agent_unis[key].add(uni_name)
        norm_city = normalise_city(city or "")
        if norm_city:
            agent_cities[key].add(norm_city)
        # Keep best available contact
        existing = agent_info.get(key, {})
        agent_info[key] = {
            "email":   existing.get("email") or (email or "").strip() or "",
            "website": existing.get("website") or (website or "").strip() or "",
        }
        if key not in agent_canonical:
            agent_canonical[key] = (canonical or company).strip()

    # Build per-country structure
    country_agents = defaultdict(list)
    for (country, company), unis in agent_unis.items():
        if len(unis) == 0:
            continue
        info = agent_info.get((country, company), {})
        cities = agent_cities.get((country, company), set())
        city_display = "Multiple" if len(cities) > 1 else (next(iter(cities)) if cities else "")
        country_agents[country].append({
            "name":      company,
            "canonical": agent_canonical.get((country, company), company),
            "city":      city_display,
            "email":     info.get("email", ""),
            "website":   info.get("website", ""),
            "parent":    company,   # no reliable parent data; use name as-is
            "unis":      sorted(unis),
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

    for row in rows:
        company, country, city, email, website, uni_id = row[0], row[1], row[2], row[3], row[4], row[5]
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


def build_social_index(conn: sqlite3.Connection) -> dict:
    """
    SOCIAL_INDEX = {canonical_name: {country: agent_social_id}}
    Used by agent-network.html to link directory rows to profile pages.
    Deduplicates by (canonical_name, country) — keeps highest presence_score,
    tiebreak by highest id (matches rebuild_profiles logic).
    """
    rows = conn.execute("""
        SELECT canonical_name, country, agent_id, COALESCE(presence_score, 0)
        FROM agent_social
        WHERE country IN ('Thailand','Nepal','Cambodia','Vietnam','Indonesia','Sri Lanka')
          AND canonical_name IS NOT NULL AND TRIM(canonical_name) != ''
        ORDER BY COALESCE(presence_score, 0) DESC, agent_id DESC
    """).fetchall()

    seen: dict = {}  # (canonical_name, country) → (score, sid)
    for name, country, sid, score in rows:
        key = (name, country)
        if key not in seen:
            seen[key] = (score, sid)

    index: dict = {}
    for (name, country), (_, sid) in seen.items():
        if name not in index:
            index[name] = {}
        index[name][country] = sid
    return index


def build_uk_data(conn: sqlite3.Connection) -> dict:
    """
    Build UK_DATA: per-market breakdown of UK university agents.
    Structure: {market: {universities: [...], agents: [{name, unis, website, email}]}}
    """
    uk_uni_ids = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT id, name FROM universities WHERE country = 'United Kingdom'"
        ).fetchall()
    }
    if not uk_uni_ids:
        return {}

    placeholders = ",".join("?" * len(uk_uni_ids))
    rows = conn.execute(f"""
        SELECT COALESCE(canonical_name, company_name) AS display_name,
               country, website, email, university_id, company_name
        FROM   agents
        WHERE  university_id IN ({placeholders})
          AND  company_name IS NOT NULL
          AND  TRIM(company_name) != ''
        ORDER  BY display_name
    """, list(uk_uni_ids.keys())).fetchall()

    # Build: market → canonical_name → {unis, website, email, raw_name}
    markets: dict = {}
    for display_name, country, website, email, uni_id, company_name in rows:
        uni_name = uk_uni_ids.get(uni_id, "")
        if not country or not uni_name:
            continue
        if country not in markets:
            markets[country] = {}
        key = (display_name or company_name).strip()
        if key not in markets[country]:
            markets[country][key] = {"unis": [], "website": website, "email": email}
        if uni_name not in markets[country][key]["unis"]:
            markets[country][key]["unis"].append(uni_name)

    # Convert to sorted lists
    result = {}
    for market, agent_map in sorted(markets.items()):
        all_unis = sorted({
            u for entry in agent_map.values() for u in entry["unis"]
        })
        agents = sorted(
            [
                {
                    "name": name,
                    "unis": sorted(entry["unis"]),
                    "website": entry["website"] or "",
                    "email": entry["email"] or "",
                }
                for name, entry in agent_map.items()
            ],
            key=lambda a: (-len(a["unis"]), a["name"].lower()),
        )
        result[market] = {"universities": all_unis, "agents": agents}

    return result


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
    print("Building SOCIAL_DATA …")
    social_data = build_social_data(conn)
    conn.close()
    print(f"  {len(rows):,} cleaned agent rows across {len(uni_names)} universities")
    total_social = sum(len(v) for v in social_data.values())
    print(f"  {total_social} agents with social data across {len(social_data)} countries")

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
    total_unis   = len([u for u in uni_names.values() if u])  # Australian universities only

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

    print("Replacing SOCIAL_INDEX …")
    conn2 = sqlite3.connect(DB_PATH)
    social_index = build_social_index(conn2)
    conn2.close()
    print(f"  {sum(len(v) for v in social_index.values())} country-agent entries across {len(social_index)} agents")
    html = replace_js_const(html, "SOCIAL_INDEX", json.dumps(social_index, ensure_ascii=False, separators=(',', ':')))

    print("Replacing UK_DATA …")
    conn3 = sqlite3.connect(DB_PATH)
    uk_data = build_uk_data(conn3)
    conn3.close()
    total_uk = sum(len(m["agents"]) for m in uk_data.values())
    print(f"  {total_uk} UK agent-country entries across {len(uk_data)} markets")
    html = replace_js_const(html, "UK_DATA", json.dumps(uk_data, ensure_ascii=False, separators=(',', ':')))

    NETWORK_HTML.write_text(html)
    print(f"  ✅ {NETWORK_HTML.name} written ({len(html):,} bytes)")

    # ── Update agent-profile.html ─────────────────────────────────────────────
    print(f"\nReading {PROFILE_HTML.name} …")
    phtml = PROFILE_HTML.read_text()
    print("Replacing UNI_LOGOS in agent-profile …")
    phtml = replace_js_const(phtml, "UNI_LOGOS", json.dumps(uni_logos, ensure_ascii=False, separators=(',', ':')))

    # Inject META_ADS_DATA — merge all country JSON files in mentions/data/processed/
    meta_ads_combined: dict = {}
    mentions_processed = REPO_DIR / "mentions" / "data" / "processed"
    for jf in sorted(mentions_processed.glob("meta_ads_*.json")):
        try:
            meta_ads_combined.update(json.load(open(jf, encoding="utf-8")))
            print(f"  Loaded Meta Ads: {jf.name}")
        except Exception as e:
            print(f"  Warning: could not load {jf.name}: {e}")
    phtml = replace_js_const(phtml, "META_ADS_DATA",
                             json.dumps(meta_ads_combined, ensure_ascii=False, separators=(',', ':')))

    # Inject AGENT_EVENTS — merge all agent_events_*.json files keyed by agent name
    agent_events_by_name: dict = {}
    events_processed = REPO_DIR / "data" / "processed"
    for jf in sorted(events_processed.glob("agent_events_*.json")):
        try:
            for record in json.load(open(jf, encoding="utf-8")):
                name = record.get("agent_name", "")
                if name and record.get("events"):
                    agent_events_by_name[name] = {
                        "events": record["events"],
                        "events_page_url": record.get("events_page_url", ""),
                    }
            print(f"  Loaded Agent Events: {jf.name}")
        except Exception as e:
            print(f"  Warning: could not load {jf.name}: {e}")
    phtml = replace_js_const(phtml, "AGENT_EVENTS",
                             json.dumps(agent_events_by_name, ensure_ascii=False, separators=(',', ':')))

    PROFILE_HTML.write_text(phtml)
    print(f"  ✅ {PROFILE_HTML.name} written ({len(phtml):,} bytes)")

    # ── Update mentions-report.html ───────────────────────────────────────────
    print(f"\nReading {MENTIONS_HTML.name} …")
    mhtml = MENTIONS_HTML.read_text()
    mhtml = replace_js_const(mhtml, "AGENT_EVENTS",
                             json.dumps(agent_events_by_name, ensure_ascii=False, separators=(',', ':')))
    MENTIONS_HTML.write_text(mhtml)
    print(f"  ✅ {MENTIONS_HTML.name} written ({len(mhtml):,} bytes)")

    # ── Update market-intelligence-report.html ────────────────────────────────
    print(f"\nReading {REPORT_HTML.name} …")
    rhtml = REPORT_HTML.read_text()
    print("Replacing ALL_DATA, SOCIAL_DATA and UNI_LOGOS in market-intelligence-report …")
    rhtml = replace_js_const(rhtml, "ALL_DATA",      json.dumps(all_data,             ensure_ascii=False, separators=(',', ':')))
    rhtml = replace_js_const(rhtml, "SOCIAL_DATA",   json.dumps(social_data,          ensure_ascii=False, separators=(',', ':')))
    rhtml = replace_js_const(rhtml, "UNI_LOGOS",     json.dumps(uni_logos,            ensure_ascii=False, separators=(',', ':')))
    rhtml = replace_js_const(rhtml, "AGENT_EVENTS",  json.dumps(agent_events_by_name, ensure_ascii=False, separators=(',', ':')))
    REPORT_HTML.write_text(rhtml)
    print(f"  ✅ {REPORT_HTML.name} written ({len(rhtml):,} bytes)")

    # ── Update index.html ─────────────────────────────────────────────────────
    print(f"\nUpdating {INDEX_HTML.name} …")
    update_index_html(INDEX_HTML, total_agents, total_markets, total_unis)

    print("\nDone.")


if __name__ == "__main__":
    main()
