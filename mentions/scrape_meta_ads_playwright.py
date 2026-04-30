#!/usr/bin/env python3
"""
scrape_meta_ads_playwright.py

Scrapes the Meta Ad Library for all 6 markets using a real Playwright/Chromium
browser. First resolves each agent's numeric Facebook page ID (cached to JSON),
then queries the ad library with view_all_page_id — no keyword bleed.

Usage:
    python3 mentions/scrape_meta_ads_playwright.py                 # all 6 markets
    python3 mentions/scrape_meta_ads_playwright.py --headless
    python3 mentions/scrape_meta_ads_playwright.py --market Thailand
    python3 mentions/scrape_meta_ads_playwright.py --resolve-ids-only  # cache IDs, no ad scrape
    python3 mentions/scrape_meta_ads_playwright.py --slug AECCThailand --market Thailand
"""

import argparse
import asyncio
import csv
import json
import re
import sqlite3
import urllib.parse
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

REPO_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

MARKETS = {
    "Thailand":  "TH",
    "Nepal":     "NP",
    "Cambodia":  "KH",
    "Vietnam":   "VN",
    "Indonesia": "ID",
    "Sri Lanka": "LK",
}

MAX_ADS      = 25
LOAD_WAIT    = 5_000   # ms after domcontentloaded
ID_WAIT      = 2_500   # ms when resolving page IDs
PAGE_TIMEOUT = 30_000

OUTPUT_DIR    = REPO_DIR / "mentions" / "data" / "raw"
DEBUG_DIR     = OUTPUT_DIR / "debug_screenshots"
PAGE_ID_CACHE = OUTPUT_DIR / "fb_page_id_cache.json"

ALIAS_FILE = Path(__file__).parent / "university_alias_table_v2.xlsx"

# ── University alias loader ───────────────────────────────────────────────────

def load_uni_aliases():
    """
    Returns list of (canonical_name, alias) pairs from the alias Excel file,
    sorted longest alias first so longer matches win over shorter ones.
    Falls back to hardcoded list if file not available.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(ALIAS_FILE, read_only=True, data_only=True)
        ws = wb.active
        pairs = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            canonical, alias = row[0], row[1]
            if canonical and alias:
                pairs.append((str(canonical).strip(), str(alias).strip()))
        wb.close()
        # Sort longest alias first so "Macquarie University" wins over "Macquarie"
        pairs.sort(key=lambda x: -len(x[1]))
        return pairs
    except Exception:
        pass
    # Fallback
    names = [
        "Monash University","University of Melbourne","RMIT University",
        "Deakin University","Swinburne University","La Trobe University",
        "UNSW Sydney","UTS","Macquarie University","University of Wollongong",
        "University of Newcastle","ANU","University of Canberra","ACU",
        "Charles Sturt University","Charles Darwin University","CQU",
        "Southern Cross University","Griffith University","QUT","Bond University",
        "JCU","USQ","University of the Sunshine Coast","Murdoch University",
        "Curtin University","ECU","Edith Cowan University","Flinders University",
        "University of Adelaide","UniSA","University of Tasmania",
        "Federation University","Torrens University","Victoria University",
    ]
    return [(n, n) for n in names]

UNI_ALIASES = load_uni_aliases()

# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_id_cache():
    if PAGE_ID_CACHE.exists():
        return json.loads(PAGE_ID_CACHE.read_text())
    return {}


def save_id_cache(cache):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGE_ID_CACHE.write_text(json.dumps(cache, indent=2))

# ── DB loader ─────────────────────────────────────────────────────────────────

def slug_from_url(url):
    if not url:
        return None
    url = url.rstrip("/")
    slug = url.split("facebook.com/")[-1].split("?")[0].split("/")[0]
    if slug.lower() in ("", "pg", "media", "pages", "profile.php", "groups"):
        return None
    return slug


def load_agents_from_db(country):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT canonical_name, facebook_url
        FROM agent_social
        WHERE country = ?
          AND facebook_url IS NOT NULL
          AND TRIM(facebook_url) != ''
        ORDER BY COALESCE(presence_score, 0) DESC, agent_id DESC
    """, (country,)).fetchall()
    conn.close()

    seen_urls = set()
    agents = []
    for name, url in rows:
        url = (url or "").strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        slug = slug_from_url(url)
        if not slug:
            continue
        agents.append((name, slug, url))
    return agents

