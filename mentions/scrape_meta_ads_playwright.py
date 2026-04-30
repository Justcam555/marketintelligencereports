#!/usr/bin/env python3
"""
scrape_meta_ads_playwright.py

Scrapes the Meta Ad Library (Thailand) using a real Playwright/Chromium browser.
By default loads all Thailand agents that have a facebook_url in agent_social,
extracts the page slug, and searches by slug — exact match, no keyword bleed.

Usage:
    python3 mentions/scrape_meta_ads_playwright.py              # all DB agents
    python3 mentions/scrape_meta_ads_playwright.py --headless
    python3 mentions/scrape_meta_ads_playwright.py --slug "AECCThailand"
    python3 mentions/scrape_meta_ads_playwright.py --competitors  # hardcoded list only
"""

import argparse
import asyncio
import csv
import re
import sqlite3
import urllib.parse
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

REPO_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

COUNTRY    = "Thailand"
MAX_ADS    = 25
LOAD_WAIT  = 5_000   # ms after domcontentloaded
PAGE_TIMEOUT = 30_000

OUTPUT_DIR = REPO_DIR / "mentions" / "data" / "raw"
OUTPUT_CSV = OUTPUT_DIR / f"meta_ads_playwright_{date.today()}.csv"
DEBUG_DIR  = OUTPUT_DIR / "debug_screenshots"

UNIVERSITIES = [
    "Monash","Melbourne","RMIT","Deakin","Swinburne","La Trobe",
    "UNSW","UTS","Macquarie","Wollongong","Newcastle","ANU","Canberra",
    "ACU","Charles Sturt","Charles Darwin","CQU","Southern Cross",
    "Griffith","QUT","Bond","JCU","USQ","Sunshine Coast","Murdoch",
    "Curtin","ECU","Edith Cowan","Flinders","Adelaide","UniSA",
    "Tasmania","Federation","Torrens","Victoria University",
]

# ── DB loader ─────────────────────────────────────────────────────────────────

def slug_from_url(url):
    """Extract page slug from https://www.facebook.com/SLUG"""
    if not url:
        return None
    url = url.rstrip("/")
    slug = url.split("facebook.com/")[-1].split("?")[0].split("/")[0]
    # Filter out invalid/generic slugs
    if slug.lower() in ("", "pg", "media", "pages", "profile.php", "groups"):
        return None
    return slug


def load_agents_from_db(country=COUNTRY):
    """Return list of (canonical_name, slug, facebook_url) deduped by facebook_url."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT canonical_name, facebook_url
        FROM agent_social
        WHERE LOWER(country) = LOWER(?)
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

URL_COUNTRY = "TH"

def ad_library_url(slug):
    q = urllib.parse.quote_plus(slug)
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={URL_COUNTRY}"
        f"&search_type=page&q={q}"
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_unis(text):
    t = text.lower()
    return sorted({u for u in UNIVERSITIES if u.lower() in t})


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


async def screenshot(page, name, suffix=""):
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

async def scrape_one(page, name, slug):
    url = ad_library_url(slug)
    result = {
        "name": name, "slug": slug, "url": url,
        "active_ads": "?", "ad_snippets": [],
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
        await screenshot(page, slug, "_blocked")
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
        await screenshot(page, slug, "_noresults")
        return result

    result["active_ads"] = parse_active_count(body)
    snippets = extract_ad_snippets(body, MAX_ADS)
    result["ad_snippets"] = snippets
    result["unis_found"]  = find_unis(" ".join(snippets))

    if not snippets:
        result.update(status="no_snippets",
                      error="Loaded but no snippets extracted")
        await screenshot(page, slug, "_nosnippets")

    return result

# ── Runner ────────────────────────────────────────────────────────────────────

async def run(agents, headless):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )

        for i, (name, slug, fb_url) in enumerate(agents):
            print(f"\n[{i+1}/{len(agents)}] {name}  (@{slug})")
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="Asia/Bangkok",
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = await ctx.new_page()
            result = await scrape_one(page, name, slug)
            result["facebook_url"] = fb_url
            await ctx.close()
            all_results.append(result)

            icons = {"ok":"✓","no_results":"○","blocked":"✗",
                     "timeout":"⏱","error":"!","no_snippets":"?"}
            print(f"  {icons.get(result['status'],'?')}  "
                  f"ads={result['active_ads']}  "
                  f"snippets={len(result['ad_snippets'])}  "
                  f"unis={result['unis_found']}")
            if result["error"]:
                print(f"     ⚠  {result['error']}")

            if i < len(agents) - 1:
                await asyncio.sleep(6)

        await browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*66}")
    print(f"  META AD LIBRARY — THAILAND  ({len(all_results)} agents)")
    print(f"{'='*66}")
    print(f"  {'Agent':<32}  {'Ads':>5}  {'Status':<12}  Unis")
    print(f"  {'-'*32}  {'-'*5}  {'-'*12}  {'-'*24}")
    for r in sorted(all_results,
                    key=lambda x: -int(x["active_ads"])
                    if str(x["active_ads"]).isdigit() else 0):
        unis = ", ".join(r["unis_found"]) or "—"
        print(f"  {r['name'][:32]:<32}  {str(r['active_ads']):>5}  "
              f"{r['status']:<12}  {unis}")

    # ── CSV ───────────────────────────────────────────────────────────────────
    rows = []
    for r in all_results:
        base = {
            "agent_name":    r["name"],
            "fb_slug":       r["slug"],
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

    if not rows:
        print("\n  ⚠  No rows to write — no agents loaded from DB.")
        return

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  ✅  {len(rows)} rows → {OUTPUT_CSV.name}")
    shots = list(DEBUG_DIR.glob("*.png")) if DEBUG_DIR.exists() else []
    if shots:
        print(f"  📸  {len(shots)} debug screenshots → {DEBUG_DIR.name}/")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless",    action="store_true")
    parser.add_argument("--slug",        help='Single slug to test e.g. "AECCThailand"')
    parser.add_argument("--competitors", action="store_true",
                        help="Use hardcoded competitor list instead of DB")
    args = parser.parse_args()

    if args.slug:
        agents = [("Test", args.slug, f"https://www.facebook.com/{args.slug}")]
    elif args.competitors:
        hardcoded = [
            ("IDP",           "IDPEducationThailand"),
            ("WIN Education", "WINed.thailand"),
            ("Hands On",      "HandsOnEdu"),
            ("OEC",           "oecbangkok"),
            ("AECC",          "AECCThailand"),
            ("One Education", "OneEducationGroup"),
        ]
        agents = [(l, s, f"https://www.facebook.com/{s}") for l, s in hardcoded]
    else:
        agents = load_agents_from_db()
        print(f"Loaded {len(agents)} Thailand agents with Facebook URLs from DB")

    asyncio.run(run(agents, headless=args.headless))


if __name__ == "__main__":
    main()
