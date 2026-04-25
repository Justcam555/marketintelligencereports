"""
scrape_events.py — Find and scrape events pages from Thailand agent websites.

For each agent website:
  1. Tries common event page paths (/events, /seminars, etc.)
  2. For pages that respond, sends HTML to Claude API to extract structured events
  3. Saves to data/processed/agent_events.json

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scrape_events.py
    python3 scrape_events.py --country Nepal
    python3 scrape_events.py --limit 10   # test with first 10 agents
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

try:
    import anthropic
except ImportError:
    sys.exit("anthropic not installed. Run: pip3 install anthropic")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

DB_PATH       = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Common paths to check for events pages
EVENT_PATHS = [
    "/events",
    "/event",
    "/events/",
    "/seminars",
    "/seminar",
    "/workshops",
    "/workshop",
    "/webinars",
    "/activities",
    "/news-events",
    "/news-and-events",
    "/open-day",
    "/open-days",
    "/education-fair",
    "/fairs",
    "/upcoming-events",
    "/our-events",
    "/programs-events",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
}

CLAUDE_MODEL   = "claude-sonnet-4-6"
REQUEST_TIMEOUT = 20
RATE_LIMIT_SLEEP = 0.5


# ── helpers ───────────────────────────────────────────────────────────────────

def base_url(url: str) -> str:
    """Extract scheme + netloc from any URL."""
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}"


def strip_html(html: str) -> str:
    """Rough HTML → text for Claude, keeping structure hints."""
    # Remove scripts, styles, nav, footer noise
    html = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Remove tags but keep newlines for block elements
    html = re.sub(r"<(br|p|div|li|tr|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    html = html.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    # Collapse whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


def fetch_page(url: str) -> tuple:
    """Return (text, final_url) or (None, None) on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                         allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text, r.url
        return None, None
    except Exception:
        return None, None


def fetch_page_playwright(url: str) -> tuple:
    """Render page with Playwright and return (html, final_url). Slower but handles JS."""
    if not PLAYWRIGHT_AVAILABLE:
        return None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
                locale="en-US",
            )
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit extra for lazy-loaded content
            page.wait_for_timeout(2000)
            html = page.content()
            final_url = page.url
            browser.close()
        return html, final_url
    except Exception:
        return None, None


def looks_like_events_page(html: str, url: str) -> bool:
    """Quick heuristic check before sending to Claude."""
    text = html.lower()
    event_signals = [
        "event", "seminar", "workshop", "webinar", "fair", "open day",
        "register", "registration", "rsvp", "sign up", "join us",
        "date:", "time:", "venue", "location", "admission",
    ]
    score = sum(1 for s in event_signals if s in text)
    return score >= 3


# ── database ──────────────────────────────────────────────────────────────────

def load_agents(country: str) -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT DISTINCT canonical_name, website_url
        FROM agent_social
        WHERE LOWER(country) = LOWER(?)
          AND website_url IS NOT NULL AND website_url != ''
          AND website_url NOT LIKE '%404%'
        ORDER BY canonical_name
    """, (country,)).fetchall()
    conn.close()

    agents, seen = [], set()
    for name, url in rows:
        b = base_url(url)
        if not b or b in seen:
            continue
        seen.add(b)
        agents.append({"name": name, "website": b})
    return agents


# ── events page discovery ─────────────────────────────────────────────────────

def find_events_page(agent: dict) -> tuple:
    """
    Try common event paths on the agent's website.
    For pages that look like events but have thin content (JS-rendered),
    retries with Playwright to get the fully-rendered HTML.
    Never matches the bare homepage.
    """
    base = agent["website"].rstrip("/")
    for path in EVENT_PATHS:
        url = base + path
        html, final_url = fetch_page(url)
        if not html:
            time.sleep(0.2)
            continue
        # Reject if redirected back to homepage
        parsed = urlparse(final_url)
        if parsed.path in ("", "/", "/index.html", "/index.php"):
            time.sleep(0.2)
            continue
        if looks_like_events_page(html, final_url):
            # Check if content is too thin — likely JS-rendered
            text = strip_html(html)
            if len(text.strip()) < 300 and PLAYWRIGHT_AVAILABLE:
                pw_html, pw_url = fetch_page_playwright(final_url)
                if pw_html and looks_like_events_page(pw_html, pw_url):
                    return pw_html, pw_url
            return html, final_url
        time.sleep(0.2)
    return None, None


# ── Claude extraction ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are extracting recruitment event data from an education agent website.

Agent: {agent_name}
Page URL: {page_url}

Page content:
<content>
{page_text}
</content>

Extract UPCOMING or RECENT events only (from the last 6 months or any future dates). Skip old archived/past events. For each event return a JSON object with these fields:
- "name": event name/title (string)
- "date": date as written on the page (string, e.g. "15 May 2026" or "May 2026")
- "date_iso": best guess at ISO date YYYY-MM-DD, or "" if unclear
- "time": time as written (string, e.g. "10:00 AM - 4:00 PM") or ""
- "location": venue/city/online (string) or ""
- "format": one of "in-person", "online", "hybrid", or ""
- "universities": list of university names mentioned in this event (list of strings)
- "details": brief summary in English of what the event is about, max 80 words (string)
- "registration_url": registration/RSVP link if present (string) or ""

Important: Write ALL field values in English, even if the page content is in Thai or another language.
Return a JSON object: {{"events": [...], "page_summary": "one sentence in English about what events this page covers"}}

If there are no events, return: {{"events": [], "page_summary": "no events found"}}
Return ONLY valid JSON, no other text."""