# ── URL builder ───────────────────────────────────────────────────────────────

def ad_library_url(slug, page_id, country_code):
    if page_id:
        return (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all&country={country_code}"
            f"&view_all_page_id={page_id}"
        )
    q = urllib.parse.quote_plus(slug)
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={country_code}"
        f"&search_type=page&q={q}"
    )

# ── Page ID resolver ──────────────────────────────────────────────────────────

# Patterns ordered to prefer legacy page IDs (shorter, pre-2020 format).
# New-format IDs (100063…/100064…/100066… etc.) are 15-digit and start with
# 1000 — the Ad Library view_all_page_id does NOT accept them, so we skip any
# match that starts with 1000.
_ID_PATTERNS = [
    r'fb://page/(\d{8,})',            # meta tag — most reliable legacy ID
    r'content="fb://page/(\d+)"',     # alternate meta tag encoding
    r'/pages/[^/"]+/(\d{10,})',       # legacy /pages/Name/ID URL
    r'"pageID"\s*:\s*"(\d+)"',        # JSON blob
    r'"page_id"\s*:\s*"(\d+)"',       # JSON blob alternate key
    r'"ownerID"\s*:\s*"(\d+)"',       # owner ID
]

_NEW_FORMAT = re.compile(r'^1000[0-9]')  # 100063…/100064… etc. — not accepted by Ad Library


async def resolve_page_id(page, facebook_url):
    """Visit the Facebook page and extract its legacy numeric page ID."""
    try:
        await page.goto(facebook_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        await page.wait_for_timeout(ID_WAIT)
        html = await page.content()
        for pat in _ID_PATTERNS:
            for m in re.finditer(pat, html):
                pid = m.group(1)
                if len(pid) >= 8 and not _NEW_FORMAT.match(pid):
                    return pid
    except Exception:
        pass
    return None

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_unis(text):
    """Return sorted list of canonical uni names found in text, using alias table."""
    found = set()
    for canonical, alias in UNI_ALIASES:
        if alias.lower() in text.lower():
            found.add(canonical)
    return sorted(found)


def parse_active_count(text):
    for pat in [r'~?([\d,]+)\s+result', r'~?([\d,]+)\s+ad']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", "")
    return "?"


def extract_ad_snippets(text, max_ads):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    snippets, current, in_ad = [], [], False
    skip = re.compile(
        r'^(See more|Hide|Report|Why am I seeing|Share|Learn more|Like|'
        r'Comment|Follow|Send message|Get|Book now|Shop now|Sign up|'
        r'Apply now|Watch more|Download|Contact us|About this ad|'
        r'Filters|All filters|Country|Language|Impressions|Reach|'
        r'Active|See ad details|Open Drop-down|This ad has multiple)$',
        re.IGNORECASE
    )
    for line in lines:
        if line.lower() == "sponsored":
            if current and in_ad:
                snippets.append(" ".join(current))
                if len(snippets) >= max_ads:
                    break
                current = []
            in_ad = True
            continue
        if skip.match(line) or len(line) < 4:
            continue
        if in_ad:
            current.append(line)
    if current and in_ad and len(snippets) < max_ads:
        snippets.append(" ".join(current))
    return [s[:400] for s in snippets]


async def take_screenshot(page, name, suffix=""):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^\w]', '_', name)
        await page.screenshot(
            path=str(DEBUG_DIR / f"{safe}{suffix}.png"),
            full_page=False, timeout=8000,
        )
    except Exception:
        pass

# ── Cookie banner ─────────────────────────────────────────────────────────────

