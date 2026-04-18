#!/usr/bin/env python3
"""
build_market_blocks.py — Generate HTML market size blocks from processed JSON.

Usage:
    python3 build_market_blocks.py                     # latest JSON in data/processed/
    python3 build_market_blocks.py --country Thailand  # single country preview
    python3 build_market_blocks.py --file data/processed/market_size_2026-02.json

Output:
    data/processed/market_blocks_2026-02.html    standalone preview
    data/processed/market_snippets_2026-02.json  per-country HTML for embedding
"""

import argparse
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROC_DIR = BASE_DIR / "data" / "processed"

HA_URL  = "https://data.gov.au/data/dataset/student-visas"
AEI_URL = "https://app.powerbi.com/view?r=eyJrIjoiNTY0NWI1ODctODA2Mi00M2VmLThkZWEtZTJlZDc4OTAzMzBiIiwidCI6ImRkMGNmZDE1LTQ1NTgtNGIxMi04YmFkLWVhMjY5ODRmYzQxNyJ9"

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
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(v):
    if v is None:
        return '<span class="nil">—</span>'
    return f"{v:,}"


def trend_badge(yoy, trend):
    if yoy is None:
        return ""
    if trend == "↑":
        cls = "badge-up"
    elif trend == "↓":
        cls = "badge-down"
    else:
        cls = "badge-flat"
    sign = "+" if yoy > 0 else ""
    return f'<span class="badge {cls}">{trend} {sign}{yoy}%</span>'


def pct_bar(pct):
    """Small inline bar showing % offshore."""
    if pct is None:
        return "—"
    return (
        f'<span class="pct-val">{pct}%</span>'
        f'<span class="pct-bar-wrap"><span class="pct-bar" style="width:{min(pct,100)}%"></span></span>'
    )


# ── Resources tab ─────────────────────────────────────────────────────────────

def _res_link(title, source, url, note=None):
    url_display = re.sub(r'^https?://', '', url)
    note_html = f'<div class="res-note">{note}</div>' if note else ''
    return (
        f'<a class="res-link" href="{url}" target="_blank" rel="noopener">'
        f'<div class="res-title">{title}</div>'
        f'<div class="res-source">{source}</div>'
        f'<div class="res-url">{url_display}</div>'
        f'{note_html}'
        f'</a>'
    )


def _res_group(heading, *links):
    return (
        f'<div class="res-group">'
        f'<div class="res-group-head">{heading}</div>'
        + ''.join(links)
        + '</div>'
    )


def build_resources_html(country: str) -> str:
    r = COUNTRY_RESOURCES.get(country)
    if not r:
        return (
            '<div class="res-unavailable">'
            f'Resource index for {country} not yet configured.'
            '</div>'
        )

    wb_code = r["worldbank_code"]
    dr_slug  = r["datareportal_slug"]
    fb_slug  = r["factbook_slug"]

    groups = [
        _res_group(
            "AUSTRALIAN STUDENT DATA",
            _res_link(
                "Student visa grants (offshore / onshore)",
                "Australian Department of Home Affairs",
                "https://data.gov.au/data/dataset/student-visas",
            ),
            _res_link(
                "Commencements &amp; enrolments by sector — Interactive Report",
                "Australian Department of Education",
                AEI_URL,
            ),
        ),
        _res_group(
            "DIGITAL &amp; SOCIAL MEDIA",
            _res_link(
                f"Digital 2026: {country} — internet, social media &amp; platform usage",
                "DataReportal / We Are Social / Meltwater",
                f"https://datareportal.com/reports/digital-2026-{dr_slug}",
            ),
        ),
        _res_group(
            "ECONOMY &amp; DEMOGRAPHICS",
            _res_link(
                "Economy &amp; population data",
                "World Bank",
                f"https://data.worldbank.org/country/{wb_code}",
            ),
            _res_link(
                "Country profile — demographics, education system, economy",
                "CIA World Factbook",
                f"https://www.cia.gov/the-world-factbook/countries/{fb_slug}/",
            ),
        ),
        _res_group(
            "STUDENT MOBILITY",
            _res_link(
                "Outbound &amp; inbound international student mobility",
                "UNESCO Institute for Statistics",
                "https://uis.unesco.org/en/topic/international-student-mobility",
            ),
            _res_link(
                f"Accredited universities in {country}",
                "WHED — World Higher Education Database (IAU)",
                "https://www.whed.net/home.php",
                note="The standard reference used by Australian universities to verify overseas qualifications.",
            ),
        ),
    ]

    attribution = (
        '<div class="res-attribution">'
        'Data sourced from Australian Department of Home Affairs, '
        'Australian Department of Education, DataReportal, World Bank, '
        'CIA World Factbook, UNESCO UIS, and IAU WHED. '
        'All links direct to primary sources.'
        '</div>'
    )

    return (
        '<div class="resources-pane">'
        + ''.join(groups)
        + attribution
        + '</div>'
    )