def extract_events(client, agent_name: str, page_url: str, html: str) -> dict:
    page_text = strip_html(html)[:12000]

    if len(page_text.strip()) < 100:
        return {"events": [], "page_summary": "page too short — likely JS-rendered"}

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(
                    agent_name=agent_name,
                    page_url=page_url,
                    page_text=page_text,
                )
            }]
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        parsed = json.loads(raw)

        # Claude sometimes returns a list of events directly
        if isinstance(parsed, list):
            return {"events": parsed, "page_summary": f"{len(parsed)} events found"}
        if isinstance(parsed, dict):
            return parsed
        return {"events": [], "page_summary": f"unexpected response type: {type(parsed).__name__}"}

    except json.JSONDecodeError as e:
        return {"events": [], "page_summary": f"JSON parse error: {e}"}
    except Exception as e:
        return {"events": [], "page_summary": f"extraction error: {type(e).__name__}: {e}"}


# ── main ──────────────────────────────────────────────────────────────────────

def run_discovery(country: str, limit: int):
    """Discovery-only mode: find which agents have events pages, no Claude API needed."""
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = PROCESSED_DIR / f"agent_events_{country.lower()}.json"

    agents = load_agents(country)
    if limit:
        agents = agents[:limit]
    print(f"\nEvents page discovery — {country}, {len(agents)} agents\n")

    results = []
    found = 0

    for i, agent in enumerate(agents, 1):
        print(f"[{i:02d}/{len(agents)}] {agent['name']:<45}", end="", flush=True)
        html, page_url = find_events_page(agent)
        if html:
            found += 1
            print(f"FOUND  {page_url}")
        else:
            print("—")
        results.append({
            "agent_name":      agent["name"],
            "website":         agent["website"],
            "events_page_url": page_url,
            "events":          [],
            "page_summary":    "discovery only — not yet extracted" if page_url else "no events page found",
            "scraped_at":      today,
        })
        time.sleep(RATE_LIMIT_SLEEP)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'─'*60}")
    print(f"Agents checked:     {len(agents)}")
    print(f"Events pages found: {found}")
    print(f"Output:             {out_path}")
    print(f"\nAgents with events pages:")
    for r in results:
        if r["events_page_url"]:
            print(f"  {r['agent_name']}")
            print(f"    {r['events_page_url']}")


def run(api_key: str, country: str, limit: int):
    client  = anthropic.Anthropic(api_key=api_key)
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = PROCESSED_DIR / f"agent_events_{country.lower()}.json"

    agents = load_agents(country)
    if limit:
        agents = agents[:limit]
    print(f"\nEvents scraper — {country}, {len(agents)} agents\n")

    results = []
    found_pages = 0
    total_events = 0

    for i, agent in enumerate(agents, 1):
        print(f"[{i:02d}/{len(agents)}] {agent['name']}")
        print(f"         {agent['website']}")

        html, page_url = find_events_page(agent)
        if not html:
            print(f"         → no events page found")
            results.append({
                "agent_name": agent["name"],
                "website": agent["website"],
                "events_page_url": None,
                "events": [],
                "page_summary": "no events page found",
                "scraped_at": today,
            })
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        print(f"         → found: {page_url}")
        found_pages += 1

        extracted = extract_events(client, agent["name"], page_url, html)
        events = extracted.get("events", [])
        total_events += len(events)
        print(f"         → {len(events)} events extracted — {extracted.get('page_summary','')[:80]}")

        results.append({
            "agent_name": agent["name"],
            "website": agent["website"],
            "events_page_url": page_url,
            "events": events,
            "page_summary": extracted.get("page_summary", ""),
            "scraped_at": today,
        })

        time.sleep(RATE_LIMIT_SLEEP)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'─'*50}")
    print(f"Agents checked:    {len(agents)}")
    print(f"Events pages found:{found_pages}")
    print(f"Total events:      {total_events}")
    print(f"Output:            {out_path}")

    agents_with_events = [r for r in results if r["events"]]
    pages_no_events    = [r for r in results if r["events_page_url"] and not r["events"]]

    if agents_with_events:
        print(f"\nAgents with events:")
        for r in agents_with_events:
            print(f"  {r['agent_name']} — {len(r['events'])} events")
            for e in r["events"][:3]:
                unis = ", ".join(e.get("universities", [])) or "—"
                print(f"    · {e.get('name','?')[:60]}  [{e.get('date','')}]  Unis: {unis[:50]}")

    if pages_no_events:
        print(f"\nEvents page found but no events extracted:")
        for r in pages_no_events:
            print(f"  {r['agent_name']}")
            print(f"    {r['events_page_url']}")
            print(f"    Reason: {r['page_summary'][:80]}")


def main():
    parser = argparse.ArgumentParser(description="Scrape events pages from agent websites")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    parser.add_argument("--country", default="Thailand")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N agents (0 = all)")
    parser.add_argument("--discover", action="store_true", help="Discovery only — no Claude API needed")
    args = parser.parse_args()

    if args.discover:
        run_discovery(args.country, args.limit)
    else:
        if not args.api_key:
            print("Error: ANTHROPIC_API_KEY required. Set env var or use --api-key")
            sys.exit(1)
        run(args.api_key, args.country, args.limit)


if __name__ == "__main__":
    main()
