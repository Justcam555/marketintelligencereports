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

## Session: April 25, 2026 (continued — profile link fixes)

### What Was Built

#### Directory Profile Link Fix — Phase 1: canonical_name in ALL_DATA (`build_agent_html.py`, `agent-network.html`)
- **Root cause**: `a.name` in ALL_DATA used `COALESCE(parent_company, company_name)` (e.g. "IDP Education Ltd") but SOCIAL_INDEX keys use `canonical_name` (e.g. "IDP Education") — lookup always returned null
- `load_data()` updated: added `canonical_name` as 7th field in SQL query
- `build_all_data()` stores it as `"canonical"` on each agent dict
- `renderDirRows()` in `agent-network.html` now uses: `const lookupKey = a.canonical || a.name;`
- Fixed agents: IDP Education, One Education, AVSS, WIN Education, AECC, Hands On Education, and others where parent_company ≠ canonical_name

#### Directory Profile Link Fix — Phase 2: brand rules for remaining mismatches (`normalise_agents.py`)
- After Phase 1, 17 Thailand agents still missing — `agents.canonical_name` didn't match `agent_social.canonical_name`
- Added 11 new brand rules to `normalise_agents.py`:
  - AVSS branches (uppercase with "&") → "AVSS"
  - Yes Education Group variants → "Yes Education Group(Bangkok)"
  - Expert Education & Visa Services / Expert Group Holdings → "Expert Education - EEVS Thailand"
  - Eduyoung.com / Edu Young.Com → "Eduyoung.Com - Thailand"
  - Beyond Study Center → "Beyond Study Center Co"
  - EDNET CO.,LTD branches → "EDNET CO"
  - FURTHER EDUCATION COMPANY → "Further Education"
  - Imagine Global Edu and Migration (Thailand) → "Imagine Global Edu and Migration- iGEM (Bangkok)"
  - LCI Group → "Liu Cheng International Group"
  - Asiania International Consulting (with trading-as suffix) → "Asiania International Consulting"
  - OEC Global Education (city variants) → "Oec Global Education"
- Re-ran `python3 normalise_agents.py` then `python3 build_agent_html.py`
- Thailand result: **42/44 agents now have Profile links** (2 remaining — Nurture Higher Education Group, i-San International Ed — have no social data in agent_social, so no profile link is correct behaviour)

### Status at End of Session
- All changes pushed to GitHub at commit `8a24dd6`
- GitHub Pages was still deploying when session ended — **verify profile links work tomorrow; try hard refresh (Cmd+Shift+R) if they seem broken**
- If links still missing after GH Pages deploys, check that `a.canonical` field is present in ALL_DATA in the live page source

### Known Issues (Carryover)
- Meta Ad Library: needs proper FB Marketing API token
- YouTube/Instagram null subscriber/follower counts — field mapping issue
- 14 university logos still missing
- Agent deduplication still incomplete globally
- Report generator needs login system before sharing externally
- Thai text truncation in events scraper (`scrape_events.py`)

### Next Session Priorities
1. Verify directory profile links are working on live site (may just need hard refresh)
2. Fix Thai text truncation in `scrape_events.py` — slice at character boundary or bump limit
3. Run events scraper for Nepal (`--country Nepal`)
4. Get FB Marketing API token at work and run Meta Ad Library ingestion
5. Fix YouTube subscriber and Instagram follower null values
6. Download remaining 14 university logos manually

---

## Session: April 27, 2026

### What Was Built

#### Bug fixes — unblocking 5 new priority markets

**Unicode truncation fix (`scrape_events.py`)**
- `fetch_page()` now decodes response bytes as UTF-8 (`r.content.decode("utf-8", errors="replace")`) instead of relying on `r.text`, which defaults to latin-1 when the Content-Type header omits charset
- latin-1 decoding turns each UTF-8 byte into a separate character, so a 3-byte Thai/Vietnamese character became 3 garbage characters — slicing at 12,000 chars then cut mid-sequence and caused Claude JSON parse errors
- Fix applies to all non-ASCII markets: Vietnam, Cambodia, Sri Lanka, Nepal, Indonesia

