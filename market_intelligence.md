# Australian International Student Market Intelligence

## Instructions for Claude Code

-----

## Product Context — Read This First

This document is one component of a **market intelligence platform for Australian universities**. Understanding the commercial context helps Claude Code make better decisions about what to build and how to prioritise.

**The product:** A subscription platform sold to Australian universities giving them intelligence on their agent networks across 64 international source markets.

**The core value proposition (what unis pay for):**

1. **Agent coverage matrix** — which agents are authorised to represent them in each market, and where the gaps are vs competitor universities
1. **Agent activity & social presence scores** — is each agent actually active online right now? Follower counts, post frequency, channel coverage (Instagram, YouTube, LinkedIn, LINE OA etc) — data nobody else has in one place
1. **Market size context** — visa grant trends per market, so unis understand whether a market is growing or declining
1. **Curated resources** — properly attributed links to primary data sources, adding credibility and utility

**What drives revenue:** Items 1 and 2. A uni partnership manager opens Thailand, sees their 8 authorised agents, checks which ones are actually posting content, identifies 3 more active agents they're not currently working with. Actionable, saves time, worth a monthly fee.

**What drives credibility:** Items 3 and 4. A platform that links to UNESCO, World Bank, and Australian Dept of Education alongside its own data signals "built by people who know this industry." This matters when asking a uni to pay a subscription. The resources tab costs almost nothing to build but punches above its weight in making the product feel complete and authoritative.

**Build priority:** Agent coverage and social data first. Market size and resources are supporting layers — valuable but not the reason someone subscribes.

-----

This document tells Claude Code how to process and display a **market size block** and **resources tab** for each country in the agent network database.

-----

## Scope — What This Builds

A market size block for each country page showing:

1. **Headline** — offshore visa grants, latest complete financial year
1. **Trend** — offshore grants across last 3 complete financial years + YoY %
1. **Onshore grants** — last 3 years alongside offshore
1. **% Offshore** — offshore as share of total, per year
1. **By level (offshore only, latest year)** — HE / VET / ELICOS / Schools / Other
1. **YTD partial year** — current FY to latest month, shown as context only (not used for trend)
1. **Link** — AEI interactive report for commencement/sector detail

-----

## Why Visa Grants, Not Commencements

**One offshore visa grant = one person** who decided to come to Australia from that country. Clean headcount proxy.

**Commencements overcount.** A student doing ELICOS then a Bachelor in the same year = 2 commencements, 1 person. Useful for sector mix analysis but not headcount.

**Offshore vs Onshore matters.** Offshore = decision made in the home country — the true market demand signal. Onshore = student already in Australia changing or extending visa — a different dynamic, shown for context but not the headline number.

-----

## What Is NOT Possible From Public Data

- Students from a specific nationality by university ❌
- Students from a specific nationality by state ❌

The AEI pivot rows are fixed to Sector. Nationality is a page filter only. The HE institution pivot has Citizenship = Overseas/Domestic only — not by individual nationality.

-----

## Source Data

**Publisher:** Australian Department of Home Affairs
**File:** `bp0015l-student-visas-granted-report-locked-at-2026-02-28-v100.xlsx`
**Local copy:** `marketintelligencereports/` folder on MacBook desktop
**Sheet:** `Granted (Month)`
**Download page:** `https://data.gov.au/data/dataset/student-visas`

**Financial years available:** 2005-06 through 2024-25 (complete) + 2025-26 to Feb 2026 (partial/YTD)

**Use for trend:** Last 3 complete financial years — `2022-23`, `2023-24`, `2024-25`

**Show as YTD context only:** `2025-26 to 28 February 2026` — label clearly as partial, exclude from trend and YoY calculations

**Pivot filters available:**

- `Citizenship Country` — set to target country
- `Client Location` — values: `Offshore` / `Onshore`
- `Age Group`, `Gender`, `Sector`, `State`, `Month` — leave as (All) unless specified

**Sectors in file:**

- Higher Education Sector
- Vocational Education and Training Sector
- Independent ELICOS Sector
- Schools Sector
- Postgraduate Research Sector
- Non-Award Sector
- Foreign Affairs or Defence Sector

**Applicant types:**

- `Primary` = the student — use this for all calculations
- `Secondary` = dependants — exclude

**Year format:** Australian financial years (July–June). Display as-is — do not convert to calendar years. Label on site as "Financial Year (Jul–Jun)".

