"""
ingest_tiktok.py — scrape TikTok hashtag mentions via Apify.

Uses apify/tiktok-hashtag-scraper. One Apify run per hashtag alias.
Writes results to mentions/data/raw/tiktok_YYYY-MM-DD.csv.

Usage:
    export APIFY_API_TOKEN=apify_api_...
    python ingest_tiktok.py                           # all hashtag aliases
    python ingest_tiktok.py --uni "Monash University" # one university
    python ingest_tiktok.py --max-per-tag 50          # videos per hashtag
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient

sys.path.insert(0, str(Path(__file__).parent))
from alias_matcher import AliasMatcher

RAW_DIR = Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

ACTOR_ID = "clockworks/tiktok-hashtag-scraper"

CSV_FIELDS = [
    "ingested_at", "platform", "hashtag", "canonical_university",
    "video_id", "title", "author_username", "author_name",
    "published_at", "view_count", "like_count", "comment_count", "share_count",
    "duration_seconds", "url", "match_confidence",
]


def _parse_item(item: dict, hashtag: str, canonical: str, ingested_at: str) -> dict:
    author = item.get("authorMeta", {}) or {}
    stats  = item.get("stats", {}) or {}
    music  = item.get("musicMeta", {}) or {}

    created_raw = item.get("createTimeISO") or item.get("createTime")
    if isinstance(created_raw, (int, float)):
        published_at = datetime.fromtimestamp(created_raw, tz=timezone.utc).isoformat()
    else:
        published_at = str(created_raw or "")

    video_id = str(item.get("id") or "")
    raw_username = (
        author.get("uniqueId") or
        author.get("username") or
        author.get("handle") or
        item.get("authorHandle") or
        ""
    )
    url = item.get("webVideoUrl") or (
        f"https://www.tiktok.com/@{raw_username}/video/{video_id}" if video_id else ""
    )
    # Fall back to extracting from URL if still empty
    if not raw_username and url:
        m = re.search(r"tiktok\.com/@([^/]+)/", url)
        if m:
            raw_username = m.group(1)

    return {
        "ingested_at":          ingested_at,
        "platform":             "tiktok",
        "hashtag":              hashtag,
        "canonical_university": canonical,
        "video_id":             video_id,
        "title":                (item.get("text") or "")[:300],
        "author_username":      raw_username,
        "author_name":          author.get("nickName", ""),
        "published_at":         published_at,
        "view_count":           stats.get("playCount", ""),
        "like_count":           stats.get("diggCount", ""),
        "comment_count":        stats.get("commentCount", ""),
        "share_count":          stats.get("shareCount", ""),
        "duration_seconds":     item.get("videoMeta", {}).get("duration", ""),
        "url":                  url,
        "match_confidence":     "high",  # hashtag match is always high-confidence
    }


def scrape_hashtag(client: ApifyClient, hashtag: str, max_items: int) -> list:
    """Run the Apify TikTok hashtag scraper and return raw items."""
    tag = hashtag.lstrip("#")
    print(f"  Apify run: #{tag} (max {max_items})")
    run = client.actor(ACTOR_ID).call(
        run_input={
            "hashtags":      [tag],
            "resultsPerPage": max_items,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        },
        timeout_secs=300,
    )
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []
    items = list(client.dataset(dataset_id).iterate_items())
    print(f"    → {len(items)} items returned")
    return items


def run(apify_token: str, uni_filter: str, max_per_tag: int):
    client  = ApifyClient(apify_token)
    matcher = AliasMatcher()
    today   = datetime.now(timezone.utc)
    date_str    = today.strftime("%Y-%m-%d")
    ingested_at = today.isoformat()
    out_path    = RAW_DIR / f"tiktok_{date_str}.csv"

    # Build list of (canonical, hashtag) pairs
    pairs = [
        (a["canonical"], a["alias"])
        for a in matcher.aliases
        if a["type"] == "hashtag"
    ]

    if uni_filter:
        pairs = [(c, h) for c, h in pairs if uni_filter.lower() in c.lower()]
        if not pairs:
            print(f"No hashtag aliases match '{uni_filter}'")
            return

    print(f"Running {len(pairs)} hashtag searches")

    seen_ids: set[str] = set()
    rows: list[dict] = []

    for canonical, hashtag in pairs:
        print(f"\n[{canonical}] {hashtag}")
        try:
            items = scrape_hashtag(client, hashtag, max_per_tag)
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(5)
            continue

        new = 0
        for item in items:
            vid = str(item.get("id") or "")
            if vid and vid in seen_ids:
                continue
            if vid:
                seen_ids.add(vid)

            # Extra validation: check caption mentions the university
            caption = item.get("text") or ""
            matches = matcher.match(caption)
            # Accept if our canonical matched, OR hashtag is high-confidence (always accept)
            canonical_matched = any(m["canonical"] == canonical for m in matches)
            # For hashtag scrapes we trust the hashtag — include all results
            rows.append(_parse_item(item, hashtag, canonical, ingested_at))
            new += 1

        print(f"  → {new} new rows (total {len(rows)})")
        time.sleep(2)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Written {len(rows)} rows → {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Ingest TikTok hashtag mentions of universities")
    parser.add_argument("--apify-token", default=os.environ.get("APIFY_API_TOKEN"),
                        help="Apify API token (or set APIFY_API_TOKEN env var)")
    parser.add_argument("--uni", default=None, help="Filter to one university (partial match)")
    parser.add_argument("--max-per-tag", type=int, default=50,
                        help="Max videos per hashtag (default 50)")
    args = parser.parse_args()

    if not args.apify_token:
        print("Error: Apify token required. Set APIFY_API_TOKEN or use --apify-token")
        sys.exit(1)

    run(args.apify_token, args.uni, args.max_per_tag)


if __name__ == "__main__":
    main()
