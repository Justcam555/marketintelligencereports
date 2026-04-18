# How to Save Filtered Visa Export Files

Source file: `bp0015l-student-visas-granted-report-locked-at-2026-02-28-v100.xlsx`
Sheet: `Granted (Month)`

You need **two saves per country** — one filtered to Offshore, one to Onshore.

---

## Steps (repeat for each country)

1. Open the source file in Excel
2. Go to sheet **Granted (Month)**
3. Set filter: **Citizenship Country** = `Thailand`
4. Set filter: **Client Location** = `Offshore`
5. **File → Save a Copy** → `data/raw/visa_thailand_offshore.xlsx`
6. Change filter: **Client Location** = `Onshore`
7. **File → Save a Copy** → `data/raw/visa_thailand_onshore.xlsx`
8. Repeat for Nepal → `visa_nepal_offshore.xlsx` / `visa_nepal_onshore.xlsx`

---

## File naming

| Country | Offshore file | Onshore file |
|---|---|---|
| Thailand | `visa_thailand_offshore.xlsx` | `visa_thailand_onshore.xlsx` |
| Nepal | `visa_nepal_offshore.xlsx` | `visa_nepal_onshore.xlsx` |
| Vietnam | `visa_vietnam_offshore.xlsx` | `visa_vietnam_onshore.xlsx` |
| China | `visa_china_offshore.xlsx` | `visa_china_onshore.xlsx` |

Slug rule: lowercase, spaces → underscores, special chars removed.

---

## Country name mismatches

| In our DB | In Home Affairs filter |
|---|---|
| Vietnam | Viet Nam |
| China | China (People's Republic of) |
| Hong Kong | Hong Kong (SAR of China) |
| South Korea | Korea, Republic of |

---

## Run the pipeline

```bash
cd ~/Desktop/marketintelligencereports

# Parse filtered Excel files → JSON + CSV
python3 process_market_data.py

# Build HTML blocks for embedding
python3 build_market_blocks.py
```

Preview opens in browser from: `data/processed/market_blocks_2026-02.html`