**YouTube subscriber null fix (`enrich_agents.py` `parse_youtube`)**
- `best_subs` initialised to `None` instead of `0` so we distinguish "no channel identified" (None) from "channel found but Apify didn't return subscriber count" (0)
- `best_subs or None` anti-pattern removed — `yt_subscribers` now stores `best_subs` directly
- Added `subscribers` as an additional fallback field name in the subs extraction chain

**Instagram follower field mapping fix (`enrich_agents.py` `parse_instagram`)**
- Added fallback for actor versions that nest profile data under `profile` or `data` keys
- Added `edge_followed_by.count` fallback (raw Instagram Graph API field name, returned by some Apify actor versions)
- Added `edge_owner_to_timeline_media.count` fallback for post count

### Strategic Focus Update
- Project is now focused on 6 priority markets: Thailand, Vietnam, Nepal, Indonesia, Sri Lanka, Cambodia
- PROJECT.md updated to reflect this

#### Agent Deduplication — 14 new brand rules for 5 new markets (`normalise_agents.py`)

New rules added and applied to all 15,735 agent records:

| Brand | Markets | Raw variants → Canonical |
|-------|---------|--------------------------|
| BridgeBlue | VN, ID, KH, NP, LK | AMS BridgeBlue Cambodia/Indonesia/Vietnam, BridgeBlue Nepal/Sri Lanka → "BridgeBlue" |
| AUG | VN, ID | AusEd-UniEd International Pty Ltd Trading as AUG, AUG (AusEd UniEd Group) – city, AUG - AUSED-UNIED branches → "AUG" |
| SUN Education Group | ID | SUN Education Group (Bali/Bandung/etc.), Sun Education Group Pte Ltd → "SUN Education Group" |
| ICAN Education | ID | ICAN EDUCATION PTE. LTD., ICAN Education Consultant (city branches), PT Info Cemerlang... → "ICAN Education" |
| JACK Study Abroad | VN, ID | JACK StudyAbroad (Indonesia) + JACK Study Abroad (Vietnam) → "JACK Study Abroad" |
| Yes Education (broadened) | KH | Now also catches "Yes Education Cambodia" (previously missed by `^Yes Education Group` rule) |
| Expert Education (broadened) | NP, VN, LK | Now also catches "Expert Group Holdings Pty Ltd" standalone entries |
| PFEC Global | LK | PFEC Global- Sri Lanka, PFEC Global (Colombo) → "PFEC Global" |
| Planet Education | NP, LK | Planet Education - Nepal, Planet Education LLP → "Planet Education" |
| Jeewa Education | LK | Jeewa Education + JEEWA Australian Education Centre branches → "Jeewa Education" |
| PAC Asia | NP, LK | PAC Asia Services, PAC Asia Study abroad, PAC Asia Eduserve LLP → "PAC Asia" |
| Bada Global | VN, ID, NP | Bada Global Pty Ltd - Ho Chi Minh, Bada Global Pty Ltd - Solo... → "Bada Global" |
| Fortrust Education | ID | PT. Indogro Putra Sejahtera (Fortrust...) + Fortrust International Pte Ltd → "Fortrust Education" |
| StudyLink | VN | StudyLink Company Limited + Studylink → "StudyLink" |

Consolidation results per market:
- Nepal: 205 → 148 canonical (28% reduction)
- Indonesia: 167 → 101 canonical (40% reduction)
- Vietnam: 164 → 131 canonical (20% reduction)
- Sri Lanka: 154 → 126 canonical (18% reduction)
- Thailand: 109 → 44 canonical (unchanged — already done)
- Cambodia: 30 → 19 canonical (unchanged — already done)

`build_agent_html.py` run after — all three HTML reports updated.

