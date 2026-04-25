# Development Log

---

## Session: April 14-19, 2026

### What Was Built

#### Agent Network Foundation
- Scraped authorised agent lists from 42+ Australian university websites using Playwright
- Built SQLite database with 15,000+ agent records across 78 markets
- QUT scraper used internal API endpoint (`/Feature/AgentsSearch/SearchResults`) found via network tab inspection
- UWA and several others required Playwright browser automation to bypass bot protection
- ISO country code normalisation added (UWA stored "AE" instead of "United Arab Emirates" etc.)
- Parent company grouping implemented in matrix display — normalises variants (IDP Education Bangkok 1/2/3 → IDP Education)

#### Social Media Scraping
- Apify integration for Instagram, YouTube, TikTok, LinkedIn scraping
- Facebook Pages Scraper added for follower counts (apify/facebook-pages-scraper, $10/1000 pages)
- Google Reviews rating and count scraped
- Presence score (0–10) calculated per agent across all channels
- Individual agent profile pages built with full social breakdown

#### Agent Network HTML
- Coverage matrix (agents × universities) with sortable column headers
- Agent ranking by authorisation count
- University ranking by agent count per market
- Agent cards with university logo wall (5-column grid)
- Directory with search, email, website links
- Global agents tab
- Market Data tab with visa grant trends
- Resources tab with curated per-country links

#### University Logos
- 29/43 logos successfully fetched (SVG/PNG)
- 14 blocked by bot protection: Deakin, ECU, Griffith, JCU, Macquarie, Monash, QUT, UMelb, UNE, Newcastle, Notre Dame, UTAS, Avondale, Batchelor
- Logos displayed at base of matrix column headers and in agent card logo walls
- Fallback: styled text abbreviation badges

#### Market Data Layer
- Home Affairs visa grants Excel parsed for 77 countries
- Offshore/onshore split, 3-year trend, % offshore column
- Education level breakdown (HE/VET/ELICOS/Schools)
- Power BI interactive report link on every market page
- Financial year labelling (Jul–Jun) to distinguish from AEI calendar year data
- Geognos country profile links (replaced CIA World Factbook — DOGE cuts)

#### AI-Powered Report Generator
- `market-intelligence-report.html` built with Anthropic API integration
- University autocomplete from ALL_DATA
- Country dropdown (Thailand, Nepal coming)
- Generates: channel landscape, top agents by channel table (traffic light matrix), coverage gaps, 3 recommendations
- Thailand digital context hardcoded: YouTube 42hrs/month, TikTok world #2 engagement, LINE OA 78% population
- "Powered by Claude (Anthropic)" attribution
- Save as PDF button

#### Mentions Tracking System
- `mentions/` subfolder with full pipeline
- `alias_matcher.py` — loads alias table, confidence-based matching, education keywords (EN + TH)
- `ingest_tiktok.py` — Apify clockworks/tiktok-hashtag-scraper, 24 hashtags across 10 universities
- `ingest_youtube.py` — Apify youtube-scraper
- `ingest_meta_ads.py` — Meta Ad Library (BLOCKED — needs FB Marketing API token)
- `aggregate.py` — produces 4 output CSVs: university summary, agent mentions, attention table, paid ads summary
- `agent_mapper.py` — maps social handles to agent records (145 agent-country records, 21 TikTok, 65 IG, 124 YT handles indexed)
- `university_alias_table_v2.xlsx` — 68 aliases for 10 universities, EN + TH + hashtags

### Known Issues
- Agent name deduplication still incomplete — some duplicate rows visible in matrix for smaller agents
- Meta Ad Library blocked by Facebook GraphQL — needs official FB Marketing API token
- LINE OA data not yet collected — needs website re-scrape to detect LINE links first
- YouTube subscriber counts showing null for some agents — field mapping issue to investigate
- Instagram follower counts showing null — same issue
- 14 university logos still missing
- `market-intelligence-report.html` requires user to enter Anthropic API key — needs to be replaced with login system before sharing with partners

### GitHub
- Repo: `https://github.com/Justcam555/marketintelligencereports`
- Live: `https://justcam555.github.io/marketintelligencereports`
- SSH configured for push — use `git push origin main`
- Previous HTTPS push attempts failed — SSH is the working method

