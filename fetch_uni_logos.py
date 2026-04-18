#!/usr/bin/env python3
"""
fetch_uni_logos.py — Fetch official logos for Australian universities.

Strategy per university:
  1. GET the homepage, search <img> tags for logo (alt/src/class heuristics)
  2. Also check for SVG in <header> / <nav> elements
  3. Download SVG preferred, fall back to PNG
  4. Save as Uni logos/{slug}.svg or {slug}.png

Run from marketintelligencereports/ folder.
"""

import io
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

LOGO_DIR = Path(__file__).parent / "Uni logos"
LOGO_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# (slug, homepage_url) — ordered by priority
UNIVERSITIES = [
    ("adelaide-university",              "https://adelaideuni.edu.au"),
    ("australian-national-university",   "https://www.anu.edu.au"),
    ("australian-catholic-university",   "https://www.acu.edu.au"),
    ("australian-university-of-theology","https://aut.edu.au"),
    ("avondale-university",              "https://www.avondale.edu.au"),
    ("bond-university",                  "https://bond.edu.au"),
    ("charles-darwin-university",        "https://www.cdu.edu.au"),
    ("charles-sturt-university",         "https://www.csu.edu.au"),
    ("cquniversity",                     "https://www.cqu.edu.au"),
    ("curtin-university",                "https://www.curtin.edu.au"),
    ("deakin-university",                "https://www.deakin.edu.au"),
    ("edith-cowan-university",           "https://www.ecu.edu.au"),
    ("federation-university-australia",  "https://federation.edu.au"),
    ("flinders-university",              "https://www.flinders.edu.au"),
    ("griffith-university",              "https://www.griffith.edu.au"),
    ("james-cook-university",            "https://www.jcu.edu.au"),
    ("la-trobe-university",              "https://www.latrobe.edu.au"),
    ("macquarie-university",             "https://www.mq.edu.au"),
    ("monash-university",                "https://www.monash.edu"),
    ("murdoch-university",               "https://www.murdoch.edu.au"),
    ("queensland-university-of-technology", "https://www.qut.edu.au"),
    ("rmit-university",                  "https://www.rmit.edu.au"),
    ("southern-cross-university",        "https://www.scu.edu.au"),
    ("swinburne-university-of-technology","https://www.swinburne.edu.au"),
    ("torrens-university-australia",     "https://www.torrens.edu.au"),
    ("unsw-sydney",                      "https://www.unsw.edu.au"),
    ("university-of-canberra",           "https://www.canberra.edu.au"),
    ("university-of-divinity",           "https://divinity.edu.au"),
    ("university-of-melbourne",          "https://www.unimelb.edu.au"),
    ("university-of-new-england",        "https://www.une.edu.au"),
    ("university-of-newcastle",          "https://www.newcastle.edu.au"),
    ("university-of-notre-dame-australia","https://www.notredame.edu.au"),
    ("university-of-queensland",         "https://www.uq.edu.au"),
    ("university-of-southern-queensland","https://www.unisq.edu.au"),
    ("university-of-sydney",             "https://www.sydney.edu.au"),
    ("university-of-tasmania",           "https://www.utas.edu.au"),
    ("university-of-technology-sydney",  "https://www.uts.edu.au"),
    ("university-of-western-australia",  "https://www.uwa.edu.au"),
    ("university-of-wollongong",         "https://www.uow.edu.au"),
    ("university-of-the-sunshine-coast", "https://www.usc.edu.au"),
    ("victoria-university",              "https://www.vu.edu.au"),
    ("western-sydney-university",        "https://www.westernsydney.edu.au"),
]

# Logo patterns to score candidate <img> elements (higher = better)
LOGO_KEYWORDS = [
    "logo", "brand", "crest", "seal", "coat-of-arms", "emblem",
    "header", "masthead", "identity",
]

SKIP_KEYWORDS = [
    "banner", "hero", "slide", "carousel", "bg", "background",
    "icon", "avatar", "social", "facebook", "twitter", "instagram",
    "youtube", "linkedin", "staff", "student", "news", "event",
    "course", "study", "search", "arrow", "chevron", "hamburger",
    "menu", "close", "play", "video", "map", "flag",
    "partner", "sponsor", "advertisement",
]

MIN_WIDTH_HINT = 60   # ignore tiny icons


def score_candidate(tag, base_url):
    """Score an img/svg candidate — higher is better logo candidate."""
    score = 0
    src = tag.get("src", "") or tag.get("href", "") or tag.get("data-src", "") or ""
    alt = (tag.get("alt", "") or "").lower()
    cls = " ".join(tag.get("class", [])).lower()
    pid = (tag.get("id", "") or "").lower()
    combined = f"{src} {alt} {cls} {pid}".lower()

    for kw in LOGO_KEYWORDS:
        if kw in combined:
            score += 10
    for kw in SKIP_KEYWORDS:
        if kw in combined:
            score -= 15

    # Prefer SVG
    if src.lower().endswith(".svg") or "svg" in src.lower():
        score += 20

    # Penalise data URIs (usually tiny icons)
    if src.startswith("data:"):
        score -= 50

    # Width/height hints
    width = tag.get("width", "")
    if width and width.isdigit():
        w = int(width)
        if w < MIN_WIDTH_HINT:
            score -= 20
        elif w > 200:
            score += 5

    # <header> or <nav> parent boosts score
    parent = tag.parent
    for _ in range(5):
        if parent is None:
            break
        pname = getattr(parent, "name", "")
        pcls = " ".join(parent.get("class", [])).lower() if hasattr(parent, "get") else ""
        if pname in ("header", "nav") or any(k in pcls for k in ("header", "nav", "masthead", "brand", "logo")):
            score += 15
            break
        parent = parent.parent

    return score


