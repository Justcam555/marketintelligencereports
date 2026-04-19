"""
ingest_youtube.py — scrape YouTube mentions via Apify youtube-scraper actor.

Uses apify/youtube-scraper. Searches by alias term (one run per search query),
extracts title, description, channel name, subscriber count, views, publish date.
Writes results to mentions/data/raw/youtube_YYYY-MM-DD.csv.

Usage:
    export APIFY_API_TOKEN=apify_api_...
    python ingest_youtube.py                          # all universities
    python ingest_youtube.py --uni "Monash University"  # one university
    python ingest_youtube.py --max-per-query 25       # results per search
    python ingest_youtube.py --days 90                # only keep videos from last N days
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apify_client import ApifyClient

sys.path.insert(0, str(Path(__file__).parent))
from alias_matcher import AliasMatcher

RAW_DIR = Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

ACTOR_ID = "apify/youtube-scraper"

CSV_FIELDS = [
    "ingested_at", "platform", "query_alias", "canonical_university",
    "video_id", "title", "description", "channel_id", "channel_title",
    "channel_subscribers", "published_at", "view_count", "like_count",
    "comment_count", "duration", "url", "match_confidence", "match_type",
]


def _parse_item(item: dict) -> dict:
    """Normalise a raw apify/youtube-scraper result into our CSV schema."""
    video_id = item.get("id") or item.get("videoId") or ""
    url = item.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")

    # Published date — actor returns ISO string or epoch ms
    pub_raw = item.get("date") or item.get("publishedAt") or item.get("publishDate") or ""
    if isinstance(pub_raw, (int, float)):
        pub_raw = datetime.fromtimestamp(pub_raw / 1000, tz=timezone.utc).isoformat()

    # Subscriber count may come as "1.2M" string or integer
    subs_raw = item.get("channelSubscriberCount") or item.get("numberOfSubscribers") or ""
    subs = _parse_abbrev(subs_raw)

    return {
        "video_id":           video_id,
        "title":              (item.get("title") or "")[:300],
        "description":        (item.get("description") or item.get("text") or "")[:500],
        "channel_id":         item.get("channelId") or item.get("channelUrl") or "",
        "channel_title":      item.get("channelName") or item.get("channel") or "",
        "channel_subscribers": subs,
        "published_at":       str(pub_raw),
        "view_count":         item.get("viewCount") or item.get("views") or "",
        "like_count":         item.get("likes") or item.get("likeCount") or "",
        "comment_count":      item.get("commentsCount") or item.get("commentCount") or "",
        "duration":           item.get("duration") or "",
        "url":                url,
    }


def _parse_abbrev(val) -> str:
    """Convert '1.2M', '34K' abbreviations to integer string."""
    if not val:
        return ""
    if isinstance(val, int):
        return str(val)
    s = str(val).strip().upper().replace(",", "")
    try:
        if s.endswith("M"):
            return str(int(float(s[:-1]) * 1_000_000))
        if s.endswith("K"):
            return str(int(float(s[:-1]) * 1_000))
        return str(int(float(s)))
    except (ValueError, TypeError):
        return str(val)


def search_youtube_apify(client: ApifyClient, query: str, max_results: int) -> list:
    """Run apify/youtube-scraper for a search query and return raw items."""
    print(f"  Apify run: '{query}' (max {max_results})")
    run = client.actor(ACTOR_ID).call(
        run_input={
            "searchKeywords":   query,
            "maxResults":       max_results,
            "maxResultsShorts": 0,
            "downloadSubtitles": False,
            "saveVtt":          False,
        },
        timeout_secs=300,
    )
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []
    items = list(client.dataset(dataset_id).iterate_items())
    print(f"    → {len(items)} items returned")
    return items


def run(apify_token: str, uni_filter: str, days: int, max_per_query: int):
    client  = ApifyClient(apify_token)
    matcher = AliasMatcher()
    today   = datetime.now(timezone.utc)
    cutoff  = today - timedelta(days=days)
    date_str    = today.strftime("%Y-%m-%d")
    ingested_at = today.isoformat()
    out_path    = RAW_DIR / f"youtube_{date_str}.csv"

    canonicals = matcher.canonical_names
    if uni_filter:
        canonicals = [c for c in canonicals if uni_filter.lower() in c.lower()]
        if not canonicals:
            print(f"No universities match '{uni_filter}'")
            return

    seen_video_ids: set = set()
    rows: list = []

    for canonical in canonicals:
        # EN aliases: non-hashtag, high/medium confidence
        search_aliases = [
            a for a in matcher.aliases
            if a["canonical"] == canonical
            and a["type"] != "hashtag"
            and a["language"] == "EN"
            and a["confidence"] in ("high", "medium")
        ]
        # High-confidence TH aliases too
        search_aliases += [
            a for a in matcher.aliases
            if a["canonical"] == canonical
            and a["type"] != "hashtag"
            and a["language"] == "TH"
            and a["confidence"] == "high"
        ]

        print(f"\n[{canonical}] {len(search_aliases)} search terms")

        for alias_rec in search_aliases:
            query = alias_rec["alias"] + " study australia"
            try:
                items = search_youtube_apify(client, query, max_per_query)
            except Exception as e:
                print(f"  ERROR: {e}")
                time.sleep(5)
                continue

            new = 0
            for item in items:
                parsed = _parse_item(item)
                vid = parsed["video_id"]
                if not vid or vid in seen_video_ids:
                    continue

                # Date filter — drop videos older than cutoff
                pub = parsed["published_at"]
                if pub and len(pub) >= 10:
                    try:
                        pub_dt = datetime.fromisoformat(pub[:19]).replace(tzinfo=timezone.utc)
                        if pub_dt < cutoff:
                            continue
                    except ValueError:
                        pass

                # Confirm match in title/description
                full_text = f"{parsed['title']} {parsed['description']}"
                matches = matcher.match(full_text)
                if matches:
                    best = next((m for m in matches if m["canonical"] == canonical), matches[0])
                    match_conf = best["confidence"]
                    match_type = best["type"]
                else:
                    match_conf = alias_rec["confidence"]
                    match_type = alias_rec["type"]

                seen_video_ids.add(vid)
                rows.append({
                    "ingested_at":          ingested_at,
                    "platform":             "youtube",
                    "query_alias":          alias_rec["alias"],
                    "canonical_university": canonical,
                    "match_confidence":     match_conf,
                    "match_type":           match_type,
                    **parsed,
                })
                new += 1

            print(f"    → {new} new (total {len(rows)})")
            time.sleep(2)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Written {len(rows)} rows → {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest YouTube mentions of universities via Apify")
    parser.add_argument("--apify-token", default=os.environ.get("APIFY_API_TOKEN"),
                        help="Apify API token (or set APIFY_API_TOKEN env var)")
    parser.add_argument("--uni", default=None,
                        help="Filter to one university (partial match)")
    parser.add_argument("--days", type=int, default=90,
                        help="Drop videos older than N days (default 90)")
    parser.add_argument("--max-per-query", type=int, default=25,
                        help="Max results per search query (default 25)")
    args = parser.parse_args()

    if not args.apify_token:
        print("Error: Apify token required. Set APIFY_API_TOKEN or use --apify-token")
        sys.exit(1)

    run(args.apify_token, args.uni, args.days, args.max_per_query)


if __name__ == "__main__":
    main()