### Next Session Priorities
1. Fix YouTube subscriber and Instagram follower null values — check Apify raw output vs DB field mapping
2. Complete agent name deduplication in database
3. Build hardcoded university login system for demo
4. Add Nepal digital context to report generator
5. Get FB Marketing API token from OE marketing team (instructions doc sent)
6. Download remaining 14 university logos manually
7. Run full mentions pipeline once Apify token confirmed working

---

## Session: April 25, 2026

### What Was Built

#### Handle Editor UI (`admin_server.py`)
- Added DB-backed web UI at `http://localhost:8765/handles` for manually editing social media handles
- Country selector → agent list with missing-field badges → inline editable fields for all social channels
- Fields: facebook_url, tiktok_handle, tiktok_url, instagram_handle, instagram_url, yt_channel_name, yt_channel_url, linkedin_url, line_oa_handle
- New API routes: `GET /api/db/countries`, `GET /api/db/agents?country=X`, `PUT /api/db/agents/<id>`
- Link added to homepage footer

#### Events Page Scraper (`scrape_events.py`)
- New standalone script: discovers and extracts recruitment events from Thailand agent websites
- Tries 18 common event URL paths per agent (/events, /seminars, /workshops, /activities, /education-fair, etc.)
- Heuristic pre-filter (3+ event signals) before hitting Claude API
- Playwright fallback for JS-rendered pages with thin static HTML (<300 chars)
- Claude API (`claude-sonnet-4-6`) extracts structured events: name, date, ISO date, time, location, format, universities mentioned, details, registration URL
- `--discover` mode for URL discovery without Claude API cost
- Output: `data/processed/agent_events_thailand.json`

#### Meta Ad Library (`mentions/ingest_meta_ads.py`)
- Rewrote to use Apify Facebook Pages Scraper to resolve page IDs, then keyword search
- Abandoned Apify keyword approach — too expensive ($7 wasted, $0.75/1000 ads, no per-page targeting)
- Proper Meta Marketing API token needed; script structure is ready and waiting

### Issues Encountered
- Meta Marketing API token from marketing team was blocked (app not approved for Marketing API `ads_read`)
- Apify FB Ad Library actor doesn't support page-specific URL targeting — keyword search only, too broad
- Thai Unicode text in pages (Chulalongkorn, Education For Life) truncated mid-character at 12,000 char limit → JSON parse errors from Claude
- Adventus homepage matched events heuristic — fixed by rejecting redirects to root path

### What's Working
- Events discovery: 10/37 Thailand agents have events pages
- Events extraction: 11 events extracted from 3 agents (Hands On Education, iGEM Bangkok, WIN Education)
- AECC Global, IDP Education, Expert Education pages found but appear to have no current events
- Chulalongkorn and Education For Life events pages found but Thai text causes JSON parse errors

#### Events Integration — Three Reports
- **Agent Profile**: `renderEvents()` function added to `agent-profile.html`; shows upcoming events card per agent (date, format badge, location, university tags, register link)
- **Mentions Report**: "Agent Events" sidebar section added to `mentions-report.html`; shows university mention counts from events with mini bar chart
- **Market Report**: `AGENT_EVENTS` injected into `market-intelligence-report.html`; event data passed to Claude prompt, "Event Activity" section generated when events present
- `build_agent_html.py` updated to load all `agent_events_*.json` files and inject into all three pages on every build

#### Events Extractor Fixes
- Raised `max_tokens` from 2000 → 4096 (was cutting Claude response mid-JSON)
- Added English-only instruction to prevent Thai text inflating token count
- Changed "Extract ALL events" → "UPCOMING or RECENT only (last 6 months)" — prevents Education For Life historical archive flooding response

### Known Issues (Carryover)
- Thai text truncation in events extractor — fix: use character-safe slicing (slice on decoded chars, not bytes) or increase limit
- Meta Ad Library: needs proper FB Marketing API token (user will get from work)
- YouTube/Instagram null subscriber/follower counts — field mapping issue
- 14 university logos still missing
- Agent deduplication incomplete
- Report generator needs login system before sharing externally

### Next Session Priorities
1. Fix Thai text truncation in `scrape_events.py` — slice at character boundary or bump limit
2. Run events scraper for Nepal (`--country Nepal`)
3. Get FB Marketing API token at work and run Meta Ad Library ingestion
4. Fix YouTube subscriber and Instagram follower null values
5. Download remaining 14 university logos manually

---

## Session: April 25, 2026 (continued)

### What Was Built

