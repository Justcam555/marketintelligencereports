"""
agent_mapper.py — maps content creator usernames to known agents in the DB.

Loads TikTok handles, Instagram handles, and YouTube channel URLs from
agent_social and tries to match the author_username / channel_id in raw CSVs.

Usage:
    from agent_mapper import AgentMapper
    mapper = AgentMapper()
    agent = mapper.lookup_tiktok("idpthailand")
    # {'canonical_name': 'IDP Education', 'country': 'Thailand', ...}
"""

import sqlite3
import re
from pathlib import Path

DB_PATH = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"


def _normalise_handle(handle: str) -> str:
    """Strip @, lowercase, remove URL cruft."""
    if not handle:
        return ""
    h = str(handle).strip().lstrip("@").lower()
    # Strip trailing query strings or paths
    h = h.split("?")[0].split("/")[0]
    return h


def _yt_channel_id_from_url(url: str) -> str:
    """Extract channel ID or handle from a YouTube URL."""
    if not url:
        return ""
    # UC... style channel ID
    m = re.search(r"/(UC[\w-]{22})", url)
    if m:
        return m.group(1)
    # /@handle or /c/handle or /user/handle
    m = re.search(r"/(?:@|c/|user/)([^/?&]+)", url)
    if m:
        return m.group(1).lower()
    return ""


class AgentMapper:
    def __init__(self, db_path: Path = DB_PATH):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                s.canonical_name,
                s.country,
                s.tiktok_handle,
                s.tiktok_url,
                s.instagram_handle,
                s.instagram_url,
                s.yt_channel_name,
                s.yt_channel_url,
                s.facebook_url
            FROM agent_social s
        """).fetchall()
        conn.close()

        # Build lookup dicts
        self._tiktok:    dict[str, dict] = {}
        self._instagram: dict[str, dict] = {}
        self._youtube:   dict[str, dict] = {}  # channel_id or handle → agent
        self._agents:    list[dict] = []

        for r in rows:
            agent = {
                "canonical_name": r["canonical_name"],
                "country":        r["country"],
                "tiktok_handle":  r["tiktok_handle"],
                "instagram_handle": r["instagram_handle"],
                "yt_channel_name":  r["yt_channel_name"],
                "yt_channel_url":   r["yt_channel_url"],
            }
            self._agents.append(agent)

            if r["tiktok_handle"]:
                key = _normalise_handle(r["tiktok_handle"])
                self._tiktok[key] = agent

            if r["instagram_handle"]:
                key = _normalise_handle(r["instagram_handle"])
                self._instagram[key] = agent

            if r["yt_channel_url"]:
                key = _yt_channel_id_from_url(r["yt_channel_url"])
                if key:
                    self._youtube[key.lower()] = agent
            if r["yt_channel_name"]:
                self._youtube[r["yt_channel_name"].lower()] = agent

    def lookup_tiktok(self, username: str) -> "dict | None":
        return self._tiktok.get(_normalise_handle(username))

    def lookup_instagram(self, username: str) -> "dict | None":
        return self._instagram.get(_normalise_handle(username))

    def lookup_youtube(self, channel_id_or_name: str) -> "dict | None":
        key = channel_id_or_name.lower() if channel_id_or_name else ""
        return self._youtube.get(key)

    def enrich_rows(self, rows: list[dict], platform: str) -> list:
        """
        Add agent_name, agent_country columns to a list of raw ingest rows.
        platform: 'youtube' | 'tiktok' | 'instagram'
        """
        out = []
        for row in rows:
            agent = None
            if platform == "tiktok":
                agent = self.lookup_tiktok(row.get("author_username", ""))
            elif platform == "youtube":
                agent = self.lookup_youtube(row.get("channel_id", ""))
                if not agent:
                    agent = self.lookup_youtube(row.get("channel_title", ""))
            elif platform == "instagram":
                agent = self.lookup_instagram(row.get("author_username", ""))

            enriched = dict(row)
            enriched["agent_name"]    = agent["canonical_name"] if agent else ""
            enriched["agent_country"] = agent["country"]        if agent else ""
            out.append(enriched)
        return out

    @property
    def all_agents(self) -> list:
        return self._agents


if __name__ == "__main__":
    mapper = AgentMapper()
    tt = len(mapper._tiktok)
    ig = len(mapper._instagram)
    yt = len(mapper._youtube)
    total = len({a["canonical_name"] + a["country"] for a in mapper._agents})
    print(f"AgentMapper loaded {total} agent-country records")
    print(f"  TikTok handles:    {tt}")
    print(f"  Instagram handles: {ig}")
    print(f"  YouTube channels:  {yt}")
