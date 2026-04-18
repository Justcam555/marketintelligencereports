#!/usr/bin/env python3
"""
fetch_uni_logos_retry.py — Second-pass fetcher for universities that blocked the first attempt.

Strategies tried per university:
  1. Known direct CDN / asset URLs
  2. Wikipedia SVG (reliable, permissive)
  3. Minimal headers (no User-Agent spoofing)
  4. Try www2 / study. subdomain variants
"""

import io
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

LOGO_DIR = Path(__file__).parent / "Uni logos"

# Minimal headers — some sites block elaborate UA strings
HEADERS_MINIMAL = {}

HEADERS_CHROME = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Per-university fallback strategies: list of direct URLs to try
FALLBACKS = {
    "avondale-university": [
        "https://www.avondale.edu.au/wp-content/uploads/2023/02/avondale-logo.svg",
        "https://www.avondale.edu.au/wp-content/uploads/2022/01/avondale-logo.png",
        "https://www.avondale.edu.au/wp-content/themes/avondale/images/logo.svg",
        "https://www.avondale.edu.au/wp-content/uploads/2024/01/avondale-university-logo.svg",
    ],
    "deakin-university": [
        "https://www.deakin.edu.au/__data/assets/file/0008/2376577/deakin-logo.svg",
        "https://www.deakin.edu.au/images/deakin-logo.svg",
        "https://cdn.deakin.edu.au/images/logo.svg",
        "https://www.deakin.edu.au/__data/assets/image/0010/1972406/deakin-logo.svg",
    ],
    "edith-cowan-university": [
        "https://www.ecu.edu.au/ECUWS17/img/ecu-logo.svg",
        "https://www.ecu.edu.au/images/ecu-logo.svg",
        "https://www.ecu.edu.au/ECUWS17/img/logos/ecu-logo-primary.svg",
        "https://intranet.ecu.edu.au/__data/assets/image/0005/770005/ECU_Logo_Horizontal_White.svg",
    ],
    "griffith-university": [
        "https://www.griffith.edu.au/__data/assets/image/0021/172766/Griffith_University_vertical_white.svg",
        "https://www.griffith.edu.au/__data/assets/image/0022/172767/GriffithUniversity_Logo_CMYK.svg",
        "https://www.griffith.edu.au/images/griffith-logo.svg",
        "https://cdn.griffith.edu.au/images/logo.svg",
    ],
    "james-cook-university": [
        "https://www.jcu.edu.au/images/jcu-logo.svg",
        "https://www.jcu.edu.au/web-resources/images/JCU_logo.svg",
        "https://assets.jcu.edu.au/images/jcu-logo.svg",
        "https://www.jcu.edu.au/web-resources/images/jcu-logo.png",
    ],
    "macquarie-university": [
        "https://www.mq.edu.au/__data/assets/image/0013/1169888/Macquarie_University_logo.svg",
        "https://www.mq.edu.au/images/logo.svg",
        "https://cdn.mq.edu.au/images/macquarie-logo.svg",
        "https://www.mq.edu.au/__data/assets/image/0018/1038003/MQ_INT_HorizontalReverse_RGB.svg",
    ],
    "monash-university": [
        "https://www.monash.edu/__data/assets/image/0025/2371/monash-logo.svg",
        "https://www.monash.edu/__data/assets/image/0006/2009/Monash_University_logo.svg",
        "https://cdn.monash.edu/monash-logo.svg",
        "https://www.monash.edu/images/monash-logo.svg",
    ],
    "queensland-university-of-technology": [
        "https://www.qut.edu.au/images/qut-logo.svg",
        "https://www.qut.edu.au/images/logo/qut-logo-og.png",
        "https://cdn.qut.edu.au/images/qut-logo.svg",
        "https://www.qut.edu.au/images/logo.png",
    ],
    "university-of-melbourne": [
        "https://www.unimelb.edu.au/images/uom-logo.svg",
        "https://d2glwx35mhbfwf.cloudfront.net/v1.0.8/logo.svg",
        "https://www.unimelb.edu.au/__data/assets/image/0015/2673905/university-of-melbourne-logo.svg",
        "https://static.unimelb.edu.au/images/logos/uom-logo.svg",
    ],
    "university-of-new-england": [
        "https://www.une.edu.au/images/une-logo.svg",
        "https://www.une.edu.au/__data/assets/image/0017/465765/UNE-logo.svg",
        "https://www.une.edu.au/images/logo.svg",
        "https://www.une.edu.au/assets/images/une-logo.png",
    ],
    "university-of-newcastle": [
        "https://www.newcastle.edu.au/images/newcastle-logo.svg",
        "https://www.newcastle.edu.au/__data/assets/image/0017/1118734/uon-logo.svg",
        "https://www.newcastle.edu.au/images/logo.svg",
        "https://cdn.newcastle.edu.au/images/uon-logo.svg",
    ],
    "university-of-notre-dame-australia": [
        "https://www.notredame.edu.au/images/unda-logo.svg",
        "https://www.notredame.edu.au/images/logo.svg",
        "https://www.notredame.edu.au/__data/assets/image/0003/1052065/UNDA_Logo_Colour.svg",
        "https://www.notredame.edu.au/images/unda-logo.png",
    ],
    "university-of-tasmania": [
        "https://www.utas.edu.au/__data/assets/image/0003/1519022/UTAS_Horiz_rev.svg",
        "https://www.utas.edu.au/images/utas-logo.svg",
        "https://cdn.utas.edu.au/images/logo.svg",
        "https://www.utas.edu.au/__data/assets/image/0004/1519023/UTAS_Stacked_rev.svg",
    ],
}

