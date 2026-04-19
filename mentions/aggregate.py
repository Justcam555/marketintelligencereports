"""
aggregate.py — reads raw ingest CSVs and produces 4 output tables.

Output tables (all written to mentions/data/processed/):
  1. university_summary.csv    — per-university mention counts + reach by platform
  2. agent_mentions.csv        — content linked to a known agent, with agent metadata
  3. attention_table.csv       — university × agent cross-tab (who promotes whom)
  4. paid_ads_summary.csv      — placeholder for paid/boosted content signals

Usage:
    python aggregate.py                  # process all raw files
    python aggregate.py --date 2026-04-19  # process specific date only
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_mapper import AgentMapper

RAW_DIR       = Path(__file__).parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _int(v) -> int:
    try:
        return int(v) if v not in (None, "", "N/A") else 0
    except (ValueError, TypeError):
        return 0


def _load_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict], fields: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {path.name} ({len(rows)} rows)")


# ── load raw files ────────────────────────────────────────────────────────────

def load_raw(date_filter: str) -> list:
    """Load all raw CSVs, optionally filtered by date string (YYYY-MM-DD)."""
    all_rows = []
    for f in sorted(RAW_DIR.glob("*.csv")):
        if date_filter and date_filter not in f.name:
            continue
        rows = _load_csv(f)
        platform = f.stem.split("_")[0]  # youtube_2026-04-19 → youtube
        for r in rows:
            r.setdefault("platform", platform)
        all_rows.extend(rows)
        print(f"  Loaded {len(rows):>5} rows ← {f.name}")
    return all_rows


# ── table 1: university summary ───────────────────────────────────────────────

UNI_SUMMARY_FIELDS = [
    "canonical_university", "platform",
    "mention_count", "total_views", "total_likes", "total_comments",
    "unique_creators", "high_confidence_count", "medium_confidence_count",
    "agent_linked_count", "top_video_url", "top_video_views",
    "as_of_date",
]


def build_university_summary(rows: list[dict]) -> list:
    # Group by (canonical_university, platform)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r.get("canonical_university", ""), r.get("platform", ""))
        groups[key].append(r)

    out = []
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for (uni, platform), items in sorted(groups.items()):
        if not uni:
            continue
        views    = [_int(r.get("view_count")) for r in items]
        likes    = [_int(r.get("like_count")) for r in items]
        comments = [_int(r.get("comment_count")) for r in items]

        creator_field = "author_username" if platform == "tiktok" else "channel_id"
        creators = {r.get(creator_field, "") for r in items if r.get(creator_field)}

        conf_counts = defaultdict(int)
        for r in items:
            conf_counts[r.get("match_confidence", "medium")] += 1

        # Top video by views
        top = max(items, key=lambda r: _int(r.get("view_count")), default={})

        out.append({
            "canonical_university":  uni,
            "platform":              platform,
            "mention_count":         len(items),
            "total_views":           sum(views),
            "total_likes":           sum(likes),
            "total_comments":        sum(comments),
            "unique_creators":       len(creators),
            "high_confidence_count": conf_counts["high"],
            "medium_confidence_count": conf_counts["medium"],
            "agent_linked_count":    sum(1 for r in items if r.get("agent_name")),
            "top_video_url":         top.get("url", ""),
            "top_video_views":       _int(top.get("view_count")),
            "as_of_date":            as_of,
        })
    return out


# ── table 2: agent mentions ───────────────────────────────────────────────────

AGENT_MENTIONS_FIELDS = [
    "platform", "canonical_university", "agent_name", "agent_country",
    "video_id", "title", "author_username", "channel_title",
    "published_at", "view_count", "like_count", "comment_count",
    "url", "match_confidence", "match_type",
]


def build_agent_mentions(rows: list[dict]) -> list:
    return [
        r for r in rows
        if r.get("agent_name") and r.get("canonical_university")
    ]


# ── table 3: attention table (university × agent cross-tab) ──────────────────

ATTENTION_FIELDS = [
    "canonical_university", "agent_name", "agent_country",
    "total_mentions", "total_views", "platforms",
    "tiktok_mentions", "youtube_mentions",
    "last_mention_date",
]


def build_attention_table(rows: list[dict]) -> list:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if not r.get("agent_name") or not r.get("canonical_university"):
            continue
        key = (r["canonical_university"], r["agent_name"], r.get("agent_country", ""))
        groups[key].append(r)

    out = []
    for (uni, agent, country), items in sorted(groups.items()):
        platforms = sorted({r["platform"] for r in items})
        dates = [r.get("published_at", "") for r in items if r.get("published_at")]
        out.append({
            "canonical_university": uni,
            "agent_name":           agent,
            "agent_country":        country,
            "total_mentions":       len(items),
            "total_views":          sum(_int(r.get("view_count")) for r in items),
            "platforms":            ", ".join(platforms),
            "tiktok_mentions":      sum(1 for r in items if r["platform"] == "tiktok"),
            "youtube_mentions":     sum(1 for r in items if r["platform"] == "youtube"),
            "last_mention_date":    max(dates) if dates else "",
        })
    # Sort by total views descending
    out.sort(key=lambda r: r["total_views"], reverse=True)
    return out


# ── table 4: paid ads summary (placeholder) ──────────────────────────────────

PAID_ADS_FIELDS = [
    "platform", "canonical_university", "agent_name", "agent_country",
    "video_id", "url", "title", "view_count", "paid_signal", "notes",
]

PAID_SIGNALS = {
    # YouTube: unusually high views vs likes ratio can indicate boosted
    "youtube": lambda r: _int(r.get("view_count", 0)) > 100_000 and _int(r.get("like_count", 0)) == 0,
    # TikTok: no strong signal without API access to ad labels — flag high view count outliers
    "tiktok":  lambda r: _int(r.get("view_count", 0)) > 500_000,
}


def build_paid_ads_summary(rows: list[dict]) -> list:
    out = []
    for r in rows:
        platform = r.get("platform", "")
        signal_fn = PAID_SIGNALS.get(platform)
        if signal_fn and signal_fn(r):
            out.append({
                "platform":             platform,
                "canonical_university": r.get("canonical_university", ""),
                "agent_name":           r.get("agent_name", ""),
                "agent_country":        r.get("agent_country", ""),
                "video_id":             r.get("video_id", ""),
                "url":                  r.get("url", ""),
                "title":                r.get("title", "")[:200],
                "view_count":           r.get("view_count", ""),
                "paid_signal":          "possible_boosted",
                "notes":                "High views / low engagement ratio" if platform == "youtube"
                                        else "View count exceeds organic threshold",
            })
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def run(date_filter: str):
    print(f"\nLoading raw files{f' (date={date_filter})' if date_filter else ''}…")
    raw = load_raw(date_filter)
    if not raw:
        print("No raw files found.")
        return

    print(f"\nEnriching {len(raw)} rows with agent mapping…")
    mapper = AgentMapper()

    # Enrich by platform
    enriched = []
    by_platform: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_platform[r.get("platform", "unknown")].append(r)

    for platform, rows in by_platform.items():
        enriched.extend(mapper.enrich_rows(rows, platform))

    agent_linked = sum(1 for r in enriched if r.get("agent_name"))
    print(f"  Agent-linked: {agent_linked}/{len(enriched)}")

    print("\nBuilding output tables…")

    uni_summary = build_university_summary(enriched)
    _write_csv(PROCESSED_DIR / "university_summary.csv", uni_summary, UNI_SUMMARY_FIELDS)

    agent_mentions = build_agent_mentions(enriched)
    _write_csv(PROCESSED_DIR / "agent_mentions.csv", agent_mentions, AGENT_MENTIONS_FIELDS)

    attention = build_attention_table(enriched)
    _write_csv(PROCESSED_DIR / "attention_table.csv", attention, ATTENTION_FIELDS)

    paid_ads = build_paid_ads_summary(enriched)
    _write_csv(PROCESSED_DIR / "paid_ads_summary.csv", paid_ads, PAID_ADS_FIELDS)

    print(f"\n✓ Done — outputs in {PROCESSED_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Aggregate raw mention CSVs into output tables")
    parser.add_argument("--date", default=None,
                        help="Process only files matching YYYY-MM-DD (default: all)")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
