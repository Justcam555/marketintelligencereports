"""
ingest_meta_ads.py — scrape Meta Ad Library data for Thai education agents via Apify.

Actor: apify/facebook-ads-scraper
Input: Meta Ad Library URLs constructed from each agent's Facebook page URL.
Saves to mentions/data/raw/meta_ads_YYYY-MM-DD.csv
Also writes mentions/data/processed/meta_ads_Thailand.json keyed by facebook_url
(consumed by agent-profile.html and aggregate.py).

Usage:
    export APIFY_API_TOKEN=apify_api_...
    python ingest_meta_ads.py                    # all Thailand agents with FB pages
    python ingest_meta_ads.py --country Nepal    # different country (when data exists)
    python ingest_meta_ads.py --days 30          # ads active in last N days
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apify_client import ApifyClient

sys.path.insert(0, str(Path(__file__).parent))
from alias_matcher import AliasMatcher

DB_PATH       = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
RAW_DIR       = Path(__file__).parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

ACTOR_ID = "apify/facebook-ads-scraper"

# Country → Meta Ad Library country code
COUNTRY_CODES = {
    "Thailand": "TH",
    "Nepal":    "NP",
    "India":    "IN",
    "Vietnam":  "VN",
}

CSV_FIELDS = [
    "platform", "date", "text", "account_name", "agent_name",
    "canonical_university", "alias_matched", "is_paid",
    "facebook_url", "ad_id", "start_date", "end_date",
    "est_reach_min", "est_reach_max", "ad_status",
    "ad_library_url", "ingested_at",
]


def _page_name_from_url(fb_url: str) -> str:
    """Extract page name from https://www.facebook.com/PageName."""
    if not fb_url:
        return ""
    m = re.search(r"facebook\.com/([^/?&#]+)", fb_url)
    if not m:
        return ""
    name = m.group(1).strip("/")
    # Skip generic/invalid slugs
    if name.lower() in ("pg", "media", "pages", "profile.php", ""):
        return ""
    return name


def _ad_library_url(page_name: str, country_code: str) -> str:
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=all&ad_type=all&country={country_code}&q={page_name}"
    )


def _load_agents(country: str) -> list[dict]:
    """Load agents with valid Facebook URLs for the given country."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT canonical_name, facebook_url
        FROM agent_social
        WHERE LOWER(country) = LOWER(?)
          AND facebook_url IS NOT NULL
          AND facebook_url != ''
        GROUP BY canonical_name
    """, (country,)).fetchall()
    conn.close()

    agents = []
    seen = set()
    for name, url in rows:
        page_name = _page_name_from_url(url)
        if not page_name or page_name in seen:
            continue
        seen.add(page_name)
        agents.append({"canonical_name": name, "facebook_url": url, "page_name": page_name})
    return agents


def _parse_ad(item: dict, agent: dict, country_code: str,
              matcher: AliasMatcher, ingested_at: str) -> dict:
    """Normalise a raw Apify facebook-ads-scraper item."""
    # Ad text — try multiple field names the actor may use
    text = (
        item.get("adText") or
        item.get("body") or
        item.get("caption") or
        item.get("title") or
        ""
    )
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    text = str(text).strip()[:1000]

    # Advertiser / account name
    account_name = (
        item.get("pageName") or
        item.get("advertiserName") or
        item.get("page_name") or
        agent["canonical_name"]
    )

    # Dates
    start_date = str(item.get("startDate") or item.get("ad_delivery_start_time") or "")
    end_date   = str(item.get("endDate")   or item.get("ad_delivery_stop_time")  or "")

    # Estimated reach
    reach = item.get("estimatedAudienceSize") or item.get("reach") or {}
    if isinstance(reach, dict):
        reach_min = reach.get("lowerBound") or reach.get("min") or ""
        reach_max = reach.get("upperBound") or reach.get("max") or ""
    else:
        reach_min = reach_max = str(reach) if reach else ""

    # Platform(s)
    platforms = item.get("publisherPlatforms") or item.get("platforms") or ["facebook"]
    if isinstance(platforms, list):
        platform_str = ",".join(platforms)
    else:
        platform_str = str(platforms)

    # Ad status
    status = item.get("adActiveStatus") or item.get("status") or "unknown"

    # Ad ID
    ad_id = str(item.get("adArchiveID") or item.get("id") or "")

    # Run alias matcher on text
    matches = matcher.match(text) if text else []
    canonical_uni = matches[0]["canonical"] if matches else ""
    alias_matched = matches[0]["alias"]     if matches else ""

    return {
        "platform":             platform_str,
        "date":                 start_date,
        "text":                 text,
        "account_name":         str(account_name),
        "agent_name":           agent["canonical_name"],
        "canonical_university": canonical_uni,
        "alias_matched":        alias_matched,
        "is_paid":              True,
        "facebook_url":         agent["facebook_url"],
        "ad_id":                ad_id,
        "start_date":           start_date,
        "end_date":             end_date,
        "est_reach_min":        str(reach_min),
        "est_reach_max":        str(reach_max),
        "ad_status":            str(status),
        "ad_library_url":       _ad_library_url(agent["page_name"], country_code),
        "ingested_at":          ingested_at,
    }


