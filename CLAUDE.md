# Claude Code — Session Startup Instructions

At the start of EVERY session, before doing anything else:

1. Read `PROJECT.md` — project overview, architecture, current status
2. Read `DEVLOG.md` — what was last built, what's in progress, known issues
3. Run `git log --oneline -5` — see last 5 commits for recent context

Never start building without completing these three steps first.

---

## Project Location
- Main project: `~/Desktop/marketintelligencereports/`
- Agent scraper database: `~/Desktop/Agent Scraper/data/agents.db`
- Uni logos: `~/Desktop/marketintelligencereports/Uni logos/`
- Mentions tracking: `~/Desktop/marketintelligencereports/mentions/`

## Key Commands

### Rebuild agent network HTML from database
```bash
cd ~/Desktop/marketintelligencereports
python3 build_agent_html.py
```

### Run mentions ingestion pipeline
```bash
cd ~/Desktop/marketintelligencereports
python3 mentions/ingest_tiktok.py --max-per-tag 50
python3 mentions/ingest_youtube.py --days 30
python3 mentions/ingest_meta_ads.py
python3 mentions/aggregate.py
```

### Push to GitHub (SSH configured)
```bash
cd ~/Desktop/marketintelligencereports
git add -A && git commit -m "your message" && git push origin main
```

### Check agent database
```bash
sqlite3 ~/Desktop/"Agent Scraper"/data/agents.db "SELECT COUNT(*) FROM agents"
```

## Environment Variables Required
```bash
export APIFY_API_TOKEN=your_token
export FB_ACCESS_TOKEN=your_token        # when available
export YOUTUBE_API_KEY=your_key          # if switching from Apify to YT API
```

## Rules
- Always test changes locally before pushing to GitHub
- Run `build_agent_html.py` after any database changes before pushing
- Never hardcode API keys — use environment variables
- Commit messages should describe what changed and why
- Update DEVLOG.md at the end of every session
