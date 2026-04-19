"""
ingest_youtube.py — search YouTube Data API v3 for university mentions.

For each university canonical name, searches its aliases (non-hashtag EN terms)
and writes results to mentions/data/raw/youtube_YYYY-MM-DD.csv.

Usage:
    export YOUTUBE_API_KEY=AIza...
    python ingest_youtube.py                        # all universities
    python ingest_youtube.py --uni "Monash University"  # one university
    python ingest_youtube.py --days 30              # published in last N days
    python ingest_youtube.py --max-per-query 25     # results per search query
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from alias_matcher import AliasMatcher

RAW_DIR = Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEO_URL  = "https://www.googleapis.com/youtube/v3/videos"

CSV_FIELDS = [
    "ingested_at", "platform", "query_alias", "canonical_university",
    "video_id", "title", "description", "channel_id", "channel_title",
    "published_at", "view_count", "like_count", "comment_count",
    "duration", "url", "match_confidence", "match_type",
]


def search_youtube(api_key: str, query: str, published_after: str,
                   max_results: int = 25) -> list:
    """Run a YouTube search and return enriched video items."""
    params = {
        "part":           "snippet",
        "q":              query,
        "type":           "video",
        "maxResults":     min(max_results, 50),
        "publishedAfter": published_after,
        "key":            api_key,
    }
    r = requests.get(YT_SEARCH_URL, params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return []

    # Batch-fetch video statistics
    video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
    stats = _fetch_stats(api_key, video_ids)

    results = []
    for item in items:
        vid = item.get("id", {}).get("videoId")
        if not vid:
            continue
        snip = item.get("snippet", {})
        s = stats.get(vid, {})
        results.append({
            "video_id":      vid,
            "title":         snip.get("title", ""),
            "description":   (snip.get("description", "") or "")[:500],
            "channel_id":    snip.get("channelId", ""),
            "channel_title": snip.get("channelTitle", ""),
            "published_at":  snip.get("publishedAt", ""),
            "view_count":    s.get("viewCount", ""),
            "like_count":    s.get("likeCount", ""),
            "comment_count": s.get("commentCount", ""),
            "duration":      s.get("duration", ""),
            "url":           f"https://www.youtube.com/watch?v={vid}",
        })
    return results


def _fetch_stats(api_key: str, video_ids: list[str]) -> dict[str, dict]:
    if not video_ids:
        return {}
    params = {
        "part": "statistics,contentDetails",
        "id":   ",".join(video_ids),
        "key":  api_key,
    }
    r = requests.get(YT_VIDEO_URL, params=params, timeout=20)
    r.raise_for_status()
    out = {}
    for item in r.json().get("items", []):
        vid = item["id"]
        st  = item.get("statistics", {})
        cd  = item.get("contentDetails", {})
        out[vid] = {
            "viewCount":    st.get("viewCount", ""),
            "likeCount":    st.get("likeCount", ""),
            "commentCount": st.get("commentCount", ""),
            "duration":     cd.get("duration", ""),
        }
    return out


def run(api_key: str, uni_filter: str, days: int, max_per_query: int):
    matcher = AliasMatcher()
    today = datetime.now(timezone.utc)
    published_after = (today - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    date_str = today.strftime("%Y-%m-%d")
    out_path = RAW_DIR / f"youtube_{date_str}.csv"

    canonicals = matcher.canonical_names
    if uni_filter:
        canonicals = [c for c in canonicals if uni_filter.lower() in c.lower()]
        if not canonicals:
            print(f"No universities match '{uni_filter}'")
            return

    seen_video_ids: set[str] = set()
    rows: list[dict] = []
    ingested_at = today.isoformat()

    for canonical in canonicals:
        aliases = matcher.aliases
        search_aliases = [
            a for a in aliases
            if a["canonical"] == canonical
            and a["type"] != "hashtag"
            and a["language"] == "EN"
            and a["confidence"] in ("high", "medium")
        ]
        # Also include high-confidence TH aliases
        search_aliases += [
            a for a in aliases
            if a["canonical"] == canonical
            and a["type"] != "hashtag"
            and a["language"] == "TH"
            and a["confidence"] == "high"
        ]

        print(f"\n[{canonical}] {len(search_aliases)} search terms")

        for alias_rec in search_aliases:
            query = alias_rec["alias"] + " study australia"
            print(f"  Searching: '{query}'")
            try:
                videos = search_youtube(api_key, query, published_after, max_per_query)
            except requests.HTTPError as e:
                print(f"  ERROR: {e}")
                time.sleep(2)
                continue

            new = 0
            for v in videos:
                vid = v["video_id"]
                if vid in seen_video_ids:
                    continue

                # Run alias matcher on title + description to confirm match
                full_text = f"{v['title']} {v['description']}"
                matches = matcher.match(full_text)
                if not matches:
                    # Still include — search query matched, just no alias in text body
                    match_conf = alias_rec["confidence"]
                    match_type = alias_rec["type"]
                else:
                    best = next((m for m in matches if m["canonical"] == canonical), matches[0])
                    match_conf = best["confidence"]
                    match_type = best["type"]

                seen_video_ids.add(vid)
                rows.append({
                    "ingested_at":           ingested_at,
                    "platform":              "youtube",
                    "query_alias":           alias_rec["alias"],
                    "canonical_university":  canonical,
                    "match_confidence":      match_conf,
                    "match_type":            match_type,
                    **v,
                })
                new += 1

            print(f"    → {new} new videos (total {len(rows)})")
            time.sleep(0.5)  # be kind to quota

    # Write CSV
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Written {len(rows)} rows → {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Ingest YouTube mentions of universities")
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY"),
                        help="YouTube Data API v3 key (or set YOUTUBE_API_KEY env var)")
    parser.add_argument("--uni", default=None, help="Filter to one university (partial match)")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default 30)")
    parser.add_argument("--max-per-query", type=int, default=25,
                        help="Max results per search query (default 25, max 50)")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: YouTube API key required. Set YOUTUBE_API_KEY or use --api-key")
        sys.exit(1)

    run(args.api_key, args.uni, args.days, args.max_per_query)


if __name__ == "__main__":
    main()
