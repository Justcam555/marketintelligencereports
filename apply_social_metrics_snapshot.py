#!/usr/bin/env python3
"""Safely merge collected public social metrics into agent-profile.html.

Only platform records explicitly marked ``collected`` are applied.  Missing or
blocked values never clear existing profile data.  The HTML keeps a dated
``social_metrics_checked_at`` value so visitors can distinguish refreshed
metrics from older enrichment fields.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
PROFILE = REPO / "agent-profile.html"
DEFAULT_SNAPSHOT = REPO / "data" / "raw" / "social_metrics_thailand_2026-09-15.json"


def profile_url_handle(url: str) -> str | None:
    match = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
    return match.group(1).lstrip("@") if match else None


def load_agents(source: str) -> tuple[list[dict], int, int]:
    match = re.search(r"const AGENTS = (\[.*?\]);\n", source, re.S)
    if not match:
        raise RuntimeError("Could not find the embedded AGENTS data")
    return json.loads(match.group(1)), match.start(1), match.end(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    source = PROFILE.read_text(encoding="utf-8")
    agents, start, end = load_agents(source)
    by_id = {agent["id"]: agent for agent in agents}
    updates: list[str] = []

    for record in snapshot["agents"]:
        agent = by_id.get(record["profile_id"])
        if not agent:
            print(f"Skip {record['name']}: profile id not found")
            continue
        instagram = record["platforms"].get("instagram")
        if not instagram or instagram.get("status") != "collected":
            continue
        if instagram.get("followers") is None:
            continue
        agent["instagram_url"] = instagram["url"]
        agent["instagram_handle"] = profile_url_handle(instagram["url"])
        agent["instagram_followers"] = instagram["followers"]
        agent["ig_post_count"] = instagram.get("post_count")
        agent["social_metrics_checked_at"] = snapshot["collected_at"]
        updates.append(f"{agent['name']}: {instagram['followers']} followers")

    print("\n".join(updates) if updates else "No collected metrics to apply")
    if args.dry_run:
        return 0

    new_data = json.dumps(agents, ensure_ascii=False, separators=(",", ":"))
    source = source[:start] + new_data + source[end:]
    source = source.replace(
        "const enriched = a.platform_enriched_at\n    ? new Date(a.platform_enriched_at).toLocaleDateString",
        "const enrichedAt = a.social_metrics_checked_at || a.platform_enriched_at;\n  const enriched = enrichedAt\n    ? new Date(enrichedAt).toLocaleDateString",
        1,
    )
    PROFILE.write_text(source, encoding="utf-8")
    print(f"Updated {PROFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
