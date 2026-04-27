# Australian University Agent Network — Market Intelligence Hub

## One-Line Description
A market intelligence platform that maps which agents are authorised to represent Australian universities in 78 source markets, tracks their online presence and social media activity, and generates AI-powered recruitment intelligence reports.

## Live Site
`https://justcam555.github.io/marketintelligencereports`

## What It Does

### Layer 1 — Market Demand (Government Data)
Shows macro student flow data for each market:
- Commencements by sector (HE / VET / ELICOS) — 3 year trend
- Offshore visa grants — financial year trend
- Source: Australian Department of Education + Home Affairs
- Interactive link: Power BI dashboard at education.gov.au

### Layer 2 — Agent Network (Scraped University Pages)
For each of 78 markets:
- Which agents are authorised by which Australian universities
- Coverage matrix (agents × universities)
- Agent ranking by number of authorisations
- University ranking by number of agents in market
- Agent cards and directory with contact details

### Layer 3 — Online Presence (Social Media Scraping)
For each agent:
- Presence score (0–10) across Website, Google, TikTok, Facebook, IG, LinkedIn, YouTube, LINE OA
- Follower counts, post frequency, last post date, engagement rates
- Google Reviews rating and count
- Individual agent profile pages

### Layer 4 — Intelligence Reports (Claude-Powered)
Dynamic AI-generated reports per university × market:
- Channel landscape for that market
- Top agents by channel (YouTube, TikTok, Facebook, IG, Google Reviews, LINE OA)
- Coverage gaps identified
- 3 actionable recommendations
- Powered by Anthropic API (claude-sonnet-4-20250514)

### Layer 5 — Mentions Tracking (In Progress)
Weekly tracking of university mentions in agent social content:
- TikTok (hashtag scraping via Apify)
- YouTube (Apify scraper)
- Meta Ad Library (requires FB Marketing API token)
- Alias matching system with Thai + English variants
- Output: university mention counts, agent attention mapping, competitive leakage

---

## Architecture

### Data Flow
```
University websites → Playwright scrapers → agents.db (SQLite)
                                                    ↓
Social media (Apify) ──────────────────────→ agents.db
                                                    ↓
Government data (manual download) ──────→ data/processed/
                                                    ↓
build_agent_html.py ────────────────────→ agent-network.html
                                                    ↓
GitHub Pages ───────────────────────────→ justcam555.github.io
```

### Key Files
```
marketintelligencereports/
├── CLAUDE.md                          # Claude Code startup instructions
├── PROJECT.md                         # This file
├── DEVLOG.md                          # Development log
├── index.html                         # Homepage
├── agent-network.html                 # Main agent network page (2.5MB+)
├── agent-profile.html                 # Individual agent profile template
├── market-intelligence-report.html   # AI-powered report generator
├── build_agent_html.py               # Rebuilds agent-network.html from DB
├── market_intelligence.md            # Instructions for market data processing
├── Uni logos/                         # University logo files (SVG/PNG)
│   └── {university-slug}.svg
├── data/
│   ├── raw/                          # Downloaded source files
│   └── processed/
│       ├── market_size_2026-02.json  # Visa grants data, 77 countries
│       ├── market_snippets_2026-02.json
│       └── meta_ads_Thailand.json
├── mentions/                          # University mentions tracking system
│   ├── alias_matcher.py
│   ├── ingest_tiktok.py
│   ├── ingest_youtube.py
│   ├── ingest_meta_ads.py
│   ├── aggregate.py
│   ├── agent_mapper.py
│   ├── university_alias_table_v2.xlsx
│   └── data/
│       ├── raw/
│       └── processed/
└── scrape_*.py                        # University website scrapers (one per uni)
```

### Database
- Location: `~/Desktop/Agent Scraper/data/agents.db` (SQLite)
- ~15,000+ agent rows across 78 markets and 42+ universities
- Key fields: agent_name, parent_company, country, city, email, website, facebook_url, instagram_handle, youtube_channel, tiktok_handle, linkedin_url, line_oa, google_rating, google_review_count, presence_score, authorised_universities

---

## Priority Markets (Active Focus)

The project is now focused on 6 priority markets:

| Market | Notes |
|--------|-------|
| Thailand | Most developed — events scraper, digital context in report generator |
| Vietnam | In scope |
| Nepal | Events scraper next; digital context to add to report generator |
| Indonesia | In scope |
| Sri Lanka | In scope |
| Cambodia | In scope |

All other markets remain in the database but new feature development, scraping runs, and intelligence report work is concentrated on these six.

---

## Current Status (April 2026)

### Working
- Agent network for 78 markets, 42 universities, 15,000+ agents
- Coverage matrix, agent ranking, university ranking, agent cards, directory
- Individual agent profile pages with presence scores and social data
- Market data tab with visa grant trends (77 countries)
- Curated resources tab with per-country links
- AI-powered market intelligence report generator (Thailand + Nepal)
- University logos for 29/43 universities
- TikTok and YouTube mentions ingestion (Apify)
- Facebook page follower scraping (Apify)

### In Progress
- Agent name deduplication / parent company consolidation
- Meta Ad Library ingestion (needs FB Marketing API token from OE marketing team)
- LINE OA presence detection and scraping
- Missing university logos (14 unis blocked bot protection)

### Planned
- University login system (hardcoded credentials for demo)
- Digital landscape context for Vietnam, Indonesia, Sri Lanka, Cambodia in report generator
- Monthly data refresh automation
- Expand mentions tracking to all 6 priority markets

---

## Key Data Sources

| Source | URL | Update Frequency |
|--------|-----|-----------------|
| AEI Monthly Commencements | education.gov.au/international-education-data-and-research | Monthly |
| Home Affairs Visa Grants | data.gov.au/data/dataset/student-visas | Quarterly |
| Universities Australia Hub | universitiesaustralia.edu.au/stats-publications/student-data-hub | Annual |
| Meta Ad Library | facebook.com/ads/library | Real-time |
| DataReportal Thailand Digital | datareportal.com | Annual |

---

## Business Context
This platform is being developed as a standalone market intelligence product. Target customers are Australian universities who want visibility into their agent network quality and digital presence in source markets. Potential pricing: $500–1000/month per university with monthly data refresh. Demo being shown to Australian partner — April 2026.
