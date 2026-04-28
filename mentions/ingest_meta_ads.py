"""
ingest_meta_ads.py — scrape Meta Ad Library for education agents via Apify.

Two-step process:
  Step 1 (one-time): resolve Facebook page IDs via Facebook Pages Scraper actor.
                     Cached to mentions/data/page_ids.json — skip on subsequent runs.
  Step 2 (every run): scrape ads using view_all_page_id= URLs (page-specific, cheap).

No Facebook account or API token required — uses public Ad Library website.

Saves to:
  mentions/data/raw/meta_ads_YYYY-MM-DD.csv
  mentions/data/processed/meta_ads_{Country}.json  (consumed by agent-profile.html)

Usage:
    export APIFY_API_TOKEN=apify_api_...
    python ingest_meta_ads.py                       # all Thailand agents
    python ingest_meta_ads.py --country Nepal        # Nepal agents
    python ingest_meta_ads.py --days 30              # filter ads newer than N days
    python ingest_meta_ads.py --max-per-page 50      # ads per agent page
    python ingest_meta_ads.py --refresh-page-ids     # force re-resolve page IDs
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

DB_PATH        = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
RAW_DIR        = Path(__file__).parent / "data" / "raw"
PROCESSED_DIR  = Path(__file__).parent / "data" / "processed"
PAGE_IDS_CACHE = Path(__file__).parent / "data" / "page_ids.json"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

AD_LIBRARY_ACTOR  = "XtaWFhbtfxyzqrFmd"   # facebook-ads-library-scraper (keyword search, reliable)
PAGES_ACTOR       = "4Hv5RhChiaDk6iwad"   # Facebook Pages Scraper (page ID resolution)
PAGES_BATCH_SIZE  = 20                     # page IDs to resolve per Apify run

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


# ── helpers ───────────────────────────────────────────────────────────────────

def _page_slug_from_url(fb_url: str) -> str:
    if not fb_url:
        return ""
    m = re.search(r"facebook\.com/([^/?&#]+)", fb_url)
    if not m:
        return ""
    slug = m.group(1).strip("/")
    if slug.lower() in ("pg", "media", "pages", "profile.php", ""):
        return ""
    return slug


def _ad_library_url(page_slug: str, country_code: str) -> str:
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=all&ad_type=all&country={country_code}&q={page_slug}"
    )


def _ad_library_url_for_profile(page_id: str, country_code: str) -> str:
    """Used only in output links — not passed to Apify."""
    return (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=all&ad_type=all&country={country_code}"
        f"&search_type=page&view_all_page_id={page_id}"
    )


def _ad_text(item: dict) -> str:
    snapshot = item.get("snapshot") or {}
    parts = []
    body = snapshot.get("body") or {}
    if isinstance(body, dict):
        text = body.get("text") or body.get("markup", {}).get("__html", "") if isinstance(body.get("markup"), dict) else ""
        if text:
            parts.append(str(text))
    elif isinstance(body, str) and body:
        parts.append(body)
    for field in ("title", "caption"):
        val = snapshot.get(field) or ""
        if val:
            parts.append(str(val))
    for card in (snapshot.get("cards") or []):
        cb = card.get("body") or ""
        if cb:
            parts.append(str(cb))
    return " ".join(parts).strip()[:1000]


def _reach(item: dict) -> tuple:
    impressions = item.get("impressions_with_index") or {}
    text = str(impressions.get("impressions_text", "") or "")
    if "–" in text:
        parts = text.split("–")
        return parts[0].strip(), parts[-1].strip()
    if text:
        return text, text
    return "", ""


# ── database ──────────────────────────────────────────────────────────────────

def load_agents(country: str) -> list:
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

    agents, seen = [], set()
    for name, url in rows:
        slug = _page_slug_from_url(url)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        agents.append({"canonical_name": name, "facebook_url": url, "page_slug": slug})
    return agents


# ── step 1: resolve page IDs (cached) ────────────────────────────────────────

def load_page_id_cache() -> dict:
    if PAGE_IDS_CACHE.exists():
        with open(PAGE_IDS_CACHE) as f:
            return json.load(f)
    return {}


def save_page_id_cache(cache: dict):
    PAGE_IDS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(PAGE_IDS_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def resolve_page_ids(client: ApifyClient, agents: list, force: bool = False) -> dict:
    """
    Return {facebook_url: page_id} for all agents.
    Uses cache unless force=True or an agent is missing from cache.
    """
    cache = {} if force else load_page_id_cache()

    missing = [a for a in agents if a["facebook_url"] not in cache]
    if not missing:
        print(f"  Page IDs: all {len(agents)} loaded from cache")
        return cache

    print(f"  Resolving {len(missing)} page IDs via Apify (cached: {len(agents)-len(missing)})…")

    for i in range(0, len(missing), PAGES_BATCH_SIZE):
        batch = missing[i : i + PAGES_BATCH_SIZE]
        start_urls = [{"url": a["facebook_url"]} for a in batch]

        try:
            run = client.actor(PAGES_ACTOR).call(
                run_input={"startUrls": start_urls, "maxPosts": 0},
                timeout_secs=120,
            )
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                continue
            items = list(client.dataset(dataset_id).iterate_items())
        except Exception as e:
            print(f"    Batch {i//PAGES_BATCH_SIZE+1} error: {e}")
            continue

        # Map results back to agents by URL or name
        for item in items:
            # Pages Scraper uses pageId + pageUrl fields
            page_id  = str(item.get("pageId") or item.get("id") or "").strip()
            item_url = str(item.get("pageUrl") or item.get("url") or "").rstrip("/")
            if not page_id or not item_url:
                continue

            for agent in batch:
                if agent["facebook_url"].rstrip("/").lower() == item_url.lower():
                    cache[agent["facebook_url"]] = page_id
                    break

    save_page_id_cache(cache)
    resolved = sum(1 for a in agents if cache.get(a["facebook_url"]))
    print(f"  Resolved {resolved}/{len(agents)} page IDs (saved to cache)")
    return cache


# ── step 2: scrape ads ────────────────────────────────────────────────────────

def scrape_ads(client: ApifyClient, agents: list, page_id_map: dict,
               country_code: str, max_per_page: int) -> tuple:
    """
    Scrape Ad Library using keyword search by agent canonical name.
    Filter results by page_profile_uri slug (reliable) rather than page_id
    (the Pages Scraper returns IDs in a different format than the Ad Library uses).
    Returns (raw_items, page_id_to_agent, slug_to_agent).
    """
    page_id_to_agent = {}  # populated after run from matched results
    slug_to_agent    = {a["page_slug"].lower(): a for a in agents}
    known_page_ids   = set(page_id_map.values())

    # Search by canonical agent name — more likely to match page name than the slug
    def _name_search_url(name, country_code):
        import urllib.parse
        q = urllib.parse.quote_plus(name)
        return f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={country_code}&q={q}"

    urls = [{"url": _name_search_url(a["canonical_name"], country_code)} for a in agents]
    print(f"  Apify run: {len(urls)} keyword-by-name URLs (max {max_per_page} each)")

    run = client.actor(AD_LIBRARY_ACTOR).call(
        run_input={"urls": urls, "maxResults": max_per_page},
        timeout_secs=600,
    )
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return [], page_id_to_agent, slug_to_agent

    all_items = list(client.dataset(dataset_id).iterate_items())
    total     = sum(1 for i in all_items if i.get("ad_archive_id") or i.get("snapshot"))

    # Filter by page_profile_uri slug — more reliable than page_id (Pages Scraper
    # returns different ID format than what the Ad Library uses internally)
    real_items = []
    for i in all_items:
        if not (i.get("ad_archive_id") or i.get("snapshot")):
            continue
        snap = i.get("snapshot") or {}
        uri_slug = _page_slug_from_url(snap.get("page_profile_uri") or "").lower()
        if uri_slug and uri_slug in slug_to_agent:
            agent = slug_to_agent[uri_slug]
            # Collect the real Ad Library page_id for future use
            real_pid = str(i.get("page_id") or snap.get("page_id") or "")
            if real_pid:
                page_id_to_agent[real_pid] = agent
            real_items.append(i)

    print(f"    → {total} ads fetched, {len(real_items)} matched our agents "
          f"({len(set(page_id_to_agent.values()))} distinct agent pages)")
    return real_items, page_id_to_agent, slug_to_agent


# ── match item to agent ───────────────────────────────────────────────────────

def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_item_to_agent(item: dict, page_id_to_agent: dict, slug_to_agent: dict):
    snapshot = item.get("snapshot") or {}

    # 1. Match by page_id (exact, reliable for page-specific URLs)
    pid = str(item.get("page_id") or snapshot.get("page_id") or "")
    if pid and pid in page_id_to_agent:
        return page_id_to_agent[pid]

    # 2. Match by page_profile_uri slug (normalised)
    profile_uri = snapshot.get("page_profile_uri") or ""
    uri_slug    = _page_slug_from_url(profile_uri)
    if uri_slug:
        if uri_slug.lower() in slug_to_agent:
            return slug_to_agent[uri_slug.lower()]
        norm = _normalise(uri_slug)
        for slug, agent in slug_to_agent.items():
            if _normalise(slug) == norm:
                return agent

    return None


# ── parse ad ──────────────────────────────────────────────────────────────────

def parse_ad(item: dict, agent: dict, country_code: str,
             matcher: AliasMatcher, ingested_at: str, cutoff: datetime):
    snapshot   = item.get("snapshot") or {}
    start_date = str(item.get("startDate") or snapshot.get("creation_time") or "")
    end_date   = str(item.get("endDate") or "")

    if start_date and cutoff:
        try:
            sd = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            if sd.tzinfo is None:
                sd = sd.replace(tzinfo=timezone.utc)
            if sd < cutoff:
                return None
        except ValueError:
            pass

    text             = _ad_text(item)
    reach_min, reach_max = _reach(item)
    ad_id            = str(item.get("ad_archive_id") or "")
    page_name        = str(snapshot.get("page_name") or agent["canonical_name"])
    pid              = str(item.get("page_id") or snapshot.get("page_id") or "")
    ad_status        = "active" if item.get("is_active", True) else "inactive"
    platforms        = snapshot.get("publisher_platform") or ["facebook"]
    platform_str     = ",".join(platforms) if isinstance(platforms, list) else str(platforms)
    lib_url          = (_ad_library_url_for_profile(pid, country_code) if pid
                        else _ad_library_url(agent["page_slug"], country_code))

    matches           = matcher.match(text) if text else []
    canonical_uni     = matches[0]["canonical"] if matches else ""
    alias_matched     = matches[0]["alias"]     if matches else ""

    return {
        "platform":             platform_str,
        "date":                 start_date,
        "text":                 text,
        "account_name":         page_name,
        "agent_name":           agent["canonical_name"],
        "canonical_university": canonical_uni,
        "alias_matched":        alias_matched,
        "is_paid":              True,
        "facebook_url":         agent["facebook_url"],
        "ad_id":                ad_id,
        "start_date":           start_date,
        "end_date":             end_date,
        "est_reach_min":        reach_min,
        "est_reach_max":        reach_max,
        "ad_status":            ad_status,
        "ad_library_url":       lib_url,
        "ingested_at":          ingested_at,
    }


# ── processed JSON ────────────────────────────────────────────────────────────

def build_processed_json(rows: list) -> dict:
    from collections import defaultdict
    by_agent = defaultdict(list)
    for r in rows:
        by_agent[r["facebook_url"]].append(r)

    def _ri(v):
        try:
            return int(re.sub(r"[^0-9]", "", str(v))) if v else 0
        except (ValueError, TypeError):
            return 0

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {}
    for fb_url, ads in by_agent.items():
        active = [a for a in ads if a.get("ad_status") == "active"]
        unis   = sorted({a["canonical_university"] for a in ads if a["canonical_university"]})
        out[fb_url] = {
            "active_ads_30d":         len(active),
            "total_ads":              len(ads),
            "universities_mentioned": unis,
            "est_reach_min":          sum(_ri(a["est_reach_min"]) for a in ads),
            "est_reach_max":          sum(_ri(a["est_reach_max"]) for a in ads),
            "page_name":              ads[0]["account_name"] if ads else "",
            "ad_library_url":         ads[0]["ad_library_url"] if ads else "",
            "last_scraped":           today_str,
        }
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def run(apify_token: str, country: str, days: int, max_per_page: int, refresh_ids: bool):
    client       = ApifyClient(apify_token)
    matcher      = AliasMatcher()
    today        = datetime.now(timezone.utc)
    cutoff       = today - timedelta(days=days)
    date_str     = today.strftime("%Y-%m-%d")
    ingested_at  = today.isoformat()
    country_code = COUNTRY_CODES.get(country, "TH")

    print(f"\nMeta Ad Library ingestion — {country} ({country_code}), last {days} days")

    agents = load_agents(country)
    if not agents:
        print(f"No agents with Facebook URLs found for {country}")
        return
    print(f"Found {len(agents)} {country} agents with Facebook pages")

    # Step 1: page IDs (cached after first run)
    page_id_map = resolve_page_ids(client, agents, force=refresh_ids)

    # Step 2: scrape ads
    raw_items, page_id_to_agent, slug_to_agent = scrape_ads(
        client, agents, page_id_map, country_code, max_per_page
    )

    rows = []
    skipped = 0
    for item in raw_items:
        agent = match_item_to_agent(item, page_id_to_agent, slug_to_agent)
        if not agent:
            skipped += 1
            continue
        row = parse_ad(item, agent, country_code, matcher, ingested_at, cutoff)
        if row:
            rows.append(row)

    if skipped:
        print(f"  Skipped {skipped} ads (unmatched page)")

    out_csv = RAW_DIR / f"meta_ads_{date_str}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✓ Raw CSV: {len(rows)} ads → {out_csv}")

    processed = build_processed_json(rows)
    out_json = PROCESSED_DIR / f"meta_ads_{country}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"✓ Processed JSON: {len(processed)} agents → {out_json}")

    with_ads = sum(1 for v in processed.values() if v["total_ads"] > 0)
    with_uni  = sum(1 for v in processed.values() if v["universities_mentioned"])
    print(f"  Agents with ads:       {with_ads}/{len(agents)}")
    print(f"  Ads mentioning a uni:  {with_uni}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Meta Ad Library for education agents via Apify")
    parser.add_argument("--apify-token", default=os.environ.get("APIFY_API_TOKEN"),
                        help="Apify API token (or set APIFY_API_TOKEN env var)")
    parser.add_argument("--country", default="Thailand")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-per-page", type=int, default=50)
    parser.add_argument("--refresh-page-ids", action="store_true",
                        help="Force re-resolve page IDs even if cached")
    args = parser.parse_args()

    if not args.apify_token:
        print("Error: Apify token required. Set APIFY_API_TOKEN or use --apify-token")
        sys.exit(1)

    run(args.apify_token, args.country, args.days, args.max_per_page, args.refresh_page_ids)


if __name__ == "__main__":
    main()