### Next Session Priorities
1. Run events scraper for Nepal (`--country Nepal`)
2. Run events scraper for Vietnam, Indonesia, Sri Lanka, Cambodia
3. Extend alias table for university mentions to cover all 6 markets
4. Run Apify social enrichment for Vietnam, Nepal, Indonesia, Sri Lanka, Cambodia
5. Get FB Marketing API token and run Meta Ad Library ingestion
6. Download 14 missing university logos manually

---

## Session: April 28, 2026

### What Was Built

#### Events scraper — all 6 priority markets (`scrape_events.py`)

**`load_agents()` fallback fix**
- Script was querying only `agent_social` for agent websites — Cambodia, Vietnam, Indonesia, Sri Lanka had 0 rows there (not yet enriched)
- Added fallback to `agents` table when `agent_social` returns 0 rows for a country
- All 4 new markets now load correctly

**Events results across all 6 markets:**
| Market | Agents | Event Pages | Events |
|--------|--------|-------------|--------|
| Thailand | 37 | 9 | 31 |
| Nepal | 101 | 37 | 62 |
| Cambodia | 10 | 5 | 0 |
| Vietnam | 77 | 21 | 38 |
| Indonesia | 63 | 32 | 42 |
| Sri Lanka | 73 | 27 | 106 |

- Sri Lanka dominant: Jeewa Education had 37 events across two branches; VIEC, Nawaloka, Royal Institute of Colombo all active
- Nepal strong: KIEC (10 events), upGrad GSP (5), Grace International (4), Education Asia (5)
- Cambodia: 5 pages found but no upcoming events

**Other fixes:**
- ANTHROPIC_API_KEY saved to `.env`, `.gitignore` created so key is never committed
- `PYTHONUNBUFFERED=1` added to all background runs to prevent output buffering

#### Social enrichment — 4 new markets (`research_social.py`, `enrich_agents.py`)

**Scripts updated to support all 6 markets** (previously hardcoded to Thailand + Nepal only):
- `research_social.py`: `COUNTRIES` list expanded; `--country` arg already worked
- `enrich_agents.py`: `COUNTRIES` list + SQL filter in `rebuild_profiles()` expanded

**`research_social.py` run for Cambodia, Vietnam, Indonesia, Sri Lanka:**
- Scraped each agent website for Facebook, Instagram, LinkedIn links
- Google Places rating and review count fetched
- Created `agent_social` rows for all 4 markets

**`enrich_agents.py` — new `--batch` mode added:**
- Old mode ran one Apify actor per agent per platform → ~$15 for 19 Cambodia agents (YouTube was the main culprit, running for every agent with a website)
- New `--batch` mode: one Apify run per platform per country (IG batch, TikTok batch, Facebook batch, LinkedIn per-URL)
- YouTube scraper removed from batch mode — keyword-based, unreliable, expensive
- New functions: `enrich_tiktok_batch`, `enrich_facebook_batch`, `enrich_linkedin_batch`, `enrich_country_batch`
- LinkedIn: `harvestapi/linkedin-company` doesn't support true batching (only processes first URL); fixed to loop per-URL — still cheap at $4/1000 companies

**Enrichment results across all 6 markets:**
| Market | Agents | IG w/data | TikTok w/data | LinkedIn w/data | Avg Score |
|--------|--------|-----------|---------------|-----------------|-----------|
| Nepal | 103 | 0* | 10 | 30 | 5.5 |
| Cambodia | 19 | 8 | 2 | 3 | 5.3 |
| Thailand | 65 | 25 | 18 | 10 | 5.2 |
| Sri Lanka | 126 | 47 | 14 | 30 | 4.9 |
| Vietnam | 131 | 32 | 18 | 15 | 4.4 |
| Indonesia | 101 | 32 | 10 | 10 | 4.0 |

*Nepal Instagram showing 0 with data — likely a field issue from an earlier partial run. Needs investigation.

