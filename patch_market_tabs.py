#!/usr/bin/env python3
"""
patch_market_tabs.py — Add Market Size / Resources sub-tabs to agent-network.html.

Applies three patches:
  1. CSS  — sub-tab and resource-link styles
  2. JS   — COUNTRY_RESOURCES const (slugs + WB codes for 77 countries)
  3. JS   — replace buildMarketData() with version that renders both sub-tabs

Run once; safe to re-run (idempotent check on CSS sentinel).
"""

from pathlib import Path

HTML = Path(__file__).parent / "agent-network.html"

# ── 1. CSS ───────────────────────────────────────────────────────────────────

CSS_ANCHOR = ".tab:hover { color: var(--primary); }"

CSS_NEW = """.tab:hover { color: var(--primary); }

/* Market panel sub-tabs */
.mkt-tabs { display: flex; border-bottom: 2px solid var(--border); margin-bottom: 1.4rem; }
.mkt-tab  { padding: .5rem 1.1rem; cursor: pointer; font-size: .82rem; font-weight: 600; color: #64748B; border-bottom: 3px solid transparent; margin-bottom: -2px; transition: color .2s, border-color .2s; }
.mkt-tab.active { color: var(--primary); border-bottom-color: var(--accent); }
.mkt-tab:hover  { color: var(--primary); }
.res-section { margin-bottom: 1.5rem; }
.res-heading { font-size: .67rem; text-transform: uppercase; letter-spacing: .1em; color: #94A3B8; margin-bottom: .55rem; padding-bottom: .3rem; border-bottom: 1px solid #E8EDF2; font-weight: 700; }
.res-item { display: flex; flex-direction: column; padding: .5rem 0; border-bottom: 1px solid #F1F5F9; }
.res-item:last-child { border-bottom: none; }
.res-item a { font-size: .85rem; font-weight: 600; color: #2563EB; text-decoration: none; }
.res-item a:hover { text-decoration: underline; }
.res-item .res-src { font-size: .72rem; color: #94A3B8; margin-top: .15rem; }"""

# ── 2. COUNTRY_RESOURCES const ───────────────────────────────────────────────