async def accept_cookies(page):
    for sel in [
        '[data-cookiebanner="accept_button"]',
        'button:has-text("Accept all")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Accept")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(800)
                return
        except Exception:
            continue

# ── Core scrape ───────────────────────────────────────────────────────────────

async def scrape_one(page, name, slug, page_id, country_code):
    url = ad_library_url(slug, page_id, country_code)
    result = {
        "name": name, "slug": slug, "page_id": page_id or "",
        "url": url, "active_ads": "?", "ad_snippets": [],
        "unis_found": [], "status": "ok", "error": "",
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PWTimeout:
        result.update(status="timeout", error="Page load timed out")
        return result

    await accept_cookies(page)
    await page.wait_for_timeout(LOAD_WAIT)

    if "login" in page.url or "checkpoint" in page.url:
        result.update(status="blocked", error="Redirected to login")
        await take_screenshot(page, slug, "_blocked")
        return result

    try:
        body = await page.inner_text("body")
    except Exception as e:
        result.update(status="error", error=str(e))
        return result

    no_results = re.search(
        r'no\s+results|\b0\s+results\b|No ads match your search|couldn.t find',
        body, re.IGNORECASE
    )
    if no_results:
        result.update(active_ads="0", status="no_results")
        await take_screenshot(page, slug, "_noresults")
        return result

    result["active_ads"] = parse_active_count(body)
    snippets = extract_ad_snippets(body, MAX_ADS)
    result["ad_snippets"] = snippets
    result["unis_found"]  = find_unis(" ".join(snippets))

    if not snippets:
        result.update(status="no_snippets", error="Loaded but no snippets extracted")
        await take_screenshot(page, slug, "_nosnippets")

    return result

# ── Browser context factory ───────────────────────────────────────────────────

async def new_context(browser, timezone="Asia/Bangkok"):
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id=timezone,
    )
    await ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return ctx

# ── Runner ────────────────────────────────────────────────────────────────────

MARKET_TZ = {
    "Thailand":  "Asia/Bangkok",
    "Nepal":     "Asia/Kathmandu",
    "Cambodia":  "Asia/Phnom_Penh",
    "Vietnam":   "Asia/Ho_Chi_Minh",
    "Indonesia": "Asia/Jakarta",
    "Sri Lanka": "Asia/Colombo",
}


async def run(market_agents, headless, resolve_ids_only=False):
    """
    market_agents: list of (country, country_code, name, slug, fb_url)
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    id_cache = load_id_cache()
    all_results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )

        total = len(market_agents)

        # ── Phase 1: resolve missing page IDs ────────────────────────────────
        needs_id = [(i, c, cc, n, s, u) for i, (c, cc, n, s, u) in enumerate(market_agents)
                    if u not in id_cache]

        if needs_id:
            print(f"\n── Resolving page IDs ({len(needs_id)} missing from cache) ──")
            for idx, (i, country, cc, name, slug, fb_url) in enumerate(needs_id):
                print(f"  [{idx+1}/{len(needs_id)}] {name}  ({fb_url})", end="", flush=True)
                tz = MARKET_TZ.get(country, "Asia/Bangkok")
                ctx = await new_context(browser, tz)
                page = await ctx.new_page()
                pid = await resolve_page_id(page, fb_url)
                await ctx.close()
                id_cache[fb_url] = pid
                print(f"  → {pid or 'not found'}")
                if idx < len(needs_id) - 1:
                    await asyncio.sleep(3)

            save_id_cache(id_cache)
            print(f"  Cache saved ({len(id_cache)} entries)")

        if resolve_ids_only:
            await browser.close()
            return

        # ── Phase 2: scrape ad library ────────────────────────────────────────
        print(f"\n── Scraping ad library ({total} agents across {len(MARKETS)} markets) ──")

        for i, (country, cc, name, slug, fb_url) in enumerate(market_agents):
            page_id = id_cache.get(fb_url)
            id_label = f"id={page_id}" if page_id else "slug-fallback"
            print(f"\n[{i+1}/{total}] [{country}] {name}  ({id_label})")

            tz = MARKET_TZ.get(country, "Asia/Bangkok")
            ctx = await new_context(browser, tz)
            page = await ctx.new_page()
            result = await scrape_one(page, name, slug, page_id, cc)
            result["facebook_url"] = fb_url
            result["country"] = country
            await ctx.close()
            all_results.append(result)

            icons = {"ok": "✓", "no_results": "○", "blocked": "✗",
                     "timeout": "⏱", "error": "!", "no_snippets": "?"}
            print(f"  {icons.get(result['status'], '?')}  "
                  f"ads={result['active_ads']}  "
                  f"snippets={len(result['ad_snippets'])}  "
                  f"unis={result['unis_found']}")
            if result["error"]:
                print(f"     ⚠  {result['error']}")

            if i < total - 1:
                await asyncio.sleep(5)

        await browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    for country in MARKETS:
        market_results = [r for r in all_results if r["country"] == country]
        if not market_results:
            continue
        cc = MARKETS[country]
        print(f"\n{'='*66}")
        print(f"  META AD LIBRARY — {country.upper()} ({cc})  ({len(market_results)} agents)")
        print(f"{'='*66}")
        print(f"  {'Agent':<32}  {'ID':>15}  {'Ads':>5}  {'Status':<12}  Unis")
        print(f"  {'-'*32}  {'-'*15}  {'-'*5}  {'-'*12}  {'-'*20}")
        for r in sorted(market_results,
                        key=lambda x: -int(x["active_ads"])
                        if str(x["active_ads"]).isdigit() else 0):
            unis = ", ".join(r["unis_found"]) or "—"
            print(f"  {r['name'][:32]:<32}  {str(r['page_id']):>15}  "
                  f"{str(r['active_ads']):>5}  {r['status']:<12}  {unis}")

    # ── CSV (one file per market) ─────────────────────────────────────────────
    by_country = {}
    for r in all_results:
        by_country.setdefault(r["country"], []).append(r)

    for country, results in by_country.items():
        rows = []
        for r in results:
            base = {
                "country":       r["country"],
                "agent_name":    r["name"],
                "fb_slug":       r["slug"],
                "page_id":       r["page_id"],
                "facebook_url":  r["facebook_url"],
                "active_ads":    r["active_ads"],
                "unis_found":    "; ".join(r["unis_found"]),
                "status":        r["status"],
                "search_url":    r["url"],
            }
            if r["ad_snippets"]:
                for idx, snippet in enumerate(r["ad_snippets"], 1):
                    rows.append({**base, "ad_num": idx, "ad_text": snippet})
            else:
                rows.append({**base, "ad_num": 0, "ad_text": r["error"]})

        out = OUTPUT_DIR / f"meta_ads_{country.lower().replace(' ', '_')}_{date.today()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  ✅  {len(rows)} rows → {out.name}")

    shots = list(DEBUG_DIR.glob("*.png")) if DEBUG_DIR.exists() else []
    if shots:
        print(f"  📸  {len(shots)} debug screenshots → {DEBUG_DIR.name}/")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless",         action="store_true")
    parser.add_argument("--market",           help="Single market e.g. Thailand")
    parser.add_argument("--slug",             help='Single slug to test e.g. "AECCThailand"')
    parser.add_argument("--resolve-ids-only", action="store_true",
                        help="Only resolve and cache page IDs, skip ad scraping")
    args = parser.parse_args()

    if args.slug:
        country = args.market or "Thailand"
        cc = MARKETS.get(country, "TH")
        market_agents = [(country, cc, "Test", args.slug,
                          f"https://www.facebook.com/{args.slug}")]
    elif args.market:
        if args.market not in MARKETS:
            print(f"Unknown market '{args.market}'. Choose from: {', '.join(MARKETS)}")
            return
        cc = MARKETS[args.market]
        agents = load_agents_from_db(args.market)
        print(f"Loaded {len(agents)} {args.market} agents with Facebook URLs from DB")
        market_agents = [(args.market, cc, n, s, u) for n, s, u in agents]
    else:
        market_agents = []
        for country, cc in MARKETS.items():
            agents = load_agents_from_db(country)
            print(f"  {country}: {len(agents)} agents")
            market_agents.extend([(country, cc, n, s, u) for n, s, u in agents])
        print(f"Total: {len(market_agents)} agents across {len(MARKETS)} markets\n")

    asyncio.run(run(market_agents, headless=args.headless,
                    resolve_ids_only=args.resolve_ids_only))


if __name__ == "__main__":
    main()
