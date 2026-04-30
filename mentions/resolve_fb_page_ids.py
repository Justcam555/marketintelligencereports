#!/usr/bin/env python3
"""
resolve_fb_page_ids.py

Resolves legacy Facebook page IDs for agents by:
1. Searching the Meta Ad Library with search_type=page
2. Finding the matching page result card
3. Clicking "See all ads" — URL updates to view_all_page_id=LEGACY_ID
4. Caching the ID for use by the main scraper

Usage:
    python3 mentions/resolve_fb_page_ids.py --market Thailand
    python3 mentions/resolve_fb_page_ids.py --market Thailand --headless
    python3 mentions/resolve_fb_page_ids.py  # all 6 markets
"""

import argparse
import asyncio
import json
import re
import sqlite3
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

REPO_DIR      = Path(__file__).resolve().parent.parent
DB_PATH       = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
OUTPUT_DIR    = REPO_DIR / "mentions" / "data" / "raw"
PAGE_ID_CACHE = OUTPUT_DIR / "fb_page_id_cache.json"

MARKETS = {
    "Thailand":  "TH",
    "Nepal":     "NP",
    "Cambodia":  "KH",
    "Vietnam":   "VN",
    "Indonesia": "ID",
    "Sri Lanka": "LK",
}

PAGE_TIMEOUT = 30_000
LOAD_WAIT    = 4_000

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_cache():
    if PAGE_ID_CACHE.exists():
        return json.loads(PAGE_ID_CACHE.read_text())
    return {}


def save_cache(cache):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGE_ID_CACHE.write_text(json.dumps(cache, indent=2))


def slug_from_url(url):
    if not url:
        return None
    url = url.rstrip("/")
    slug = url.split("facebook.com/")[-1].split("?")[0].split("/")[0]
    if slug.lower() in ("", "pg", "media", "pages", "profile.php", "groups", "photo"):
        return None
    return slug


def load_agents(country):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT canonical_name, facebook_url
        FROM agent_social
        WHERE country = ?
          AND facebook_url IS NOT NULL AND TRIM(facebook_url) != ''
        ORDER BY COALESCE(presence_score, 0) DESC, agent_id DESC
    """, (country,)).fetchall()
    conn.close()
    seen, agents = set(), []
    for name, url in rows:
        url = (url or "").strip()
        if url in seen:
            continue
        seen.add(url)
        slug = slug_from_url(url)
        if slug:
            agents.append((name, slug, url))
    return agents


def ad_library_search_url(slug, country_code):
    q = urllib.parse.quote_plus(slug)
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={country_code}"
        f"&search_type=page&q={q}"
    )


def extract_page_id_from_url(url):
    """Pull view_all_page_id=NNN from a URL string."""
    m = re.search(r'view_all_page_id=(\d+)', url)
    return m.group(1) if m else None


_NEW_FORMAT = re.compile(r'^1000[0-9]')


def is_legacy_id(pid):
    return pid and len(pid) >= 8 and not _NEW_FORMAT.match(pid)

# ── Core resolver ─────────────────────────────────────────────────────────────

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
                await page.wait_for_timeout(600)
                return
        except Exception:
            continue


async def resolve_via_adlibrary(page, name, slug, country_code):
    """
    Search Ad Library for the page slug, find the matching result card,
    click it, return the legacy page ID from the resulting URL.
    """
    url = ad_library_search_url(slug, country_code)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PWTimeout:
        return None, "timeout"

    await accept_cookies(page)
    await page.wait_for_timeout(LOAD_WAIT)

    if "login" in page.url or "checkpoint" in page.url:
        return None, "blocked"

    # ── Try to find a page result card matching our slug ──────────────────────
    # The Ad Library page search shows cards with a "See all ads" link.
    # When clicked, the URL becomes ...?view_all_page_id=LEGACY_ID
    #
    # Strategy: find all "See all ads" links/buttons, check the href or
    # click each and see if the resulting URL contains view_all_page_id.
    # We prefer the card whose page URL contains our slug.

    # First: look for links that already contain view_all_page_id in href
    try:
        links = await page.locator('a[href*="view_all_page_id"]').all()
        for link in links:
            href = await link.get_attribute("href") or ""
            pid = extract_page_id_from_url(href)
            if pid and is_legacy_id(pid):
                return pid, "href"
    except Exception:
        pass

    # Second: find "See all ads" buttons/links and click the first one
    # that lands on a view_all_page_id URL
    see_all_selectors = [
        'a:has-text("See all ads")',
        'button:has-text("See all ads")',
        '[role="link"]:has-text("See all ads")',
    ]
    for sel in see_all_selectors:
        try:
            buttons = await page.locator(sel).all()
            for btn in buttons[:3]:  # try first 3 results max
                try:
                    async with page.expect_navigation(timeout=8000):
                        await btn.click()
                    pid = extract_page_id_from_url(page.url)
                    if pid and is_legacy_id(pid):
                        return pid, "click"
                    # go back and try next
                    await page.go_back(timeout=10000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    continue
        except Exception:
            continue

    # Third: check if current page URL already has view_all_page_id
    pid = extract_page_id_from_url(page.url)
    if pid and is_legacy_id(pid):
        return pid, "url"

    return None, "not_found"

# ── Runner ────────────────────────────────────────────────────────────────────

async def run(market_agents, headless):
    cache = load_cache()

    # Only process agents missing a valid legacy ID
    todo = [(c, cc, n, s, u) for c, cc, n, s, u in market_agents
            if not is_legacy_id(cache.get(u))]

    if not todo:
        print("All agents already have verified IDs in cache.")
        return

    print(f"\nResolving {len(todo)} agents via Ad Library click-through ...\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )

        new_found = 0

        for i, (country, cc, name, slug, fb_url) in enumerate(todo):
            print(f"[{i+1}/{len(todo)}] {name}  (@{slug})", end="  ", flush=True)

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

            pid, method = await resolve_via_adlibrary(page, name, slug, cc)
            await ctx.close()

            cache[fb_url] = pid
            if pid:
                new_found += 1
                print(f"→ {pid}  [{method}]")
            else:
                print(f"→ not found  [{method}]")

            # Save after every agent so progress isn't lost
            save_cache(cache)

            if i < len(todo) - 1:
                await asyncio.sleep(4)

        await browser.close()

    good = sum(1 for v in cache.values() if is_legacy_id(v))
    print(f"\nDone. {new_found} new IDs found. Cache: {good} verified IDs total.")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market",   help="Single market e.g. Thailand")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    markets = {args.market: MARKETS[args.market]} if args.market else MARKETS
    if args.market and args.market not in MARKETS:
        print(f"Unknown market. Choose from: {', '.join(MARKETS)}")
        return

    market_agents = []
    for country, cc in markets.items():
        agents = load_agents(country)
        print(f"  {country}: {len(agents)} agents")
        market_agents.extend([(country, cc, n, s, u) for n, s, u in agents])

    asyncio.run(run(market_agents, headless=args.headless))


if __name__ == "__main__":
    main()