-----

## Two Exports Required Per Country

Because `Client Location` is a pivot page filter, you need **two separately filtered Excel exports per country**:

|Export  |Citizenship Country|Client Location|Save as                             |
|--------|-------------------|---------------|------------------------------------|
|Offshore|[country]          |Offshore       |`data/raw/visa_{slug}_offshore.xlsx`|
|Onshore |[country]          |Onshore        |`data/raw/visa_{slug}_onshore.xlsx` |

**Process in Excel:**

1. Open `bp0015l-student-visas-granted-report-locked-at-2026-02-28-v100.xlsx`
1. Go to sheet `Granted (Month)`
1. Set `Citizenship Country` = target country
1. Set `Client Location` = `Offshore` → Save copy as offshore file
1. Set `Client Location` = `Onshore` → Save copy as onshore file
1. Repeat for each country

One source file covers all 64 markets — just change the two filters per country.

-----

## Country Name Mapping

```python
HOMEAFFAIRS_COUNTRY_MAP = {
    "Vietnam":     "Viet Nam",
    "China":       "China (People's Republic of)",
    "Hong Kong":   "Hong Kong (SAR of China)",
    "South Korea": "Korea, Republic of",
    "Taiwan":      "Taiwan",
    # Most others match standard English name exactly
    # Inspect unique Citizenship Country values in the file to verify edge cases
}
```

-----

## Processing Code

### Parse a single filtered export

> **Note:** Use `pandas` to read the Excel files — do **not** use `openpyxl` directly.
> The Home Affairs exports contain pivot caches that crash `openpyxl.load_workbook`.
> Pandas loads the sheet data without triggering the pivot cache.

```python
import re
import pandas as pd

COMPLETE_YEARS = ["2022-23", "2023-24", "2024-25"]
PARTIAL_YEAR   = "2025-26 to 28 February 2026"
SECTORS = [
    "Higher Education Sector",
    "Vocational Education and Training Sector",
    "Independent ELICOS Sector",
    "Schools Sector",
    "Postgraduate Research Sector",
    "Non-Award Sector",
    "Foreign Affairs or Defence Sector",
]
SECTOR_LABELS = {
    "Higher Education Sector":                       "Higher Education",
    "Vocational Education and Training Sector":      "VET",
    "Independent ELICOS Sector":                     "ELICOS",
    "Schools Sector":                                "Schools",
    "Postgraduate Research Sector":                  "Postgraduate Research",
    "Non-Award Sector":                              "Non-Award",
    "Foreign Affairs or Defence Sector":             "Foreign Affairs / Defence",
}

def parse_visa_export(filepath):
    df = pd.read_excel(filepath, sheet_name='Granted (Month)', header=None)
    rows = df.values.tolist()

    # Active filters — scan early rows for string key/value pairs
    filters = {}
    for row in rows[:15]:
        k = row[0] if len(row) > 0 else None
        v = row[1] if len(row) > 1 else None
        if isinstance(k, str) and isinstance(v, str):
            filters[k.strip()] = v.strip()

    # FY header row — first row that contains a "YYYY-YY" pattern in any cell
    fy_index = {}
    for row in rows:
        candidates = {
            i: str(cell).strip()
            for i, cell in enumerate(row)
            if isinstance(cell, str) and re.search(r'\d{4}-\d{2}', cell)
        }
        if candidates:
            fy_index = {label: i for i, label in candidates.items()}
            break

    all_years = COMPLETE_YEARS + [PARTIAL_YEAR]

    def cell_val(row, yr):
        if yr not in fy_index:
            return None
        v = row[fy_index[yr]] if fy_index[yr] < len(row) else None
        return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v

    # Scan all rows for sector names and "Primary Total"
    sector_data = {}
    primary_total = {}

    for row in rows:
        col_a = row[0] if len(row) > 0 else None
        col_b = row[1] if len(row) > 1 else None

        if isinstance(col_b, str) and col_b.strip() in SECTORS:
            canonical = SECTOR_LABELS[col_b.strip()]
            sector_data[canonical] = {yr: cell_val(row, yr) for yr in all_years}

        if isinstance(col_a, str) and col_a.strip() == "Primary Total":
            primary_total = {yr: cell_val(row, yr) for yr in all_years}

    return filters, primary_total, sector_data


def yoy_pct(current, previous):
    if not previous or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)

def trend_arrow(yoy):
    if yoy is None: return "—"
    if yoy > 5:  return "↑"
    if yoy < -5: return "↓"
    return "→"
```

