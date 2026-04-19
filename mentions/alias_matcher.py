"""
alias_matcher.py — loads the university alias table and matches text against aliases.

Usage:
    from alias_matcher import AliasMatcher
    matcher = AliasMatcher()
    results = matcher.match("Great video about studying at Macquarie Uni in Sydney!")
    # [{'canonical': 'Macquarie University', 'alias': 'Macquarie Uni',
    #   'confidence': 'high', 'type': 'informal'}]
"""

import re
import os
from pathlib import Path
import openpyxl

ALIAS_TABLE = Path(__file__).parent / "university_alias_table_v2.xlsx"

# Education-context keywords — at least one must appear for low/medium confidence matches
EDUCATION_KEYWORDS = {
    "study", "studying", "student", "students", "university", "uni", "college",
    "degree", "bachelor", "master", "mba", "phd", "postgrad", "undergrad",
    "scholarship", "admission", "enroll", "enrol", "apply", "application",
    "campus", "faculty", "course", "international", "abroad", "education",
    "ielts", "toefl", "visa", "graduate", "graduation", "academic",
    # Thai equivalents
    "มหาวิทยาลัย", "นักศึกษา", "ทุน", "วีซ่า", "เรียน", "ศึกษา",
    "หลักสูตร", "ปริญญา", "สมัคร", "แอดมิชชัน",
}

# Aliases that need extra care — only match if education keywords present
COLLISION_ALIASES = {
    "melbourne",      # city name
    "sydney",         # city name
    "ซิดนีย์",        # city (TH)
    "เมลเบิร์น",      # city (TH)
    "mq",             # ambiguous acronym
    "tech sydney",    # informal / low
}


def _load_aliases(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    aliases = []
    header = None
    for row in ws.iter_rows(values_only=True):
        if header is None:
            header = [str(c).lower().strip() for c in row]
            continue
        record = dict(zip(header, row))
        if record.get("canonical_name") and record.get("alias"):
            aliases.append({
                "canonical":   str(record["canonical_name"]).strip(),
                "alias":       str(record["alias"]).strip(),
                "language":    str(record.get("language") or "EN").strip().upper(),
                "type":        str(record.get("type") or "").strip().lower(),
                "confidence":  str(record.get("confidence") or "medium").strip().lower(),
                "notes":       str(record.get("notes") or "").strip(),
            })
    return aliases


class AliasMatcher:
    def __init__(self, alias_path: Path = ALIAS_TABLE):
        self.aliases = _load_aliases(alias_path)
        # Pre-compile patterns: word-boundary aware, case-insensitive
        self._patterns = []
        for a in self.aliases:
            raw = a["alias"]
            # Hashtags: match literally (# is not a word char)
            if raw.startswith("#"):
                pat = re.compile(re.escape(raw), re.IGNORECASE)
            elif re.search(r"\W", raw):
                # Multi-word or contains non-word chars — exact phrase
                pat = re.compile(r"(?<!\w)" + re.escape(raw) + r"(?!\w)", re.IGNORECASE)
            else:
                pat = re.compile(r"\b" + re.escape(raw) + r"\b", re.IGNORECASE)
            self._patterns.append((pat, a))

    def _has_edu_context(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in EDUCATION_KEYWORDS)

    def match(self, text: str) -> list[dict]:
        """
        Return list of matched universities with confidence info.
        Deduplicates to one result per canonical name (highest confidence wins).
        """
        if not text:
            return []

        has_edu = self._has_edu_context(text)
        hits: dict[str, dict] = {}  # canonical → best match

        for pat, alias in self._patterns:
            if not pat.search(text):
                continue

            confidence = alias["confidence"]
            alias_lower = alias["alias"].lower()

            # Low/medium confidence + collision risk → require education context
            if confidence in ("low", "medium") or alias_lower in COLLISION_ALIASES:
                if not has_edu:
                    continue

            result = {
                "canonical":  alias["canonical"],
                "alias":      alias["alias"],
                "language":   alias["language"],
                "type":       alias["type"],
                "confidence": confidence,
                "notes":      alias["notes"],
            }

            # Keep highest-confidence match per canonical
            existing = hits.get(alias["canonical"])
            if existing is None:
                hits[alias["canonical"]] = result
            else:
                order = {"high": 3, "medium": 2, "low": 1}
                if order.get(confidence, 0) > order.get(existing["confidence"], 0):
                    hits[alias["canonical"]] = result

        return list(hits.values())

    def match_any(self, text: str) -> bool:
        return bool(self.match(text))

    def hashtags(self, canonical: str = None) -> list[str]:
        """Return all hashtag aliases, optionally filtered by canonical name."""
        return [
            a["alias"] for a in self.aliases
            if a["type"] == "hashtag" and (canonical is None or a["canonical"] == canonical)
        ]

    def search_terms(self, canonical: str, language: str = "EN") -> list[str]:
        """Return non-hashtag aliases for a canonical name in the given language."""
        return [
            a["alias"] for a in self.aliases
            if a["canonical"] == canonical
            and a["language"].upper() == language.upper()
            and a["type"] != "hashtag"
        ]

    @property
    def canonical_names(self) -> list[str]:
        return sorted({a["canonical"] for a in self.aliases})


if __name__ == "__main__":
    m = AliasMatcher()
    print(f"Loaded {len(m.aliases)} aliases for {len(m.canonical_names)} universities")
    tests = [
        "Check out this Monash University student vlog!",
        "I'm studying at Macquarie Uni next year #macquarieuniversity",
        "Just went to Melbourne for the weekend",  # should not match without edu context
        "Melbourne Uni is great for international students",
        "เรียนที่ RMIT Bangkok ดีมาก",
        "#rmitbangkok #study",
    ]
    for t in tests:
        hits = m.match(t)
        print(f"\n'{t[:60]}'")
        for h in hits:
            print(f"  → {h['canonical']} (alias={h['alias']}, conf={h['confidence']})")
