#!/usr/bin/env python3
"""
normalise_parent_company.py — Set parent_company on agents rows using keyword rules.

Rules use regex and are applied globally across all countries.
Run this before build_agent_html.py.

Usage:
    python3 normalise_parent_company.py           # apply changes
    python3 normalise_parent_company.py --dry-run # show what would change
"""

import argparse
import re
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / "Desktop" / "Agent Scraper" / "data" / "agents.db"

# Each rule: (regex_pattern, canonical_parent_name)
# Patterns are case-insensitive. First match wins.
# Use word-boundary anchors (\b) where needed to avoid false positives.
RULES = [
    # IDP Education — "IDP " prefix catches all local offices (IDP India (Mumbai), IDP Australia (Sydney) etc.)
    (r'\bIDP Education\b',                          "IDP Education"),
    (r'^IDP\s+(?!Study)',                           "IDP Education"),   # IDP Thailand, IDP India (city), etc. — but NOT "IDP Study..."

    # AECC Global — "AECC" prefix catches all country offices
    (r'\bAECC\b',                                   "AECC Global"),

    # Hands On Education
    (r'Hands On Education',                         "Hands On Education"),

    # One Education Consulting
    (r'One Education Consulting',                   "One Education Consulting"),

    # SOL Edu
    (r'\bSOL Edu\b',                                "SOL Edu"),

    # Stellar Education
    (r'Stellar Education',                          "Stellar Education"),

    # Imagine Global Education & Migration
    (r'Imagine Global',                             "Imagine Global Education & Migration"),
    (r'\biGEM\b',                                   "Imagine Global Education & Migration"),

    # EduYoung
    (r'Eduyoung',                                   "EduYoung"),
    (r'Edu Young',                                  "EduYoung"),

    # Expert Education & Visa Services
    (r'Expert Education',                           "Expert Education & Visa Services"),
    (r'Expert Group Holdings',                      "Expert Education & Visa Services"),

    # Australian Visa and Student Services (AVSS)
    (r'Australian Visa and Student Services',       "Australian Visa and Student Services (AVSS)"),
    (r'\bAVSS\b',                                   "Australian Visa and Student Services (AVSS)"),

    # OEC Global Education
    (r'\bOEC Global\b',                             "OEC Global Education"),

    # iae Global — match known iae GLOBAL branding; exclude "IAE Study", "IAEC", "iae Edu Net"
    (r'\biae GLOBAL\b',                             "iae Global"),
    (r'\biae Global\b',                             "iae Global"),
    (r'\biae HOLDINGS\b',                           "iae Global"),
    (r'\bIAE GLOBAL\b',                             "iae Global"),
    (r'^IAE-\s',                                    "iae Global"),   # "IAE- Hong Kong"
    (r'^iae\s+(?!Edu)',                             "iae Global"),   # "iae Indonesia", not "iae Edu Net"

    # Yes Education Group
    (r'Yes Education Group',                        "Yes Education Group"),

    # Beyond Study Center
    (r'Beyond Study Center',                        "Beyond Study Center"),

    # Education For Life
    (r'Education For Life',                         "Education For Life"),

    # Asiania International Consulting
    (r'Asiania International',                      "Asiania International Consulting"),

    # LCI Group / Liu Cheng International
    (r'Liu Cheng International',                    "LCI Group"),
    (r'\bLCI Group\b',                              "LCI Group"),

    # WIN Education — branches stored as "WIN Education - [location]"
    (r'^WIN Education',                             "WIN Education"),

    # Adventus Education — "Adventus Education Pte Ltd" and bare name
    (r'Adventus Education',                         "Adventus Education"),

    # Chulalongkorn University — both faculties (Political Science / Psychology)
    (r'Chulalongkorn University',                   "Chulalongkorn University"),
]

# Compile all patterns once
_COMPILED = [(re.compile(pat, re.IGNORECASE), canonical) for pat, canonical in RULES]


def find_canonical(company_name):
    """Return the canonical parent_company for a given company_name, or None."""
    for pattern, canonical in _COMPILED:
        if pattern.search(company_name):
            return canonical
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, company_name, parent_company FROM agents").fetchall()

    updates = []

    for row_id, company_name, current_parent in rows:
        if not company_name:
            continue
        canonical = find_canonical(company_name)
        if canonical and canonical != current_parent:
            updates.append((canonical, row_id, company_name, current_parent))

    print(f"Rows to update: {len(updates)}")
    for canonical, row_id, company_name, old in updates[:80]:
        marker = "  " if not args.dry_run else "[dry] "
        print(f"  {marker}{company_name!r:65s}  →  {canonical!r}")

    if len(updates) > 80:
        print(f"  ... and {len(updates) - 80} more")

    if not args.dry_run and updates:
        conn.executemany(
            "UPDATE agents SET parent_company = ? WHERE id = ?",
            [(canonical, row_id) for canonical, row_id, _, _ in updates]
        )
        conn.commit()
        print(f"\nDone. {len(updates)} rows updated.")
    elif args.dry_run:
        print("\n[dry-run] No changes written.")
    else:
        print("Nothing to update.")

    conn.close()


if __name__ == "__main__":
    main()