# ── HTML block builder ────────────────────────────────────────────────────────

def build_block_html(d: dict) -> str:
    country   = d["country"]
    as_of     = d["data_as_of"]
    yrs       = d["complete_years"]
    off       = d["offshore"]
    on        = d["onshore"]
    pct       = d["pct_offshore"]
    lvl       = d["by_level_offshore_latest"]
    ytd       = d["partial_year"]
    latest_yr = yrs[-1]

    slug    = re.sub(r'[^a-z0-9]+', '-', country.lower()).strip('-')
    tab_mkt = f"tab-mkt-{slug}"
    tab_res = f"tab-res-{slug}"

    # Headline — latest complete year offshore
    headline_val   = off[latest_yr]["grants"]
    headline_yoy   = off[latest_yr]["yoy_pct"]
    headline_trend = off[latest_yr]["trend"]

    # Year header row
    yr_headers = "".join(f"<th>{y}</th>" for y in yrs)

    # Offshore trend rows
    offshore_cells = "".join(
        f"<td>{fmt(off[y]['grants'])}</td>" for y in yrs
    )
    badge_cells = "".join(
        f"<td>{trend_badge(off[y]['yoy_pct'], off[y]['trend'])}</td>"
        for y in yrs
    )
    onshore_cells = "".join(
        f"<td>{fmt(on[y]['grants'])}</td>" for y in yrs
    )
    pct_cells = "".join(
        f"<td>{pct_bar(pct[y])}</td>" for y in yrs
    )

    # Sector breakdown bars — sorted by grant count descending, nulls excluded
    level_vals = [(label, val) for label, val in lvl.items() if val]
    max_val    = max((v for _, v in level_vals), default=1)
    level_rows = ""
    for label, val in sorted(level_vals, key=lambda x: -x[1]):
        bar_pct = round(val / max_val * 100) if max_val else 0
        level_rows += f"""
            <div class="level-row">
                <div class="level-label">{label}</div>
                <div class="level-bar-wrap">
                    <div class="level-bar" style="width:{bar_pct}%"></div>
                </div>
                <div class="level-val">{val:,}</div>
            </div>"""

    # YTD partial
    ytd_off = f"{ytd['offshore']:,}" if ytd.get("offshore") else "—"
    ytd_on  = f"{ytd['onshore']:,}" if ytd.get("onshore") else "—"

    market_pane = f"""
        <!-- Headline -->
        <div class="headline-strip">
            <div class="headline-num">{fmt(headline_val)}</div>
            <div class="headline-desc">
                offshore grants &nbsp;{latest_yr}
                {trend_badge(headline_yoy, headline_trend)}
            </div>
        </div>

        <!-- Trend table -->
        <table class="trend-table">
            <thead>
                <tr><th></th>{yr_headers}</tr>
            </thead>
            <tbody>
                <tr class="row-offshore">
                    <td class="row-label">Offshore grants</td>
                    {offshore_cells}
                </tr>
                <tr class="row-yoy">
                    <td class="row-label muted">YoY</td>
                    {badge_cells}
                </tr>
                <tr class="row-onshore">
                    <td class="row-label muted">Onshore grants</td>
                    {onshore_cells}
                </tr>
                <tr class="row-pct">
                    <td class="row-label muted">% Offshore</td>
                    {pct_cells}
                </tr>
            </tbody>
        </table>

        <!-- By level -->
        <div class="section-head">BY LEVEL — Offshore {latest_yr}</div>
        <div class="level-chart">
            {level_rows}
        </div>

        <!-- YTD -->
        <div class="ytd-strip">
            <span class="ytd-label">{ytd['label']}</span>
            <span class="ytd-vals">Offshore: {ytd_off}&nbsp;&nbsp;|&nbsp;&nbsp;Onshore: {ytd_on}</span>
            <span class="ytd-note">Partial year — not used for trend</span>
        </div>

        <!-- Footer -->
        <div class="market-footer">
            <a class="aei-link" href="{AEI_URL}" target="_blank" rel="noopener">
                Explore commencements by sector →
                <span class="aei-source">Australian Dept of Education — Interactive Report</span>
            </a>
            <div class="attribution">
                Visa data: <a href="{HA_URL}" target="_blank">Australian Department of Home Affairs</a>
                &nbsp;|&nbsp;
                <a href="https://www.education.gov.au/international-education-data-and-research" target="_blank">
                    Australian Department of Education
                </a>
            </div>
        </div>"""

    return f"""
    <div class="market-block" id="market-{slug}">

        <div class="market-header">
            <div>
                <div class="market-label">MARKET SIZE</div>
                <div class="market-country">{country}</div>
            </div>
            <div class="market-meta">Student visas granted&nbsp;&nbsp;|&nbsp;&nbsp;FY (Jul–Jun)<br>
                <span class="as-of">Data to {as_of}</span>
            </div>
        </div>

        <div class="tab-bar">
            <button class="tab active" onclick="switchTab(this,'{tab_mkt}')">Market Size</button>
            <button class="tab" onclick="switchTab(this,'{tab_res}')">Resources</button>
        </div>

        <div id="{tab_mkt}" class="tab-pane">
            {market_pane}
        </div>

        <div id="{tab_res}" class="tab-pane" style="display:none">
            {build_resources_html(country)}
        </div>

    </div>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
.market-block {
    background: #111827;
    border: 1px solid #1f2d45;
    border-radius: 14px;
    padding: 28px 32px;
    margin: 24px 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #d1d5db;
    max-width: 720px;
}
.market-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #1f2d45;
}
.market-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #4b5563;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.market-country {
    font-size: 22px;
    font-weight: 700;
    color: #f9fafb;
}
.market-meta {
    font-size: 12px;
    color: #6b7280;
    text-align: right;
    line-height: 1.6;
}
.as-of { color: #4b5563; }

/* Tab bar */
.tab-bar {
    display: flex;
    gap: 0;
    margin-bottom: 20px;
    border-bottom: 1px solid #1f2d45;
}
.tab {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #6b7280;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    padding: 8px 16px 9px;
    margin-bottom: -1px;
    font-family: inherit;
    letter-spacing: 0.2px;
    transition: color 0.12s, border-color 0.12s;
}
.tab:hover { color: #9ca3af; }
.tab.active {
    color: #60a5fa;
    border-bottom-color: #60a5fa;
}

/* Headline */
.headline-strip {
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin-bottom: 20px;
    padding: 16px 20px;
    background: #0f1a2e;
    border-radius: 10px;
    border-left: 3px solid #e63946;
}
.headline-num {
    font-size: 36px;
    font-weight: 800;
    color: #f9fafb;
    font-variant-numeric: tabular-nums;
}
.headline-desc {
    font-size: 14px;
    color: #9ca3af;
    display: flex;
    align-items: center;
    gap: 10px;
}

/* Trend table */
.trend-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    margin-bottom: 24px;
}
.trend-table th {
    text-align: right;
    padding: 8px 10px;
    font-size: 12px;
    color: #6b7280;
    font-weight: 600;
    border-bottom: 1px solid #1f2d45;
}
.trend-table th:first-child { text-align: left; }
.trend-table td {
    padding: 8px 10px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    border-bottom: 1px solid #0d1520;
}
.row-label { text-align: left !important; color: #d1d5db; }
.row-label.muted { color: #6b7280; font-size: 13px; }
.row-offshore td { color: #f9fafb; font-weight: 600; }
.row-yoy td { vertical-align: middle; }
.row-onshore td { color: #9ca3af; }
.row-pct td { color: #9ca3af; vertical-align: middle; }
.nil { color: #374151; }

/* Badges */
.badge {
    display: inline-block;
    font-size: 12px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
}
.badge-up   { background: #052e16; color: #4ade80; }
.badge-down { background: #2d0a0a; color: #f87171; }
.badge-flat { background: #1c1407; color: #fbbf24; }

/* % offshore bar */
.pct-val { font-size: 12px; color: #9ca3af; margin-right: 6px; }
.pct-bar-wrap {
    display: inline-block;
    width: 50px;
    height: 5px;
    background: #1f2937;
    border-radius: 3px;
    vertical-align: middle;
}
.pct-bar {
    display: block;
    height: 5px;
    background: #0f3460;
    border-radius: 3px;
}

/* Section head */
.section-head {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #4b5563;
    text-transform: uppercase;
    margin-bottom: 12px;
}

/* Level chart */
.level-chart { margin-bottom: 24px; }
.level-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 7px;
    font-size: 13px;
}
.level-label { width: 175px; color: #9ca3af; flex-shrink: 0; }
.level-bar-wrap {
    flex: 1;
    height: 8px;
    background: #1f2937;
    border-radius: 3px;
}
.level-bar {
    height: 8px;
    background: linear-gradient(90deg, #0f3460, #1a6cc4);
    border-radius: 3px;
}
.level-val { width: 60px; text-align: right; color: #d1d5db; font-variant-numeric: tabular-nums; }

/* YTD */
.ytd-strip {
    background: #0a0f1a;
    border: 1px dashed #1f2d45;
    border-radius: 8px;
    padding: 12px 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    font-size: 13px;
    margin-bottom: 20px;
}
.ytd-label { font-weight: 600; color: #9ca3af; }
.ytd-vals { color: #d1d5db; font-variant-numeric: tabular-nums; }
.ytd-note { color: #4b5563; font-style: italic; font-size: 12px; margin-left: auto; }

/* Footer */
.market-footer {
    padding-top: 16px;
    border-top: 1px solid #1f2d45;
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.aei-link {
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: #60a5fa;
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
}
.aei-link:hover { color: #93c5fd; }
.aei-source { font-size: 12px; font-weight: 400; color: #4b5563; }
.attribution { font-size: 11px; color: #374151; }
.attribution a { color: #374151; }
.attribution a:hover { color: #6b7280; }

/* Resources tab */
.resources-pane { padding-top: 4px; }
.res-group { margin-bottom: 24px; }
.res-group-head {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #4b5563;
    text-transform: uppercase;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #1f2d45;
}
.res-link {
    display: block;
    padding: 10px 12px;
    border-radius: 8px;
    text-decoration: none;
    margin-bottom: 3px;
    border: 1px solid transparent;
    transition: background 0.12s, border-color 0.12s;
}
.res-link:hover {
    background: #0f1a2e;
    border-color: #1f2d45;
}
.res-title {
    font-size: 13px;
    font-weight: 600;
    color: #d1d5db;
    margin-bottom: 2px;
}
.res-source {
    font-size: 11px;
    color: #6b7280;
    margin-bottom: 2px;
}
.res-url {
    font-size: 11px;
    color: #374151;
    font-family: 'SF Mono', 'Fira Code', monospace;
}
.res-note {
    font-size: 11px;
    color: #4b5563;
    font-style: italic;
    margin-top: 4px;
}
.res-attribution {
    font-size: 11px;
    color: #374151;
    border-top: 1px solid #1f2d45;
    padding-top: 14px;
    margin-top: 4px;
    line-height: 1.7;
}
.res-unavailable {
    color: #4b5563;
    font-size: 13px;
    font-style: italic;
    padding: 20px 0;
}
"""