### Build market data object

```python
def build_market_data(country, offshore_file, onshore_file):
    _, offshore_total, offshore_sectors = parse_visa_export(offshore_file)
    _, onshore_total,  _                = parse_visa_export(onshore_file)

    # Trend across last 3 complete years
    years = COMPLETE_YEARS
    offshore_trend = {}
    for i, yr in enumerate(years):
        prev = offshore_total.get(years[i-1]) if i > 0 else None
        curr = offshore_total.get(yr)
        yoy  = yoy_pct(curr, prev)
        offshore_trend[yr] = {
            "grants": curr,
            "yoy_pct": yoy,
            "trend": trend_arrow(yoy)
        }

    # % offshore per year
    pct_offshore = {}
    for yr in years:
        off = offshore_total.get(yr) or 0
        on  = onshore_total.get(yr) or 0
        total = off + on
        pct_offshore[yr] = round((off / total * 100), 1) if total else None

    return {
        "country": country,
        "data_as_of": "February 2026",
        "complete_years": years,
        "partial_year": {
            "label": "2025-26 YTD (to Feb 2026)",
            "offshore": offshore_total.get(PARTIAL_YEAR),
            "onshore":  onshore_total.get(PARTIAL_YEAR),
        },
        "offshore": offshore_trend,
        "onshore": {
            yr: {"grants": onshore_total.get(yr)} for yr in years
        },
        "pct_offshore": pct_offshore,
        "by_level_offshore_latest": {
            label: data.get("2024-25")
            for label, data in offshore_sectors.items()
        },
        "sources": {
            "visa_data": {
                "label": "Australian Department of Home Affairs",
                "url": "https://data.gov.au/data/dataset/student-visas"
            },
            "aei_interactive": {
                "label": "Explore commencements by sector — Australian Dept of Education",
                "url": "https://app.powerbi.com/view?r=eyJrIjoiNTY0NWI1ODctODA2Mi00M2VmLThkZWEtZTJlZDc4OTAzMzBiIiwidCI6ImRkMGNmZDE1LTQ1NTgtNGIxMi04YmFkLWVhMjY5ODRmYzQxNyJ9"
            }
        }
    }
```

-----

## Display Block

```
MARKET SIZE                          Student visas granted  |  FY (Jul–Jun)
Source: Australian Dept of Home Affairs

  ┌─────────────────────────────────────────────────────────────────┐
  │  OFFSHORE GRANTS        2022-23    2023-24    2024-25           │
  │  ── headline metric ──  x,xxx      x,xxx      x,xxx  ↓ -xx%    │
  │                                                                  │
  │  Onshore grants         x,xxx      x,xxx      x,xxx             │
  │  % Offshore               xx%        xx%        xx%             │
  └─────────────────────────────────────────────────────────────────┘

  BY LEVEL — Offshore 2024-25  (sorted by grant count descending)
  Higher Education        x,xxx
  VET                     x,xxx
  ELICOS                  x,xxx
  Schools                   xxx
  Postgraduate Research     xxx
  Other                     xxx

  2025-26 YTD (to Feb 2026)   Offshore: x,xxx  |  Onshore: x,xxx
  ── Partial year — not used for trend ──

  Explore commencements by sector →
  [Australian Dept of Education — Interactive Report]
```

-----

## Output Files

```
marketintelligencereports/
├── bp0015l-student-visas-granted-report-locked-at-2026-02-28-v100.xlsx  ← source
├── data/
│   ├── raw/
│   │   ├── visa_thailand_offshore.xlsx
│   │   ├── visa_thailand_onshore.xlsx
│   │   ├── visa_nepal_offshore.xlsx
│   │   ├── visa_nepal_onshore.xlsx
│   │   └── visa_{slug}_{location}.xlsx    # two per market
│   └── processed/
│       ├── market_size_2026-02.json       # all countries
│       └── market_size_2026-02.csv        # flat version
└── market_intelligence.md                 # this file
```

-----

## Attribution

Display on every market page:

