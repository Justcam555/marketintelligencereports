#!/usr/bin/env python3
"""
scrape_uk_agent_social.py — Scrape social media profile data for UK-only agents.

Reads handles from uk_agent_social, scrapes via Apify, writes into agent_social.
Covers: Instagram, TikTok, Facebook, YouTube.

Usage:
    export APIFY_API_TOKEN=apify_api_...
    python3 scrape_uk_agent_social.py
    python3 scrape_uk_agent_social.py --platform instagram  # one platform only
    python3 scrape_uk_agent_social.py --dry-run             # print handles, no Apify calls
"""

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient

DB_PATH = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

TOKEN = os.environ.get("APIFY_API_TOKEN")
if not TOKEN:
    raise SystemExit("APIFY_API_TOKEN not set")
client = ApifyClient(TOKEN)


# ─── Load handles and market coverage ────────────────────────────────────────

def load_uk_agent_data(conn):
    """
    Returns:
      handles:  {platform: {handle_lower: [cname, ...]}}   (deduplicated per platform)
      coverage: {cname: {"agent_id": int, "markets": [str, ...]}}
    """
    # UK-only canonical names (not in AU universities)
    uk_only = set(r[0] for r in conn.execute("""
        SELECT DISTINCT COALESCE(canonical_name, company_name) AS cname
        FROM agents WHERE university_id >= 43
        AND COALESCE(canonical_name, company_name) NOT IN (
          SELECT DISTINCT COALESCE(canonical_name, company_name)
          FROM agents WHERE university_id < 43
        )
    """).fetchall())

    # Handles for uk-only agents
    social_rows = conn.execute(
        "SELECT agent_cname, platform, handle FROM uk_agent_social"
    ).fetchall()

    handles = {}   # platform → handle_lower → [cname, ...]
    for cname, platform, handle in social_rows:
        if cname not in uk_only:
            continue
        h_low = handle.lower().lstrip("@")
        handles.setdefault(platform, {}).setdefault(h_low, []).append(cname)

    # Market coverage and agent_ids
    coverage = {}
    for cname, agent_id, country in conn.execute("""
        SELECT COALESCE(canonical_name, company_name) AS cname,
               MIN(id) AS agent_id, country
        FROM agents WHERE university_id >= 43
          AND country IS NOT NULL AND TRIM(country) != ''
        GROUP BY cname, country
    """).fetchall():
        if cname not in uk_only:
            continue
        if cname not in coverage:
            coverage[cname] = {"agent_id": agent_id, "markets": []}
        if country and country not in coverage[cname]["markets"]:
            coverage[cname]["markets"].append(country)

    return handles, coverage


# ─── Platform scrapers ────────────────────────────────────────────────────────