JS = """
function switchTab(btn, tabId) {
    var block = btn.closest('.market-block');
    block.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
    block.querySelectorAll('.tab-pane').forEach(function(p) { p.style.display = 'none'; });
    btn.classList.add('active');
    document.getElementById(tabId).style.display = '';
}
"""


def build_standalone_html(blocks: str, tag: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Intelligence Blocks — {tag}</title>
<style>
body {{ background: #060b14; padding: 48px 24px; }}
h1 {{ color: #9ca3af; font-family: sans-serif; font-size: 14px;
     letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px; }}
h2 {{ color: #374151; font-family: sans-serif; font-size: 12px; margin-bottom: 32px; }}
{CSS}
</style>
</head>
<body>
<h1>Market Intelligence — Visa Grants</h1>
<h2>Data to February 2026 &nbsp;|&nbsp; Source: Australian Dept of Home Affairs</h2>
{blocks}
<script>{JS}</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file",    help="Path to JSON file")
    parser.add_argument("--country", help="Filter to single country")
    args = parser.parse_args()

    if args.file:
        json_path = Path(args.file)
    else:
        files = sorted(PROC_DIR.glob("market_size_*.json"), reverse=True)
        if not files:
            print("No market_size JSON in data/processed/ — run process_market_data.py first.")
            return
        json_path = files[0]
        print(f"Using: {json_path.name}")

    with open(json_path) as f:
        all_data = json.load(f)

    if args.country:
        all_data = [d for d in all_data if d["country"].lower() == args.country.lower()]
        if not all_data:
            print(f"'{args.country}' not found in {json_path.name}")
            return

    blocks_html = ""
    for d in all_data:
        blocks_html += build_block_html(d)
        print(f"  ✓ {d['country']}")

    tag = re.search(r"\d{4}-\d{2}", json_path.name)
    tag = tag.group(0) if tag else "latest"

    # Standalone preview
    preview_path = PROC_DIR / f"market_blocks_{tag}.html"
    with open(preview_path, "w") as f:
        f.write(build_standalone_html(blocks_html, tag))
    print(f"\n✅ Preview  → {preview_path}")

    # Per-country snippets for embedding
    snippets = {d["country"]: build_block_html(d) for d in all_data}
    snip_path = PROC_DIR / f"market_snippets_{tag}.json"
    with open(snip_path, "w") as f:
        json.dump(snippets, f, indent=2)
    print(f"✅ Snippets → {snip_path}")


if __name__ == "__main__":
    main()