RESOURCES_CONST = """const COUNTRY_RESOURCES = {
  "Argentina":           { wb:"AR", dr:"argentina",            cf:"argentina" },
  "Azerbaijan":          { wb:"AZ", dr:"azerbaijan",           cf:"azerbaijan" },
  "Bahrain":             { wb:"BH", dr:"bahrain",              cf:"bahrain" },
  "Bangladesh":          { wb:"BD", dr:"bangladesh",           cf:"bangladesh" },
  "Bhutan":              { wb:"BT", dr:"bhutan",               cf:"bhutan" },
  "Bolivia":             { wb:"BO", dr:"bolivia",              cf:"bolivia" },
  "Brazil":              { wb:"BR", dr:"brazil",               cf:"brazil" },
  "Brunei":              { wb:"BN", dr:"brunei",               cf:"brunei" },
  "Cambodia":            { wb:"KH", dr:"cambodia",             cf:"cambodia" },
  "Canada":              { wb:"CA", dr:"canada",               cf:"canada" },
  "Chile":               { wb:"CL", dr:"chile",                cf:"chile" },
  "China":               { wb:"CN", dr:"china",                cf:"china",         extra:{label:"Ministry of Education (CHSI)",url:"https://www.chsi.com.cn/en/"} },
  "Colombia":            { wb:"CO", dr:"colombia",             cf:"colombia" },
  "Denmark":             { wb:"DK", dr:"denmark",              cf:"denmark" },
  "Ecuador":             { wb:"EC", dr:"ecuador",              cf:"ecuador" },
  "Egypt":               { wb:"EG", dr:"egypt",                cf:"egypt" },
  "Ethiopia":            { wb:"ET", dr:"ethiopia",             cf:"ethiopia" },
  "Fiji":                { wb:"FJ", dr:"fiji",                 cf:"fiji" },
  "Finland":             { wb:"FI", dr:"finland",              cf:"finland" },
  "France":              { wb:"FR", dr:"france",               cf:"france" },
  "Germany":             { wb:"DE", dr:"germany",              cf:"germany" },
  "Ghana":               { wb:"GH", dr:"ghana",                cf:"ghana" },
  "Hong Kong":           { wb:"HK", dr:"hong-kong",            cf:"hong-kong" },
  "India":               { wb:"IN", dr:"india",                cf:"india",         extra:{label:"UGC Recognised Universities",url:"https://www.ugc.ac.in/"} },
  "Indonesia":           { wb:"ID", dr:"indonesia",            cf:"indonesia" },
  "Iran":                { wb:"IR", dr:"iran",                 cf:"iran" },
  "Italy":               { wb:"IT", dr:"italy",                cf:"italy" },
  "Japan":               { wb:"JP", dr:"japan",                cf:"japan" },
  "Jordan":              { wb:"JO", dr:"jordan",               cf:"jordan" },
  "Kazakhstan":          { wb:"KZ", dr:"kazakhstan",           cf:"kazakhstan" },
  "Kenya":               { wb:"KE", dr:"kenya",                cf:"kenya" },
  "Kuwait":              { wb:"KW", dr:"kuwait",               cf:"kuwait" },
  "Laos":                { wb:"LA", dr:"laos",                 cf:"laos" },
  "Lebanon":             { wb:"LB", dr:"lebanon",              cf:"lebanon" },
  "Macau":               { wb:"MO", dr:"macau",               cf:"macau" },
  "Malawi":              { wb:"MW", dr:"malawi",               cf:"malawi" },
  "Malaysia":            { wb:"MY", dr:"malaysia",             cf:"malaysia" },
  "Maldives":            { wb:"MV", dr:"maldives",             cf:"maldives" },
  "Mauritius":           { wb:"MU", dr:"mauritius",            cf:"mauritius" },
  "Mexico":              { wb:"MX", dr:"mexico",               cf:"mexico" },
  "Mongolia":            { wb:"MN", dr:"mongolia",             cf:"mongolia" },
  "Morocco":             { wb:"MA", dr:"morocco",              cf:"morocco" },
  "Myanmar":             { wb:"MM", dr:"myanmar",              cf:"burma" },
  "Nepal":               { wb:"NP", dr:"nepal",                cf:"nepal" },
  "Netherlands":         { wb:"NL", dr:"netherlands",          cf:"netherlands" },
  "New Zealand":         { wb:"NZ", dr:"new-zealand",          cf:"new-zealand" },
  "Nigeria":             { wb:"NG", dr:"nigeria",              cf:"nigeria" },
  "North Macedonia":     { wb:"MK", dr:"north-macedonia",      cf:"north-macedonia" },
  "Norway":              { wb:"NO", dr:"norway",               cf:"norway" },
  "Oman":                { wb:"OM", dr:"oman",                 cf:"oman" },
  "Pakistan":            { wb:"PK", dr:"pakistan",             cf:"pakistan" },
  "Peru":                { wb:"PE", dr:"peru",                 cf:"peru" },
  "Philippines":         { wb:"PH", dr:"philippines",          cf:"philippines" },
  "Poland":              { wb:"PL", dr:"poland",               cf:"poland" },
  "Qatar":               { wb:"QA", dr:"qatar",                cf:"qatar" },
  "Russia":              { wb:"RU", dr:"russia",               cf:"russia" },
  "Rwanda":              { wb:"RW", dr:"rwanda",               cf:"rwanda" },
  "Saudi Arabia":        { wb:"SA", dr:"saudi-arabia",         cf:"saudi-arabia" },
  "Singapore":           { wb:"SG", dr:"singapore",            cf:"singapore" },
  "Slovakia":            { wb:"SK", dr:"slovakia",             cf:"slovakia" },
  "South Africa":        { wb:"ZA", dr:"south-africa",         cf:"south-africa" },
  "South Korea":         { wb:"KR", dr:"south-korea",          cf:"korea-south" },
  "Spain":               { wb:"ES", dr:"spain",                cf:"spain" },
  "Sri Lanka":           { wb:"LK", dr:"sri-lanka",            cf:"sri-lanka" },
  "Sweden":              { wb:"SE", dr:"sweden",               cf:"sweden" },
  "Taiwan":              { wb:"TW", dr:"taiwan",               cf:"taiwan" },
  "Tanzania":            { wb:"TZ", dr:"tanzania",             cf:"tanzania" },
  "Thailand":            { wb:"TH", dr:"thailand",             cf:"thailand" },
  "Turkey":              { wb:"TR", dr:"turkey",               cf:"turkey" },
  "Uganda":              { wb:"UG", dr:"uganda",               cf:"uganda" },
  "United Arab Emirates":{ wb:"AE", dr:"united-arab-emirates", cf:"united-arab-emirates" },
  "United Kingdom":      { wb:"GB", dr:"united-kingdom",       cf:"united-kingdom" },
  "United States":       { wb:"US", dr:"united-states",        cf:"united-states" },
  "Uzbekistan":          { wb:"UZ", dr:"uzbekistan",           cf:"uzbekistan" },
  "Vietnam":             { wb:"VN", dr:"vietnam",              cf:"vietnam" },
  "Zambia":              { wb:"ZM", dr:"zambia",               cf:"zambia" },
  "Zimbabwe":            { wb:"ZW", dr:"zimbabwe",             cf:"zimbabwe" },
};"""