def scrape_ads(client: ApifyClient, ad_library_urls: list[str], max_per_page: int) -> list[dict]:
    """One Apify run for a batch of Ad Library URLs."""
    print(f"  Apify run: {len(ad_library_urls)} Ad Library URLs (max {max_per_page} each)")
    run = client.actor(ACTOR_ID).call(
        run_input={
            "startUrls":      [{"url": u} for u in ad_library_urls],
            "maxAds":         max_per_page,
            "scrapeAdDetails": True,
        },
        timeout_secs=600,
    )
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []
    items = list(client.dataset(dataset_id).iterate_items())
    print(f"    → {len(items)} ads returned")
    return items


def _build_processed_json(rows: list[dict], cutoff: datetime) -> dict:
    """
    Build meta_ads_{country}.json keyed by facebook_url.
    Structure per agent:
      { active_ads_30d, universities_mentioned, est_reach_min, est_reach_max,
        page_name, ad_library_url, last_scraped }
    """
    from collections import defaultdict
    by_agent: dict = defaultdict(list)
    for r in rows:
        by_agent[r["facebook_url"]].append(r)

    out = {}
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fb_url, ads in by_agent.items():
        # Count active/recent ads
        active = [a for a in ads if str(a.get("ad_status", "")).lower() in
                  ("active", "with_end_date", "")]
        unis = sorted({a["canonical_university"] for a in ads if a["canonical_university"]})

        # Sum reach
        def _ri(v):
            try: return int(str(v).replace(",", "")) if v else 0
            except: return 0

        reach_min = sum(_ri(a["est_reach_min"]) for a in ads)
        reach_max = sum(_ri(a["est_reach_max"]) for a in ads)

        out[fb_url] = {
            "active_ads_30d":         len(active),
            "total_ads":              len(ads),
            "universities_mentioned": unis,
            "est_reach_min":          reach_min,
            "est_reach_max":          reach_max,
            "page_name":              ads[0]["account_name"] if ads else "",
            "ad_library_url":         ads[0]["ad_library_url"] if ads else "",
            "last_scraped":           today_str,
        }
    return out


def run(apify_token: str, country: str, days: int, max_per_page: int):
    client      = ApifyClient(apify_token)
    matcher     = AliasMatcher()
    today       = datetime.now(timezone.utc)
    cutoff      = today - timedelta(days=days)
    date_str    = today.strftime("%Y-%m-%d")
    ingested_at = today.isoformat()
    country_code = COUNTRY_CODES.get(country, "TH")

    agents = _load_agents(country)
    if not agents:
        print(f"No agents with Facebook URLs found for {country}")
        return
    print(f"\nFound {len(agents)} {country} agents with Facebook pages")

    # Build Ad Library URLs
    ad_urls = [_ad_library_url(a["page_name"], country_code) for a in agents]
    url_to_agent = {_ad_library_url(a["page_name"], country_code): a for a in agents}

    # Run Apify — batch all agents in one run
    try:
        raw_items = scrape_ads(client, ad_urls, max_per_page)
    except Exception as e:
        print(f"Apify error: {e}")
        return

    # Parse and match items back to agents
    # Items may include a pageUrl or pageName field we can use to route them
    rows = []
    for item in raw_items:
        # Try to identify which agent this ad belongs to
        item_page = (
            item.get("pageUrl") or item.get("page_url") or
            item.get("advertiserProfileLink") or ""
        )
        item_name = _page_name_from_url(str(item_page)).lower()

        # Match to agent by page_name
        matched_agent = None
        for agent in agents:
            if agent["page_name"].lower() == item_name:
                matched_agent = agent
                break
        if not matched_agent:
            # Fallback: match by pageName field
            item_page_name = str(item.get("pageName") or item.get("advertiserName") or "").lower()
            for agent in agents:
                if agent["page_name"].lower() in item_page_name or item_page_name in agent["page_name"].lower():
                    matched_agent = agent
                    break
        if not matched_agent:
            matched_agent = agents[0]  # last resort

        rows.append(_parse_ad(item, matched_agent, country_code, matcher, ingested_at))

    # Write raw CSV
    out_csv = RAW_DIR / f"meta_ads_{date_str}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✓ Raw CSV: {len(rows)} ads → {out_csv}")

    # Write processed JSON for agent profile page
    processed = _build_processed_json(rows, cutoff)
    out_json = PROCESSED_DIR / f"meta_ads_{country}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"✓ Processed JSON: {len(processed)} agents → {out_json}")

    with_ads = sum(1 for v in processed.values() if v["total_ads"] > 0)
    with_uni  = sum(1 for v in processed.values() if v["universities_mentioned"])
    print(f"  Agents with ads: {with_ads}/{len(agents)}")
    print(f"  Ads with uni mention: {with_uni}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Meta Ad Library for Thai education agents via Apify")
    parser.add_argument("--apify-token", default=os.environ.get("APIFY_API_TOKEN"),
                        help="Apify API token (or set APIFY_API_TOKEN env var)")
    parser.add_argument("--country", default="Thailand",
                        help="Country to scrape (default: Thailand)")
    parser.add_argument("--days", type=int, default=30,
                        help="Look-back window in days (default 30)")
    parser.add_argument("--max-per-page", type=int, default=50,
                        help="Max ads per Facebook page (default 50)")
    args = parser.parse_args()

    if not args.apify_token:
        print("Error: Apify token required. Set APIFY_API_TOKEN or use --apify-token")
        sys.exit(1)

    run(args.apify_token, args.country, args.days, args.max_per_page)


if __name__ == "__main__":
    main()