# Wikipedia SVG fallbacks — reliable source for university logos
WIKIPEDIA_FALLBACKS = {
    "avondale-university":             "https://upload.wikimedia.org/wikipedia/en/5/5a/Avondale_University_College_logo.svg",
    "deakin-university":               "https://upload.wikimedia.org/wikipedia/en/c/c0/Deakin_University_logo.svg",
    "edith-cowan-university":          "https://upload.wikimedia.org/wikipedia/en/b/b4/Edith_Cowan_University_logo.svg",
    "griffith-university":             "https://upload.wikimedia.org/wikipedia/en/d/db/Griffith_University_Logo.svg",
    "james-cook-university":           "https://upload.wikimedia.org/wikipedia/en/3/31/James_Cook_University_logo.svg",
    "macquarie-university":            "https://upload.wikimedia.org/wikipedia/en/e/e8/Macquarie_University_logo.svg",
    "monash-university":               "https://upload.wikimedia.org/wikipedia/en/b/b7/Monash_University_logo.svg",
    "queensland-university-of-technology": "https://upload.wikimedia.org/wikipedia/en/e/e4/QUT_logo.svg",
    "university-of-melbourne":         "https://upload.wikimedia.org/wikipedia/en/f/fd/University_of_Melbourne_logo.svg",
    "university-of-new-england":       "https://upload.wikimedia.org/wikipedia/en/6/63/University_of_New_England_%28Australia%29_logo.svg",
    "university-of-newcastle":         "https://upload.wikimedia.org/wikipedia/en/4/41/University_of_Newcastle_%28Australia%29_logo.svg",
    "university-of-notre-dame-australia": "https://upload.wikimedia.org/wikipedia/en/2/21/University_of_Notre_Dame_Australia_logo.svg",
    "university-of-tasmania":          "https://upload.wikimedia.org/wikipedia/en/2/27/University_of_Tasmania_logo.svg",
}


def download(url, headers=HEADERS_CHROME, timeout=15):
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "")
    except Exception as e:
        return None, str(e)


def is_svg(content):
    if not content:
        return False
    try:
        text = content[:500].decode("utf-8", errors="ignore").strip()
        return "<svg" in text or "xmlns" in text[:300]
    except Exception:
        return False


def is_valid_image(content, min_px=40):
    if not content:
        return False
    try:
        img = Image.open(io.BytesIO(content))
        return img.size[0] >= min_px and img.size[1] >= min_px
    except Exception:
        return False


def save(slug, content, ctype, url):
    if is_svg(content):
        ext = ".svg"
    elif "png" in ctype or url.endswith(".png"):
        ext = ".png"
    elif any(x in ctype for x in ("webp", "jpeg", "jpg", "gif")):
        try:
            img = Image.open(io.BytesIO(content)).convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            content = buf.getvalue()
            ext = ".png"
        except Exception:
            return None
    elif content and content[:4] == b"\x89PNG":
        ext = ".png"
    else:
        return None
    path = LOGO_DIR / f"{slug}{ext}"
    path.write_bytes(content)
    return path


def main():
    failed = [s for s in FALLBACKS if not list(LOGO_DIR.glob(f"{s}.*"))]
    if not failed:
        print("All target logos already present.")
        return

    print(f"Retrying {len(failed)} universities...\n")
    still_failed = []

    for slug in failed:
        existing = list(LOGO_DIR.glob(f"{slug}.*"))
        if existing:
            print(f"  SKIP {slug}")
            continue

        print(f"  {slug}:")

        # 1. Try direct CDN URLs
        saved = None
        for url in FALLBACKS.get(slug, []):
            content, ctype = download(url)
            if content and (is_svg(content) or is_valid_image(content)):
                saved = save(slug, content, ctype, url)
                if saved:
                    print(f"    ✅ direct CDN  → {saved.name} ({saved.stat().st_size:,} bytes)  [{url[:60]}]")
                    break
            time.sleep(0.3)

        if saved:
            time.sleep(0.8)
            continue

        # 2. Try Wikipedia SVG
        wiki_url = WIKIPEDIA_FALLBACKS.get(slug)
        if wiki_url:
            content, ctype = download(wiki_url, headers={
                "User-Agent": "Mozilla/5.0 compatible; educational research bot"
            })
            if content and (is_svg(content) or is_valid_image(content)):
                saved = save(slug, content, ctype, wiki_url)
                if saved:
                    print(f"    ✅ Wikipedia    → {saved.name} ({saved.stat().st_size:,} bytes)")
                    time.sleep(0.8)
                    continue

        print(f"    ❌ all strategies failed — needs manual download")
        still_failed.append(slug)
        time.sleep(0.5)

    print(f"\n── Done ──")
    if still_failed:
        print(f"Still need manual download ({len(still_failed)}):")
        for s in still_failed:
            print(f"  {s}")
    else:
        print("All logos retrieved.")


if __name__ == "__main__":
    main()