# ── 3. buildMarketData() replacement ─────────────────────────────────────────

BUILD_MARKET_OLD_START = "function buildMarketData() {"
BUILD_MARKET_NEW = r"""function buildMarketData(subTab) {
  subTab = subTab || "size";
  const el = document.getElementById("marketDataContent");
  if (!currentCountry) {
    el.innerHTML = "<p style='color:#94A3B8;padding:2rem'>Select a market from the sidebar.</p>";
    return;
  }

  // ── sub-tab chrome ──────────────────────────────────────────────────────
  const tabs = `
    <div class="mkt-tabs">
      <div class="mkt-tab ${subTab==="size"?"active":""}" onclick="buildMarketData('size')">📊 Market Size</div>
      <div class="mkt-tab ${subTab==="resources"?"active":""}" onclick="buildMarketData('resources')">🔗 Resources</div>
    </div>`;

  if (subTab === "resources") {
    el.innerHTML = tabs + buildResourcesHTML(currentCountry);
    return;
  }

  // ── Market Size tab ─────────────────────────────────────────────────────
  const d = MARKET_DATA[currentCountry];
  if (!d) {
    el.innerHTML = tabs + `<div style="padding:1rem 2rem;color:#64748B">
      <p style="margin-bottom:1rem">No visa grant data available for <strong>${currentCountry}</strong>.</p>
      <a href="${POWERBI_URL}" target="_blank" rel="noopener"
        style="display:inline-block;background:#003366;color:#fff;padding:.6rem 1.2rem;border-radius:6px;text-decoration:none;font-size:.85rem;font-weight:600">
        📊 Explore commencements &amp; enrolments (interactive) →
      </a>
      <p style="margin-top:.8rem;font-size:.75rem;color:#94A3B8">Australian Dept of Education — Power BI interactive report</p>
    </div>`;
    return;
  }

  const yrs    = d.complete_years || [];
  const latest = yrs[yrs.length - 1];
  const off    = d.offshore || {};
  const ons    = d.onshore  || {};
  const latestOff    = latest && off[latest] ? off[latest].grants   : null;
  const latestOffYoy = latest && off[latest] ? off[latest].yoy_pct  : null;
  const partial      = d.partial_year || {};

  let trendRows = "";
  yrs.forEach(yr => {
    const o  = off[yr] || {};
    const on = ons[yr] || {};
    const pct = d.pct_offshore && d.pct_offshore[yr] != null ? d.pct_offshore[yr] + "%" : "—";
    const offGrants = o.grants  != null ? o.grants.toLocaleString()  : "—";
    const onGrants  = on.grants != null ? on.grants.toLocaleString() : "—";
    const yoy = o.yoy_pct != null
      ? `<span style="font-size:.72rem;padding:1px 6px;border-radius:10px;background:${o.yoy_pct>=0?"#D1FAE5":"#FEE2E2"};color:${o.yoy_pct>=0?"#065F46":"#991B1B"}">${o.yoy_pct>=0?"↑":"↓"} ${Math.abs(o.yoy_pct)}%</span>`
      : "";
    trendRows += `<tr style="border-bottom:1px solid #E8EDF2">
      <td style="padding:.4rem .7rem;font-weight:600;font-size:.82rem">${yr}</td>
      <td style="padding:.4rem .7rem;text-align:right;font-size:.85rem">${offGrants} ${yoy}</td>
      <td style="padding:.4rem .7rem;text-align:right;font-size:.85rem;color:#64748B">${onGrants}</td>
      <td style="padding:.4rem .7rem;text-align:right;font-size:.82rem;color:#94A3B8">${pct}</td>
    </tr>`;
  });

  let levelHtml = "";
  const levels = d.by_level_offshore_latest || {};
  const levelEntries = Object.entries(levels).filter(e=>e[1]).sort((a,b)=>b[1]-a[1]);
  if (levelEntries.length) {
    const maxLevel = levelEntries[0][1];
    levelHtml = `<div style="margin-top:1.2rem">
      <div style="font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#64748B;margin-bottom:.5rem">By Education Level — Offshore ${latest}</div>
      ${levelEntries.map(([lbl,val])=>`
      <div style="display:flex;align-items:center;gap:.7rem;margin-bottom:.3rem">
        <div style="width:160px;font-size:.75rem;text-align:right;color:#475569">${lbl}</div>
        <div style="flex:1;background:#EEF2F7;border-radius:3px;height:18px;position:relative">
          <div style="width:${(val/maxLevel*100).toFixed(1)}%;height:100%;background:#003366;border-radius:3px;display:flex;align-items:center;padding-left:6px">
            <span style="color:#fff;font-size:.68rem;font-weight:700">${val.toLocaleString()}</span>
          </div>
        </div>
      </div>`).join("")}
    </div>`;
  }

  const headline = latestOff != null ? latestOff.toLocaleString() : "—";
  const yoyBadge = latestOffYoy != null
    ? `<span style="font-size:.8rem;padding:2px 8px;border-radius:12px;background:${latestOffYoy>=0?"#D1FAE5":"#FEE2E2"};color:${latestOffYoy>=0?"#065F46":"#991B1B"};font-weight:700">${latestOffYoy>=0?"↑":"↓"} ${Math.abs(latestOffYoy)}%</span>`
    : "";

  el.innerHTML = tabs + `<div style="padding:.5rem 2rem 1.5rem">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:1.2rem;flex-wrap:wrap;gap:.8rem">
      <div>
        <div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;color:#64748B;margin-bottom:.3rem">MARKET SIZE · Student Visas Granted (Home Affairs)</div>
        <div style="display:flex;align-items:baseline;gap:.7rem">
          <span style="font-size:2.4rem;font-weight:700;color:#003366;line-height:1">${headline}</span>
          <span style="font-size:.82rem;color:#64748B">offshore grants · ${latest || "—"}</span>
          ${yoyBadge}
        </div>
        <div style="font-size:.75rem;color:#94A3B8;margin-top:.2rem">Data to ${d.data_as_of || "Feb 2026"}</div>
      </div>
      <a href="${POWERBI_URL}" target="_blank" rel="noopener"
        style="display:inline-flex;flex-direction:column;align-items:center;background:#003366;color:#fff;padding:.55rem 1.1rem;border-radius:6px;text-decoration:none;font-size:.8rem;font-weight:600;white-space:nowrap">
        📊 Explore commencements &amp; enrolments →
        <span style="font-size:.65rem;opacity:.7;margin-top:.1rem">Dept of Education · Interactive</span>
      </a>
    </div>
    <table style="border-collapse:collapse;width:100%;max-width:560px;margin-bottom:.5rem">
      <thead>
        <tr style="background:#003366;color:#fff">
          <th style="padding:.4rem .7rem;text-align:left;font-size:.75rem;font-weight:600">Year</th>
          <th style="padding:.4rem .7rem;text-align:right;font-size:.75rem;font-weight:600">Offshore Grants</th>
          <th style="padding:.4rem .7rem;text-align:right;font-size:.75rem;font-weight:600;opacity:.8">Onshore Grants</th>
          <th style="padding:.4rem .7rem;text-align:right;font-size:.75rem;font-weight:600;opacity:.7">% Offshore</th>
        </tr>
      </thead>
      <tbody>${trendRows}</tbody>
    </table>
    ${partial.label ? `<div style="font-size:.75rem;color:#64748B;margin-top:.4rem">
      <strong>${partial.label}:</strong> Offshore ${(partial.offshore||0).toLocaleString()} · Onshore ${(partial.onshore||0).toLocaleString()}
      <span style="color:#94A3B8;margin-left:.5rem">Partial year — not used for trend</span>
    </div>` : ""}
    ${levelHtml}
    <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #E8EDF2;font-size:.72rem;color:#94A3B8">
      Visa data: <a href="https://data.gov.au/data/dataset/student-visas" target="_blank" style="color:#2563EB">Australian Dept of Home Affairs</a>
      &nbsp;·&nbsp;
      <a href="https://www.education.gov.au/international-education-data-and-research" target="_blank" style="color:#2563EB">Australian Dept of Education</a>
    </div>
  </div>`;
}

function buildResourcesHTML(country) {
  const r = COUNTRY_RESOURCES[country];
  const name = country;

  function link(href, label, src) {
    return `<div class="res-item"><a href="${href}" target="_blank" rel="noopener">${label}</a><span class="res-src">${src}</span></div>`;
  }

  // ── Australian Student Data ──
  let aus = `<div class="res-section">
    <div class="res-heading">Australian Student Data</div>
    ${link("https://data.gov.au/data/dataset/student-visas","Student visa grants (offshore / onshore)","Australian Department of Home Affairs")}
    ${link(POWERBI_URL,"Commencements &amp; enrolments by sector — Interactive Report","Australian Department of Education · Power BI")}
  </div>`;

  if (!r) {
    return `<div style="padding:.5rem 2rem 1.5rem">${aus}
      <p style="color:#94A3B8;font-size:.82rem">Country-specific resource links not yet configured for ${name}.</p>
    </div>`;
  }

  // ── Digital & Social Media ──
  let digital = `<div class="res-section">
    <div class="res-heading">Digital &amp; Social Media</div>
    ${link(`https://datareportal.com/reports/digital-2026-${r.dr}`,`Digital 2026: ${name} — internet, social media &amp; platform usage`,"DataReportal / We Are Social / Meltwater")}
  </div>`;

  // ── Economy & Demographics ──
  let econ = `<div class="res-section">
    <div class="res-heading">Economy &amp; Demographics</div>
    ${link(`https://data.worldbank.org/country/${r.wb}`,"Economy &amp; population data — GDP per capita, growth, demographics","World Bank")}
    ${link(`https://www.cia.gov/the-world-factbook/countries/${r.cf}/`,"Country profile — demographics, education system, economy","CIA World Factbook")}
  </div>`;

  // ── Student Mobility ──
  let mobility = `<div class="res-section">
    <div class="res-heading">Student Mobility</div>
    ${link("https://uis.unesco.org/en/topic/international-student-mobility","Outbound &amp; inbound international student mobility","UNESCO Institute for Statistics")}
    ${link("https://whed.net/home.php",`Accredited universities in ${name} — filter by country`,"WHED · World Higher Education Database (IAU)")}
  </div>`;

  // ── Country-specific extras ──
  let extra = "";
  if (r.extra) {
    extra = `<div class="res-section">
      <div class="res-heading">Country-Specific</div>
      ${link(r.extra.url, r.extra.label, "Official source")}
    </div>`;
  }

  // ── Attribution ──
  let attr = `<div style="margin-top:1rem;padding-top:.8rem;border-top:1px solid #E8EDF2;font-size:.72rem;color:#94A3B8;line-height:1.6">
    Data on this page sourced from Australian Department of Home Affairs, Australian Department of Education,
    DataReportal, World Bank, CIA World Factbook, UNESCO UIS, and IAU WHED.
    All links direct to primary sources.
  </div>`;

  return `<div style="padding:.5rem 2rem 1.5rem">${aus}${digital}${econ}${mobility}${extra}${attr}</div>`;
}"""