#### Monash Agent Database Scraper (`scrape_monash.py`)
- New script: `/Desktop/Agent Scraper/scrape_monash.py`
- Monash uses a Salesforce Lightning / Aura app embedded as an iframe on their agent-database page
- Approach: system Chrome + `playwright-stealth` v2 (Stealth().apply_stealth_sync) bypasses Cloudflare Turnstile
- `requestfinished` event (not `response`) used to read response bodies — avoids Playwright timing issues
- Aura responses have empty `descriptor` fields — matched by URL query param instead
- Response structure: `{"actions": [{"returnValue": {"agencies": [...], "page": 1, "pageSize": 20, "total": 26}}]}`
- Country filter via `[aria-haspopup='listbox']` combobox → triggers `searchAgenciesByCountryWithPagination` action
- Pagination via `button:text-is('>')` (the Monash SF app uses ">" not "Next")
- fwuid extracted from `lightning.force.com/auraFW/javascript/{fwuid}/` URL pattern
- API replay mode (`--replay`) for remaining pages using saved cookies — cookies expire ~30 mins so replay is integrated into Playwright session automatically
- Scraped 26 Thailand agents including all 11 WIN Education branches

#### WIN Education Brand Rule Added
- `normalise_agents.py`: added rule `(r"\bWIN\s+EDUCATION\b|\bWIN\s+Education\b", "WIN Education", "WIN Education")`
- All Monash WIN Education branches now canonicalise to "WIN Education"

#### WIN Education — Monash Contract Fixed
- WIN Education Thailand now shows Monash University as a contract
- Previously missing because: AscentOne database had "WIN EDUCATION SERVICE CO. LTD." which wasn't being matched
- Now scraped directly from Monash's native Salesforce-hosted agent database
- All 11 WIN Education branches (Asoke HQ, Bang Kapi, Chula Samyan, Khon Kaen, Lardprao, Nonthaburi, Pinklao, Siam, Silom, Sukhumvit Emsphere, Ubon) in DB under Monash (university_id=29)

### Issues Encountered
- Cloudflare Turnstile blocks headless Playwright consistently; non-headless with stealth is intermittent
- Solution: system Chrome (`/Applications/Google Chrome.app`) + `playwright-stealth` v2 — reliable ~80% of attempts
- `playwright_stealth` v2 API changed: `Stealth().apply_stealth_sync(page)` (not `stealth_sync(page)`)
- `/AgentDB/s/` URL returns 404 — the app is only accessible as an iframe embed on monash.edu
- Aura API `descriptor` field is empty in responses (only in requests) — must match by URL query param
- Session cookies expire in ~30 minutes — API replay must happen immediately after Playwright session

#### Agent Profile ID Mismatch Fix
- **Root cause**: `enrich_agents.py` deduplication added in previous session was breaking profile links
- Background: each agent in `agent_social` sometimes has two rows (original enrichment + re-enrichment), with different `agent_id` values pointing to different rows in the `agents` table
- `SOCIAL_INDEX` in `agent-network.html` was hardcoded with the HIGHER `agent_id` (the later duplicate row)
- The deduplication kept the FIRST row encountered when scores were equal → picked LOWER `agent_id` → `byId[id]` lookup in agent-profile.html returned undefined → 404-style "not found"
- **Fix**: deduplication now uses `agent_id` as a tiebreaker when `presence_score` is equal — prefers the HIGHER `agent_id` to match what `SOCIAL_INDEX` expects
- Verified: all 145 `SOCIAL_INDEX` entries now resolve to a valid agent profile (0 broken links)

### What's Working
- `python3 scrape_monash.py --country Thailand` — reliable when Chrome passes Cloudflare
- WIN Education now shows Monash + 11 other universities in Thailand agent network
- City shows "Multiple" correctly for multi-branch agents
- All 145 agent profile links working correctly

### Next Session Priorities
1. Run events scraper for Nepal (`--country Nepal`)
2. Get FB Marketing API token at work and run Meta Ad Library ingestion
3. Fix YouTube subscriber and Instagram follower null values
4. Download remaining 14 university logos manually
5. Consider running Monash scraper for all countries (61 pages × 20 records ≈ 1,213 global agents)

---

## Template for Future Sessions

### Session: [Date]

#### What Was Built
- 

#### Issues Encountered
- 

#### What's Working
- 

#### Next Session Priorities
1. 