> Visa data: [Australian Department of Home Affairs](https://data.gov.au/data/dataset/student-visas)
> Commencement data: [Australian Department of Education](https://www.education.gov.au/international-education-data-and-research)

Do not present government data as proprietary. Always link back to source.

-----

## Resources Tab

Each market page has a **Resources** tab alongside Coverage Matrix, Agent Ranking, Universities, Agent Cards, Directory, Market Size, and Global Agents.

The Resources tab contains curated links to primary data sources — properly attributed, no scraped content. The goal is to make the platform feel authoritative and save uni marketing teams research time.

### URL Construction

Most links can be generated programmatically from the country slug or World Bank code. Build a lookup table mapping each of the 64 markets to their respective codes.

```python
COUNTRY_RESOURCES = {
    "Thailand": {
        "worldbank_code": "TH",
        "datareportal_slug": "thailand",
        "factbook_slug": "thailand",
        "whed_country": "Thailand",
    },
    "Nepal": {
        "worldbank_code": "NP",
        "datareportal_slug": "nepal",
        "factbook_slug": "nepal",
        "whed_country": "Nepal",
    },
    # ... repeat for all 64 markets
}
```

### Resources Tab Template

```
RESOURCES — {Country}

AUSTRALIAN STUDENT DATA
─────────────────────────────────────────────────────
Student visa grants (offshore/onshore)
Australian Department of Home Affairs
data.gov.au/data/dataset/student-visas

Commencements & enrolments by sector — Interactive Report
Australian Department of Education
[Power BI link]

DIGITAL & SOCIAL MEDIA
─────────────────────────────────────────────────────
Digital 2026: {Country} — internet, social media & platform usage
DataReportal / We Are Social / Meltwater
datareportal.com/reports/digital-2026-{slug}

ECONOMY & DEMOGRAPHICS
─────────────────────────────────────────────────────
Economy & population data
World Bank
data.worldbank.org/country/{code}

Country profile — demographics, education system, economy
CIA World Factbook
cia.gov/the-world-factbook/countries/{slug}

STUDENT MOBILITY
─────────────────────────────────────────────────────
Outbound & inbound international student mobility
UNESCO Institute for Statistics
uis.unesco.org/en/topic/international-student-mobility

Accredited universities in {Country}
WHED — World Higher Education Database (IAU)
whed.net/home.php
[Note: WHED is the standard reference used by Australian universities
to verify overseas qualifications]

ATTRIBUTION
─────────────────────────────────────────────────────
Data on this page sourced from Australian Department of Home Affairs,
Australian Department of Education, DataReportal, World Bank,
CIA World Factbook, UNESCO UIS, and IAU WHED.
All links direct to primary sources.
```

### Notes on Specific Sources

**DataReportal** — URL pattern `datareportal.com/reports/digital-2026-{slug}` is consistent across all countries. Free, no login required. Published November 2025 onwards for individual countries.

**World Bank** — `data.worldbank.org/country/{2-letter-code}`. GDP per capita is the key metric — proxy for family ability to afford Australian university fees.

**CIA World Factbook** — `cia.gov/the-world-factbook/countries/{slug}`. Covers population, median age, education spending, literacy. Updated regularly. Free.

**UNESCO UIS** — No clean per-country URL. Link to the topic page and let users filter. Both outbound mobility (students leaving) and inbound mobility (students arriving) are available — inbound figures give context on market sophistication and international education maturity.

**WHED** — `whed.net/home.php`. Filter by country. This is the database Australian admissions offices use to verify whether an overseas university is accredited. Directly relevant for an agent network platform — shows the pool of feeder institutions in each market.

**Market-specific additions** (where official government lists are reliable):

- China: Ministry of Education university list — `gaokao.chsi.com.cn`
- India: UGC recognised universities — `ugc.ac.in`
- Add others as identified

-----

## Refresh Schedule

|Source                      |Frequency |Notes                                                         |
|----------------------------|----------|--------------------------------------------------------------|
|Home Affairs visa file      |Monthly   |Updated end of previous month — check data.gov.au for new file|
|AEI Power BI report         |Live      |Always current when users click through — no action needed    |
|DataReportal country reports|Annual    |New editions published Nov/Dec each year                      |
|World Bank                  |Continuous|Live data, link is always current                             |
|CIA World Factbook          |Continuous|Updated regularly, link is always current                     |
|UNESCO UIS                  |Annual    |Updated with academic year data                               |
|WHED                        |Continuous|IAU maintains ongoing — link is always current                |