# ── Apply patches ─────────────────────────────────────────────────────────────

def apply():
    html = HTML.read_text(encoding="utf-8")

    # Guard — don't double-patch
    if "/* Market panel sub-tabs */" in html:
        print("CSS patch already applied — skipping.")
    else:
        assert CSS_ANCHOR in html, "CSS anchor not found"
        html = html.replace(CSS_ANCHOR, CSS_NEW, 1)
        print("✅ CSS patch applied.")

    if "const COUNTRY_RESOURCES" in html:
        print("COUNTRY_RESOURCES already present — skipping.")
    else:
        anchor = 'const POWERBI_URL = '
        idx = html.find(anchor)
        assert idx != -1, "POWERBI_URL anchor not found"
        eol = html.index("\n", idx)
        html = html[:eol+1] + RESOURCES_CONST + "\n" + html[eol+1:]
        print("✅ COUNTRY_RESOURCES const injected.")

    if "function buildResourcesHTML" in html:
        print("buildMarketData already patched — skipping.")
    else:
        start = html.find("function buildMarketData() {")
        assert start != -1, "buildMarketData start not found"
        # find the closing brace — scan for the next function or comment after
        end_marker = "\n// Default to Thailand on load"
        end = html.find(end_marker, start)
        assert end != -1, "buildMarketData end not found"
        html = html[:start] + BUILD_MARKET_NEW + "\n" + html[end:]
        print("✅ buildMarketData() replaced.")

    HTML.write_text(html, encoding="utf-8")
    print(f"\nDone. {HTML.name} written ({len(html):,} bytes).")


if __name__ == "__main__":
    apply()