### Known Issues (Carryover)
- Nepal Instagram followers showing 0 — field mapping issue from partial earlier run
- Facebook follower counts not captured (Apify FB Pages Scraper returns page data but follower field often null)
- Meta Ad Library: needs proper FB Marketing API token
- 14 university logos still missing
- Agent deduplication still incomplete globally
- Report generator needs login system before sharing externally

### Next Session Priorities
1. Fix Nepal Instagram followers field issue
2. Investigate Facebook follower count null (check raw Apify output)
3. Run Monash scraper for all 6 markets
4. Get FB Marketing API token and run Meta Ad Library ingestion
5. Download 14 missing university logos manually

---

## Session: April 28, 2026 (continued — profile links for all 6 markets)

### What Was Built

#### SOCIAL_INDEX expanded to all 6 markets (`build_agent_html.py`, `agent-network.html`)

**Root cause**: `SOCIAL_INDEX` was hardcoded with only Thailand + Nepal agents. Directory tab profile links showed "View Profile" for Thailand/Nepal only; all 4 new markets showed no link even after social enrichment.

**Fix**: Added `build_social_index(conn)` function to `build_agent_html.py`:
- Queries all 6 markets from `agent_social`
- Deduplicates by `(canonical_name, country)` — keeps highest `presence_score`, tiebreak by highest `id`
- Returns `{canonical_name: {country: agent_social_id}}`
- Wired into `main()` after COUNTRIES_META replacement; replaces `SOCIAL_INDEX` in `agent-network.html` on every build

**Result**: 522 country-agent entries across 466 agents (was ~145 Thailand+Nepal only)

### What's Working
- Profile links now appear in directory for all 6 markets: Thailand, Nepal, Cambodia, Vietnam, Indonesia, Sri Lanka

### Known Issues (Carryover)
- Nepal Instagram followers showing 0 — field mapping issue from partial earlier run
- Facebook follower counts mostly null (Apify FB Pages Scraper field naming)
- 14 university logos still missing
- Report generator needs login system before sharing externally
- **Events cross-country contamination**: Indonesian events appearing on AECC Thailand profile — agent_events JSONs are keyed by `agent_name` only (no country), so a shared canonical name (e.g. "AECC Global") across markets merges events from all countries into one bucket. Fix: key events by `(agent_name, country)` tuple in `scrape_events.py` output and `build_agent_html.py` ingestion; pass country into `renderEvents()` in `agent-profile.html` and filter on it.
- **Events pages not linked**: Profile page shows events but no link to the source events page. Fix: `scrape_events.py` already captures `events_page_url` per agent — surface it in `renderEvents()` as a "See all events →" link.
- **Agent card layout responsive**: Cards appeared broken on Vietnam profiles — resolved by widening browser window. The `stat-grid` uses `repeat(auto-fit,minmax(150px,1fr))` which collapses at narrow widths. Consider a min-width on the container or a 2-column floor for small screens.

### Meta Ad Library — What Does NOT Work (do not retry these)
- **Official Meta Marketing API (`ads_read`)**: Requires Facebook app approval + identity verification. Blocked. Do not attempt.
- **`apify/facebook-ads-scraper` with `view_all_page_id=` URLs**: Returns `page: null` and `results: []` for all agents — this actor doesn't resolve page-specific queries without auth. Do not use.
- **`apify/facebook-ads-scraper` with keyword search**: Gets blocked on Facebook's GraphQL endpoint (`403 BLOCKED`) on every search request. Do not use.
- **Facebook Pages Scraper (`4Hv5RhChiaDk6iwad`) page IDs**: Returns IDs in `100064XXXXXXXXX` format which do NOT match what the Ad Library uses (shorter legacy IDs like `126353198623`). Never filter Ad Library results by these cached IDs — use `snapshot.page_profile_uri` slug matching instead.
- **`maxResults` on `XtaWFhbtfxyzqrFmd`**: This parameter is NOT a per-URL limit — actor ignores it and fetches everything until timeout. 19 agent name searches → 6,000+ ads in 10 minutes → ~$4.50. Only use this actor with a short `timeout_secs` or single search terms.

