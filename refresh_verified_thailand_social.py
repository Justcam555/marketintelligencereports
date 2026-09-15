#!/usr/bin/env python3
"""Collect public social metrics only for verified Thailand agent identities.

This deliberately avoids account discovery and Apify.  It reads the curated
identity register, asks each public profile for lightweight page metadata, and
writes a dated snapshot.  A blocked platform is reported as unavailable; its
previous profile data must not be overwritten.

The resulting snapshot is an auditable input to the Agent Network importer,
not a direct database update.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent
REGISTER = REPO / "data" / "verified_thailand_agent_identities.json"
OUT_DIR = REPO / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AgentNetworkResearch/1.0)"}
TIMEOUT = 25


def number(value: str) -> int | None:
    """Convert public display values such as 14K, 1.2M and 12,345 to ints."""
    value = value.replace(",", "").strip().upper()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KM]?)", value)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def get(url: str) -> tuple[str | None, str | None]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"
        return response.text, None
    except requests.RequestException as exc:
        return None, type(exc).__name__


def instagram(url: str) -> dict:
    page, error = get(url)
    if error:
        return {"status": "unavailable", "reason": error}
    description = html.unescape(" ".join(re.findall(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)',
        page, re.I)))
    match = re.search(r"([0-9.,]+[KM]?)\s+Followers.*?([0-9.,]+[KM]?)\s+Posts", description, re.I)
    if not match:
        return {"status": "unavailable", "reason": "public metrics not present"}
    return {
        "status": "collected",
        "followers": number(match.group(1)),
        "post_count": number(match.group(2)),
        "raw_description": description[:500],
    }


def youtube(url: str) -> dict:
    """Use the official API for public channel statistics and recent videos."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return {"status": "unavailable", "reason": "YOUTUBE_API_KEY not configured"}
    path = url.split("youtube.com/", 1)[-1].strip("/")
    params = {"part": "snippet,statistics,contentDetails", "key": key}
    if path.startswith("channel/"):
        params["id"] = path.split("/", 1)[1]
    elif path.startswith("@"):
        params["forHandle"] = path.split("/", 1)[0]
    elif path.startswith("user/"):
        params["forUsername"] = path.split("/", 1)[1]
    elif path.startswith("c/"):
        params["forHandle"] = path.split("/")[1]
    else:  # Custom channel URLs are commonly equivalent to a public handle.
        params["forHandle"] = path.split("/")[-1]
    try:
        channel_response = requests.get("https://www.googleapis.com/youtube/v3/channels",
                                        params=params, timeout=TIMEOUT).json()
        channel = (channel_response.get("items") or [None])[0]
        if not channel:
            return {"status": "unavailable", "reason": "channel not resolved by API"}
        statistics = channel["statistics"]
        uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        recent_response = requests.get("https://www.googleapis.com/youtube/v3/playlistItems",
                                       params={"part": "snippet,contentDetails", "playlistId": uploads,
                                               "maxResults": 5, "key": key}, timeout=TIMEOUT).json()
        video_ids = [item["contentDetails"]["videoId"] for item in recent_response.get("items", [])]
        videos_response = requests.get("https://www.googleapis.com/youtube/v3/videos",
                                       params={"part": "snippet,statistics", "id": ",".join(video_ids),
                                               "key": key}, timeout=TIMEOUT).json() if video_ids else {"items": []}
        videos = [{
            "title": item["snippet"]["title"],
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "published_at": item["snippet"]["publishedAt"],
            "views": int(item["statistics"].get("viewCount", 0)),
            "likes": int(item["statistics"].get("likeCount", 0)),
        } for item in videos_response.get("items", [])]
        return {
            "status": "collected", "channel_name": channel["snippet"]["title"],
            "subscribers": int(statistics.get("subscriberCount", 0)),
            "total_views": int(statistics.get("viewCount", 0)),
            "video_count": int(statistics.get("videoCount", 0)),
            "recent_videos": sorted(videos, key=lambda item: item["published_at"], reverse=True),
            "source": "YouTube Data API v3",
        }
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}


def tiktok(url: str) -> dict:
    page, error = get(url)
    if error:
        return {"status": "unavailable", "reason": error}
    # TikTok may return a challenge page. Only accept explicit embedded counts.
    followers = re.search(r'"followerCount"\s*:\s*(\d+)', page)
    videos = re.search(r'"videoCount"\s*:\s*(\d+)', page)
    if not followers:
        return {"status": "unavailable", "reason": "public metrics not present or access challenged"}
    return {
        "status": "collected",
        "followers": int(followers.group(1)),
        "video_count": int(videos.group(1)) if videos else None,
    }


COLLECTORS = {"instagram": instagram, "youtube": youtube, "tiktok": tiktok}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Optional output path")
    args = parser.parse_args()
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    collected_at = datetime.now(timezone.utc).isoformat()
    results = []

    for agent in register["agents"]:
        record = {"profile_id": agent["profile_id"], "name": agent["name"], "platforms": {}}
        for platform, collector in COLLECTORS.items():
            identity = agent.get(platform)
            if not identity or identity.get("status") not in {"verified", "official_global_channel"}:
                continue
            result = collector(identity["url"])
            result["url"] = identity["url"]
            result["identity_status"] = identity["status"]
            record["platforms"][platform] = result
        results.append(record)
        print(f"{agent['name']}: " + ", ".join(
            f"{p}={r['status']}" for p, r in record["platforms"].items()) or "no eligible profiles")

    payload = {
        "market": "Thailand",
        "collected_at": collected_at,
        "identity_register": str(REGISTER.relative_to(REPO)),
        "method": "direct public-page metadata; no Apify; unavailable values are not replacements",
        "agents": results,
    }
    output = args.output or OUT_DIR / f"social_metrics_thailand_{datetime.now():%Y-%m-%d}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
