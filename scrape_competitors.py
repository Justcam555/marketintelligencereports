#!/usr/bin/env python3
"""
scrape_competitors.py — Scrape Instagram, TikTok, and Facebook for
competitors in one-education-report.html that are NOT in the agent_social DB.

Targets:
  - Mango Learning Express  @mangolearningexpress / @mangolearningexpress
  - GoUni                   @gouni.official / @gouniofficial
  - IEC Abroad              @iecabroadthailand / @iecabroad_lgstudy
  - Brit Education          no TikTok / @briteduk

Output: competitor_social.json (printed + saved)
"""

import json
import os
from apify_client import ApifyClient

TOKEN = os.environ.get("APIFY_API_TOKEN")
if not TOKEN:
    raise SystemExit("APIFY_API_TOKEN not set")

client = ApifyClient(TOKEN)

COMPETITORS = [
    {
        "name": "Mango Learning Express",
        "tiktok_handle": "mangolearningexpress",
        "ig_handle":     "mangolearningexpress",
        "fb_url":        "https://www.facebook.com/mangolearningexpress",
    },
    {
        "name": "GoUni",
        "tiktok_handle": "gouni.official",
        "ig_handle":     "gouniofficial",
        "fb_url":        "https://www.facebook.com/gouni.co.th",
    },
    {
        "name": "IEC Abroad",
        "tiktok_handle": "iecabroadthailand",
        "ig_handle":     "iecabroad_lgstudy",
        "fb_url":        "https://www.facebook.com/IECabroadThailand",
    },
    {
        "name": "Brit Education",
        "tiktok_handle": None,
        "ig_handle":     "briteduk",
        "fb_url":        "https://www.facebook.com/briteducation",
    },
]


def scrape_ig_batch(handles):
    """Batch Instagram profile scrape — returns dict handle→data."""
    clean = [h.lstrip("@") for h in handles if h]
    if not clean:
        return {}
    print(f"  [IG] scraping {len(clean)} profiles: {clean}")
    run = client.actor("apify/instagram-profile-scraper").call(run_input={
        "usernames": clean,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    result = {}
    for item in items:
        uname = item.get("username", "").lower()
        if uname:
            result[uname] = item
    print(f"  [IG] got {len(result)} results")
    return result


def scrape_tiktok_profile(handle):
    """TikTok profile scrape — returns dict with followers / videos."""
    h = handle if handle.startswith("@") else f"@{handle}"
    print(f"  [TikTok] scraping {h}")
    run = client.actor("clockworks/tiktok-scraper").call(run_input={
        "profiles": [h],
        "resultsPerPage": 1,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    if not items:
        return {}
    item = items[0]
    # profile info is in the first video's authorMeta
    author = item.get("authorMeta", {})
    return {
        "followers": author.get("fans") or author.get("followers") or 0,
        "following": author.get("following") or 0,
        "hearts":    author.get("heart") or author.get("diggCount") or 0,
        "videos":    author.get("video") or 0,
    }


def scrape_fb(fb_url):
    """Facebook page follower count via apify/facebook-pages-scraper."""
    print(f"  [FB] scraping {fb_url}")
    try:
        run = client.actor("apify/facebook-pages-scraper").call(run_input={
            "startUrls": [{"url": fb_url}],
            "maxPosts": 0,
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        if not items:
            return 0
        item = items[0]
        followers = (
            item.get("followers") or
            item.get("pageFollowers") or
            item.get("likesCount") or
            item.get("likes") or 0
        )
        print(f"  [FB] followers={followers}")
        return followers
    except Exception as e:
        print(f"  [FB] error: {e}")
        return 0


def main():
    results = {}

    # ── Instagram batch ───────────────────────────────────────────────────────
    print("\n=== Instagram scrape ===")
    ig_handles = [c["ig_handle"] for c in COMPETITORS if c.get("ig_handle")]
    ig_data = scrape_ig_batch(ig_handles)

    # ── TikTok profiles ───────────────────────────────────────────────────────
    print("\n=== TikTok scrape ===")
    tiktok_data = {}
    for c in COMPETITORS:
        if c.get("tiktok_handle"):
            tiktok_data[c["name"]] = scrape_tiktok_profile(c["tiktok_handle"])

    # ── Facebook ──────────────────────────────────────────────────────────────
    print("\n=== Facebook scrape ===")
    fb_data = {}
    for c in COMPETITORS:
        if c.get("fb_url"):
            fb_data[c["name"]] = scrape_fb(c["fb_url"])

    # ── Assemble results ──────────────────────────────────────────────────────
    for c in COMPETITORS:
        name = c["name"]
        ig_handle = c.get("ig_handle", "")
        ig = ig_data.get(ig_handle.lower(), {})

        ig_followers = (
            ig.get("followersCount") or ig.get("followers") or
            ig.get("followerCount") or ig.get("userFollowerCount") or 0
        )
        ig_posts = ig.get("postsCount") or ig.get("mediaCount") or ig.get("posts") or 0

        tt = tiktok_data.get(name, {})
        fb_followers = fb_data.get(name, 0)

        results[name] = {
            "instagram_handle":   ig_handle,
            "instagram_followers": ig_followers,
            "instagram_posts":    ig_posts,
            "tiktok_handle":      c.get("tiktok_handle", ""),
            "tiktok_followers":   tt.get("followers", 0),
            "facebook_url":       c.get("fb_url", ""),
            "facebook_followers": fb_followers,
        }

    # ── Print and save ────────────────────────────────────────────────────────
    print("\n=== RESULTS ===")
    print(json.dumps(results, indent=2))

    out_path = "/tmp/competitor_social.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {out_path}")

    return results


if __name__ == "__main__":
    main()