def scrape_instagram(handles_dict):
    """Batch scrape all IG handles → {handle_lower: item}"""
    usernames = list(handles_dict.keys())
    if not usernames:
        return {}
    print(f"\n[Instagram] Scraping {len(usernames)} profiles …")
    run = client.actor("apify/instagram-profile-scraper").call(run_input={
        "usernames": usernames,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    result = {}
    for item in items:
        uname = (item.get("username") or "").lower()
        if uname:
            result[uname] = item
    print(f"  → Got {len(result)} results")
    return result


def scrape_tiktok(handles_dict):
    """Batch scrape TikTok profiles → {handle_lower: data}"""
    profiles = ["@" + h for h in handles_dict.keys()]
    if not profiles:
        return {}
    print(f"\n[TikTok] Scraping {len(profiles)} profiles …")
    run = client.actor("clockworks/tiktok-scraper").call(run_input={
        "profiles":       profiles,
        "resultsPerPage": 5,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    result = {}
    for item in items:
        author = item.get("authorMeta") or {}
        uname = (author.get("uniqueId") or author.get("name") or "").lower().lstrip("@")
        if uname and uname not in result:
            result[uname] = {
                "followers":    author.get("fans") or author.get("followers") or 0,
                "following":    author.get("following") or 0,
                "hearts":       author.get("heart") or author.get("diggCount") or 0,
                "video_count":  author.get("video") or 0,
            }
    print(f"  → Got {len(result)} results")
    return result


def scrape_facebook(handles_dict):
    """Batch scrape Facebook pages → {handle_lower: followers}"""
    start_urls = [{"url": f"https://www.facebook.com/{h}"} for h in handles_dict.keys()]
    if not start_urls:
        return {}
    print(f"\n[Facebook] Scraping {len(start_urls)} pages …")
    try:
        run = client.actor("apify/facebook-pages-scraper").call(run_input={
            "startUrls": start_urls,
            "maxPosts":  0,
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        result = {}
        for item in items:
            url = (item.get("url") or item.get("pageUrl") or "").lower()
            # Try to extract the handle from the URL
            import re
            m = re.search(r"facebook\.com/([^/?#]+)", url)
            handle = m.group(1).rstrip("/") if m else ""
            if not handle:
                handle = (item.get("username") or item.get("handle") or "").lower()
            followers = (
                item.get("followers") or item.get("pageFollowers") or
                item.get("likesCount") or item.get("likes") or 0
            )
            if handle:
                result[handle] = {
                    "url":       item.get("url") or f"https://www.facebook.com/{handle}",
                    "followers": followers,
                    "name":      item.get("title") or item.get("name") or "",
                }
        print(f"  → Got {len(result)} results")
        return result
    except Exception as e:
        print(f"  [Facebook] error: {e}")
        return {}


def scrape_youtube(handles_dict):
    """Scrape YouTube channel stats via channel URL → {handle_lower: data}"""
    if not handles_dict:
        return {}
    print(f"\n[YouTube] Scraping {len(handles_dict)} channels …")
    result = {}

    def yt_url(h):
        return f"https://www.youtube.com/@{h}" if not h.startswith("UC") else f"https://www.youtube.com/channel/{h}"

    start_urls = [{"url": yt_url(h)} for h in handles_dict.keys()]
    try:
        run = client.actor("streamers/youtube-scraper").call(run_input={
            "startUrls":      start_urls,
            "maxResults":     1,
            "maxResultsPerPage": 1,
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        for item in items:
            # Channel info from video items
            ch_id    = item.get("channelId") or ""
            ch_name  = item.get("channelName") or item.get("channelTitle") or ""
            ch_url   = item.get("channelUrl") or ""
            subs     = item.get("numberOfSubscribers") or item.get("channelSubscriberCount") or 0
            if isinstance(subs, str):
                import re
                subs = int(re.sub(r"[^\d]", "", subs) or 0)
            ch_handle = ch_url.split("@")[-1].split("/")[0].lower() if "@" in ch_url else ch_id.lower()
            if ch_handle and ch_handle not in result:
                result[ch_handle] = {
                    "channel_name": ch_name,
                    "channel_url":  ch_url or f"https://www.youtube.com/{ch_id}",
                    "subscribers":  subs,
                }
        print(f"  → Got {len(result)} channel entries")
    except Exception as e:
        print(f"  [YouTube] error: {e}")
    return result


# ─── Store results into agent_social ─────────────────────────────────────────

def compute_presence_score(ig_fol, tt_fol, fb_fol, yt_subs):
    """Simple score: number of active platforms (>0 followers)."""
    score = 0
    if ig_fol and ig_fol > 0:   score += 1
    if tt_fol and tt_fol > 0:   score += 1
    if fb_fol and fb_fol > 0:   score += 1
    if yt_subs and yt_subs > 0: score += 1
    return float(score)


def store_results(conn, handles, coverage, ig_data, tt_data, fb_data, yt_data):
    """Write scraped data into agent_social for each UK-only cname × market."""
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped  = 0

    # Build lookup: cname → platform data
    # For each platform, map handle_lower → data, then look up via cname's handle
    def get_handle(cname, platform):
        h_dict = handles.get(platform, {})
        for h_low, cnames in h_dict.items():
            if cname in cnames:
                return h_low
        return None

    processed_cnames = set()
    for cname, cov in coverage.items():
        # Only process cnames that have at least one social handle
        has_handles = any(cname in names for h_dict in handles.values() for names in h_dict.values())
        if not has_handles:
            skipped += 1
            continue

        # Deduplicate: skip if this cname was already processed
        # (some cnames like Crossroads Education PVT share handles with Crossroads Education)
        dedup_key = frozenset(
            (p, h) for p, h_dict in handles.items()
            for h, cnames in h_dict.items() if cname in cnames
        )
        if dedup_key in processed_cnames:
            skipped += 1
            continue
        processed_cnames.add(dedup_key)

        # Fetch Instagram
        ig_handle = get_handle(cname, "instagram")
        ig = ig_data.get(ig_handle) if ig_handle else {}
        ig_followers = (ig.get("followersCount") or ig.get("followers") or ig.get("followerCount") or 0) if ig else 0
        ig_posts     = (ig.get("postsCount") or ig.get("mediaCount") or ig.get("posts") or 0) if ig else 0
        ig_last      = ig.get("latestIgtvVideoTimestampStr") or ig.get("latestMediaTimestamp") or "" if ig else ""

        # Fetch TikTok
        tt_handle = get_handle(cname, "tiktok")
        tt = tt_data.get(tt_handle) if tt_handle else {}
        tt_followers  = tt.get("followers", 0) if tt else 0
        tt_vid_count  = tt.get("video_count", 0) if tt else 0

        # Fetch Facebook
        fb_handle = get_handle(cname, "facebook")
        fb = fb_data.get(fb_handle) if fb_handle else {}
        if not fb and fb_handle:
            # Try partial match
            for k, v in fb_data.items():
                if fb_handle in k or k in fb_handle:
                    fb = v
                    break
        fb_url       = fb.get("url", f"https://www.facebook.com/{fb_handle}") if fb_handle else ""
        fb_followers = fb.get("followers", 0) if fb else 0

        # Fetch YouTube
        yt_handle = get_handle(cname, "youtube")
        yt = yt_data.get(yt_handle.lower()) if yt_handle else {}
        if not yt and yt_handle:
            for k, v in yt_data.items():
                if yt_handle.lower() in k or k in yt_handle.lower():
                    yt = v
                    break
        yt_subs     = yt.get("subscribers", 0) if yt else 0
        yt_ch_name  = yt.get("channel_name", "") if yt else ""
        yt_ch_url   = yt.get("channel_url", "") if yt else ""

        # Also get stored handles for LI/Zalo/Line (no Apify scrape, just store URL)
        li_handle = get_handle(cname, "linkedin")
        li_url    = f"https://linkedin.com/company/{li_handle}" if li_handle else ""

        score = compute_presence_score(ig_followers, tt_followers, fb_followers, yt_subs)

        agent_id = cov["agent_id"]
        markets  = cov["markets"]

        for market in markets:
            # Check if row already exists
            existing = conn.execute(
                "SELECT id FROM agent_social WHERE canonical_name = ? AND country = ? LIMIT 1",
                (cname, market)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE agent_social SET
                      facebook_url       = ?,  facebook_followers  = ?,
                      instagram_handle   = ?,  instagram_followers = ?,
                      ig_post_count      = ?,  ig_last_post        = ?,
                      tiktok_handle      = ?,  tiktok_followers    = ?,
                      tiktok_video_count = ?,
                      yt_channel_name    = ?,  yt_channel_url      = ?,
                      yt_subscribers     = ?,
                      linkedin_url       = ?,
                      presence_score     = ?,  platform_enriched_at = ?
                    WHERE canonical_name = ? AND country = ?
                """, (
                    fb_url, fb_followers,
                    ig_handle, ig_followers, ig_posts, ig_last,
                    tt_handle, tt_followers, tt_vid_count,
                    yt_ch_name, yt_ch_url, yt_subs,
                    li_url,
                    score, now,
                    cname, market
                ))
            else:
                conn.execute("""
                    INSERT INTO agent_social
                      (agent_id, country, canonical_name,
                       facebook_url, facebook_followers,
                       instagram_handle, instagram_url, instagram_followers,
                       ig_post_count, ig_last_post,
                       tiktok_handle, tiktok_followers, tiktok_video_count,
                       yt_channel_name, yt_channel_url, yt_subscribers,
                       linkedin_url,
                       presence_score, platform_enriched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    agent_id, market, cname,
                    fb_url, fb_followers,
                    ig_handle,
                    f"https://instagram.com/{ig_handle}" if ig_handle else "",
                    ig_followers, ig_posts, ig_last,
                    tt_handle, tt_followers, tt_vid_count,
                    yt_ch_name, yt_ch_url, yt_subs,
                    li_url,
                    score, now
                ))
            inserted += 1

    conn.commit()
    print(f"\n✓  {inserted} rows written to agent_social ({skipped} skipped as duplicates/no handles)")
    return inserted


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["instagram","tiktok","facebook","youtube","all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    handles, coverage = load_uk_agent_data(conn)

    print(f"\nUK-only agents with social handles:")
    for platform, h_dict in handles.items():
        print(f"  {platform:<12} {len(h_dict)} unique handles across {sum(len(v) for v in h_dict.values())} agent entries")
    print(f"\n  {len(coverage)} unique agents × {sum(len(c['markets']) for c in coverage.values())} market slots\n")

    if args.dry_run:
        for platform, h_dict in handles.items():
            print(f"\n{platform.upper()}:")
            for h, cnames in sorted(h_dict.items()):
                print(f"  @{h:<45} → {', '.join(cnames)}")
        conn.close()
        return

    do_all = args.platform == "all"

    ig_data = scrape_instagram(handles.get("instagram", {})) if (do_all or args.platform == "instagram") else {}
    tt_data = scrape_tiktok(handles.get("tiktok", {}))       if (do_all or args.platform == "tiktok")    else {}
    fb_data = scrape_facebook(handles.get("facebook", {}))   if (do_all or args.platform == "facebook")  else {}
    yt_data = scrape_youtube(handles.get("youtube", {}))     if (do_all or args.platform == "youtube")   else {}

    print("\n\n=== Storing results ===")
    store_results(conn, handles, coverage, ig_data, tt_data, fb_data, yt_data)

    conn.close()
    print("\nDone. Run: python3 build_agent_html.py  to rebuild the HTML.")


if __name__ == "__main__":
    main()
