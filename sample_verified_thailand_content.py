#!/usr/bin/env python3
"""Collect a small public content sample for verified Thailand agent accounts.

No authentication, account discovery, or paid scraper is used.  Results are a
sample of items visible to a public browser at collection time—not a claim that
they are the platform-wide most popular posts.  Items with public metrics can
be ranked within the sample; the rest are retained as recent-content evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parent
REGISTER = REPO / "data" / "verified_thailand_agent_identities.json"
OUT_DIR = REPO / "data" / "raw"
MAX_ITEMS = 5
TIMEOUT = 30_000


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def metric(text: str, label: str) -> int | None:
    patterns = {
        "views": [r'"viewCount"\s*:\s*"?(\d+)', r'([\d,.]+[KM]?)\s+views'],
        "likes": [r'"likeCount"\s*:\s*"?(\d+)', r'([\d,.]+[KM]?)\s+likes'],
    }
    for pattern in patterns[label]:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        raw = match.group(1).replace(",", "").upper()
        suffix = raw[-1:] if raw[-1:] in {"K", "M"} else ""
        try:
            return int(float(raw.rstrip("KM")) * {"": 1, "K": 1_000, "M": 1_000_000}[suffix])
        except ValueError:
            pass
    return None


async def profile_urls(page, platform: str, url: str) -> list[str]:
    await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
    await page.wait_for_timeout(1500)
    selectors = {
        "instagram": 'a[href*="/p/"],a[href*="/reel/"]',
        "tiktok": 'a[href*="/video/"]',
        "youtube": 'a[href*="/watch?v="]',
    }
    links = await page.locator(selectors[platform]).evaluate_all(
        "els => els.map(e => e.href).filter(Boolean)"
    )
    seen, output = set(), []
    for item in links:
        item = clean_url(item)
        if item not in seen:
            seen.add(item)
            output.append(item)
        if len(output) >= MAX_ITEMS:
            break
    return output


async def item_data(page, platform: str, url: str) -> dict:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        await page.wait_for_timeout(400)
        title = await page.title()
        description = await page.locator('meta[name="description"]').get_attribute("content") or ""
        source = (await page.content())[:1_000_000]
        return {
            "url": url,
            "title": title[:300],
            "description": description[:800],
            "views": metric(source + " " + description, "views"),
            "likes": metric(source + " " + description, "likes"),
        }
    except Exception as exc:
        return {"url": url, "status": "unavailable", "reason": type(exc).__name__}


async def sample_platform(browser, platform: str, url: str) -> dict:
    page = await browser.new_page()
    try:
        urls = await profile_urls(page, platform, url)
        items = []
        for item_url in urls:
            items.append(await item_data(page, platform, item_url))
        ranked = sorted(items, key=lambda x: (x.get("views") or x.get("likes") or 0), reverse=True)
        return {"status": "collected", "profile_url": url, "sample_limit": MAX_ITEMS,
                "ranking_note": "Ranked only among publicly visible sampled items with available metrics.",
                "items": ranked}
    except Exception as exc:
        return {"status": "unavailable", "profile_url": url, "reason": type(exc).__name__}
    finally:
        await page.close()


async def main_async(output: Path) -> None:
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for agent in register["agents"]:
                platforms = {}
                for platform in ("instagram", "tiktok", "youtube"):
                    identity = agent.get(platform)
                    if identity and identity.get("status") in {"verified", "official_global_channel"}:
                        platforms[platform] = await sample_platform(browser, platform, identity["url"])
                results.append({"profile_id": agent["profile_id"], "name": agent["name"], "platforms": platforms})
                print(f"{agent['name']}: " + ", ".join(f"{p}={d['status']}" for p, d in platforms.items()))
        finally:
            await browser.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "market": "Thailand", "collected_at": datetime.now(timezone.utc).isoformat(),
        "method": "authenticated-free public browser sample; no Apify",
        "interpretation": "Metrics rank only sampled visible content, not all historical posts.",
        "agents": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=OUT_DIR / f"social_content_thailand_{datetime.now():%Y-%m-%d}.json")
    args = parser.parse_args()
    asyncio.run(main_async(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