### Meta Ad Library — What Works
- Actor `XtaWFhbtfxyzqrFmd` (`facebook-ads-library-scraper`) with keyword search by agent canonical name, filtered by `snapshot.page_profile_uri` slug
- Thailand run (April 28 2026): 6,098 ads fetched, 57 matched to 4 agents (IDP 29, WIN 25, Hands On 2, OEC 1)
- Correct real page IDs discovered: IDP=`126353198623`, WIN=`1805916103018074`, Hands On=`108080895911317`, OEC=`166840886665467`

### Next Session Priorities
1. Fix events cross-country contamination — key by (agent_name, country), filter in profile render
2. Add "See all events →" link to profile page using existing `events_page_url` field
3. Fix Nepal Instagram followers field issue
4. Investigate Facebook follower count null (check raw Apify output)
5. Run Monash scraper for all 6 markets
6. Get FB Graph API user token and run page ID batch resolver
7. Download 14 missing university logos manually

---

## Session: April 30, 2026

### What Was Built

#### Meta Ad Library — Playwright Scraper (all 6 markets)
- `mentions/scrape_meta_ads_playwright.py` rewritten to handle all 6 markets
- Two-phase approach: resolve page IDs first (cached to `fb_page_id_cache.json`), then scrape ad library using `view_all_page_id` — eliminates keyword bleed
- University alias table (`university_alias_table_v2.xlsx`) loaded for uni detection including Thai-script variants
- `mentions/resolve_fb_page_ids.py` written (click-through approach — ultimately didn't work, see issues)
- Per-market CSV output: `meta_ads_{country}_{date}.csv`

#### Results (April 30 run — 209 agents across 6 markets)
**Verified clean results (view_all_page_id with legacy IDs):**
- Thailand — WIN Education: 180 ads (Melbourne, UNSW, Sydney mentioned)
- Thailand — IDP Education: 27 ads (Melbourne mentioned)
- Thailand — Hands On Education: 59 ads
- Thailand — OEC: 2 ads
- Sri Lanka — Asian International Academy: 9 ads
- Vietnam — Universal Study Consulting: 8 ads

### Issues Encountered

#### Facebook Legacy Page ID Problem
- `view_all_page_id` in the Ad Library URL requires a **legacy numeric page ID** (e.g. `126353198623`), not the new-format IDs (`100064...`) that appear in modern Facebook page HTML
- New-format IDs (`100064...`, `100063...` etc.) are NOT accepted by the Ad Library — returns 0 results
- Facebook has removed `fb://page/LEGACY_ID` and other legacy ID patterns from page HTML for pages created post-~2020
- `search_type=page` in the Ad Library URL is silently redirected to `search_type=keyword_unordered` — page-specific search doesn't work via URL parameter
- Click-through approach (search → click page card → extract ID from URL) failed — Facebook shows the landing/category page, not the search results page, for this URL pattern
- Autocomplete search box is not a standard `<input>` and couldn't be reliably targeted

#### What Gets Clean Results
- Only agents with a verified legacy ID in `fb_page_id_cache.json` give bleed-free results
- 16 verified IDs total: 4 patched from April 28 Apify run (IDP, WIN, Hands On, OEC Thailand), 12 others found via HTML parsing

#### What Does NOT Work (do not retry)
- Parsing `fb://page/`, `pageID`, `page_id` from Facebook page HTML → returns new-format `100064...` IDs for modern pages
- `search_type=page&q=SLUG` URL parameter → Facebook redirects to keyword search
- Click-through via Ad Library search results → landing page shown, not search results

### What's Working
- 4 Thailand competitor pages fully clean via `view_all_page_id`
- Per-market CSV files with `page_id` column to distinguish verified vs unverified results
- University alias detection including Thai-script

### Next Session Priorities
1. **Get FB Graph API user token** (basic token from developers.facebook.com/tools/explorer — no app review needed, just FB login) to batch-resolve all remaining page IDs across 6 markets. Script ready at `mentions/resolve_fb_page_ids.py` — just needs token wired in.
2. Fix events cross-country contamination
3. Add "See all events →" link to profile page
4. Fix Nepal Instagram followers field issue
5. Download 14 missing university logos manually

---

## Session: May 7, 2026

### What Was Built

#### UK University Agent Scraper (`scrape_uk_universities.py`)
- New script scraping 11 UK universities across 6 priority markets
- **405 total UK agent records** inserted into agents.db (university_id 43–53)
- Universities: Bristol, Warwick, Bath, Newcastle, Exeter, Lancaster, York, Loughborough, Swansea, Durham, Cardiff
- 9 universities use `requests` + BeautifulSoup (no bot protection)
- Durham: Playwright + playwright-stealth (Cloudflare WAF) — uses rowspan table structure
- Cardiff: Playwright + playwright-stealth (Cloudflare WAF) — per-country URL pattern

#### DB Migration
- Added `country` column to `universities` table (DEFAULT 'Australia')
- All 42 existing Australian university rows backfilled as 'Australia'
- UK universities inserted with `country = 'United Kingdom'`
- `build_agent_html.py` updated to filter `universities` table by `country = 'Australia'` for the "X Australian universities" stat — prevents UK unis inflating the count

#### Agent counts per UK university (6 markets total):
| University | TH | VN | NP | ID | LK | KH | Total |
|---|---|---|---|---|---|---|---|
| Swansea | 13 | 17 | 18 | 15 | 17 | 8 | 88 |
| Exeter | 8 | 16 | 11 | 10 | 12 | 3 | 60 |
| York | 10 | 9 | 4 | 8 | 5 | 2 | 38 |
| Newcastle | 5 | 11 | 5 | 10 | 5 | 0 | 36 |
| Lancaster | 7 | 9 | 6 | 6 | 4 | 4 | 36 |
| Loughborough | 9 | 9 | 3 | 6 | 6 | 1 | 34 |
| Bath | 8 | 5 | 8 | 4 | 3 | 1 | 29 |
| Bristol | 7 | 6 | 1 | 5 | 3 | 2 | 24 |
| Durham | 6 | 7 | 3 | 4 | 4 | 0 | 24 |
| Cardiff | 5 | 6 | 0 | 6 | 4 | 0 | 21 |
| Warwick | 2 | 4 | 2 | 3 | 2 | 2 | 15 |

### Issues Encountered / Notes
- Newcastle has no Cambodia page (404) — no agents for Cambodia
- Durham has no Cambodia agents in their SEA table
- Cardiff has no Nepal or Cambodia advisor pages
- Durham table uses `rowspan` on country cells — each continuation row has only 1 `<td>` (agent name); had to track `current_country` across rows
- Cardiff parser initially grabbed whole-page content (332 agents/country); fixed to target the `<div>` sibling after `<h1>Advisors in...`
- Swansea counts are inflated by "Global*" agents listed in the regional table — these are legitimately authorised globally

### Known Issues (Carryover)
- Nepal Instagram followers showing 0 — field mapping issue
- Facebook follower counts mostly null
- 14 missing Australian university logos
- Report generator needs login system before sharing externally
- Thai text truncation in events scraper (partially fixed earlier)
- UK agents not yet normalised (normalise_agents.py not run yet)
- UK agents not yet in agent-network.html (build_agent_html.py targets AU universities only — need to decide whether to include UK unis in the public network view or keep them as a separate dataset)

### Next Session Priorities
1. Decide: should UK agents appear in agent-network.html alongside Australian unis, or as a separate view?
2. Run normalise_agents.py for UK university agents
3. Optionally run social enrichment (enrich_agents.py) for UK agents
4. Get FB Graph API token for page ID resolver
5. Fix Nepal Instagram followers field issue

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