def absolute_url(src, base):
    if not src or src.startswith("data:"):
        return None
    return urllib.parse.urljoin(base, src)


def fetch_page(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.text, r.url
    except Exception as e:
        return None, str(e)


def download_asset(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "")
    except Exception as e:
        return None, str(e)


def is_svg(content):
    try:
        text = content[:500].decode("utf-8", errors="ignore").strip()
        return text.startswith("<svg") or "xmlns" in text[:200]
    except Exception:
        return False


def is_valid_image(content, min_px=40):
    """True if content is a decodable image of at least min_px in each dimension."""
    try:
        img = Image.open(io.BytesIO(content))
        w, h = img.size
        return w >= min_px and h >= min_px
    except Exception:
        return False


def save_logo(slug, content, content_type, url):
    """Save to Uni logos/{slug}.svg or .png. Returns saved path or None."""
    if is_svg(content):
        ext = ".svg"
    elif "svg" in content_type:
        ext = ".svg"
    elif "png" in content_type or url.lower().endswith(".png"):
        ext = ".png"
    elif "webp" in content_type or url.lower().endswith(".webp"):
        ext = ".png"  # convert below
        try:
            img = Image.open(io.BytesIO(content)).convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            content = buf.getvalue()
        except Exception:
            return None
    elif any(x in content_type for x in ("jpeg", "jpg")) or url.lower().endswith((".jpg", ".jpeg")):
        ext = ".png"
        try:
            img = Image.open(io.BytesIO(content)).convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            content = buf.getvalue()
        except Exception:
            return None
    else:
        # Try to detect from content
        if content[:4] == b"\x89PNG":
            ext = ".png"
        elif content[:4] == b"GIF8":
            ext = ".png"
            try:
                img = Image.open(io.BytesIO(content)).convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                content = buf.getvalue()
            except Exception:
                return None
        else:
            return None  # Unknown format

    path = LOGO_DIR / f"{slug}{ext}"
    path.write_bytes(content)
    return path


def find_logo_for(slug, homepage):
    """Try to find and download the university logo. Returns (path, url) or (None, reason)."""

    html, final_url = fetch_page(homepage)
    if not html:
        return None, f"page fetch failed: {final_url}"

    soup = BeautifulSoup(html, "lxml")

    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = []

    # 1. Score all <img> tags
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src or src.startswith("data:"):
            continue
        url = absolute_url(src, final_url)
        if not url:
            continue
        s = score_candidate(img, final_url)
        candidates.append((s, url, img.get("alt", "")))

    # 2. Score inline <svg> — skip (too complex to save directly)

    # 3. Also try <link rel="icon"> as last resort (not great but fallback)
    for link in soup.find_all("link", rel=lambda r: r and "icon" in r):
        href = link.get("href", "")
        url = absolute_url(href, final_url)
        if url:
            candidates.append((-5, url, "favicon"))

    if not candidates:
        return None, "no img candidates found"

    # Sort by score desc
    candidates.sort(key=lambda x: -x[0])

    # Try top candidates until one downloads cleanly
    for score, url, alt in candidates[:8]:
        if score < -10:
            break
        content, ctype = download_asset(url)
        if not content:
            continue
        if is_svg(content):
            path = save_logo(slug, content, "image/svg+xml", url)
            if path:
                return path, url
        else:
            if not is_valid_image(content):
                continue
            path = save_logo(slug, content, ctype, url)
            if path:
                return path, url

    return None, f"all candidates failed (top score={candidates[0][0] if candidates else 'n/a'})"


def main():
    print(f"Saving logos to: {LOGO_DIR}\n")
    results = []

    for slug, homepage in UNIVERSITIES:
        # Skip if already fetched
        existing = list(LOGO_DIR.glob(f"{slug}.*"))
        if existing:
            print(f"  SKIP  {slug:50s} (already have {existing[0].name})")
            results.append((slug, "skipped", str(existing[0].name)))
            continue

        print(f"  ...   {slug:50s} {homepage}", end="", flush=True)
        path, detail = find_logo_for(slug, homepage)

        if path:
            size = path.stat().st_size
            print(f" → ✅ {path.name} ({size:,} bytes)")
            results.append((slug, "ok", path.name))
        else:
            print(f" → ❌ {detail}")
            results.append((slug, "failed", detail))

        time.sleep(1.2)  # polite crawl delay

    print("\n── Summary ──────────────────────────────────────")
    ok      = [r for r in results if r[1] == "ok"]
    skipped = [r for r in results if r[1] == "skipped"]
    failed  = [r for r in results if r[1] == "failed"]
    print(f"  OK:      {len(ok)}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Failed:  {len(failed)}")
    if failed:
        print("\nFailed universities (need manual download):")
        for slug, _, reason in failed:
            print(f"  {slug:50s} — {reason}")


if __name__ == "__main__":
    main()
