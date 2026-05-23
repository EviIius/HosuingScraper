"""
Scrapeability diagnostic for Charlotte, NC real estate listing sites.
Fetches each URL and reports: status code, bot protection signals,
embedded JSON keys, and a sample of the first listing card HTML.
"""

import re
import sys
import textwrap
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SITES = [
    {
        "name": "point2homes.com",
        "url": "https://www.point2homes.com/US/Real-Estate-Listings/NC/Charlotte.html",
    },
    {
        "name": "homefinder.com",
        "url": "https://homefinder.com/NC/Charlotte/for-sale",
    },
    {
        "name": "movoto.com",
        "url": "https://www.movoto.com/nc/charlotte/",
    },
    {
        "name": "estately.com",
        "url": "https://www.estately.com/NC/Charlotte",
    },
    {
        "name": "homes.com",
        "url": "https://www.homes.com/nc/charlotte/",
    },
]

# Known bot-protection fingerprints to search for in page source
BOT_PROTECTION_SIGNALS = {
    "Cloudflare": [
        "cloudflare",
        "cf-ray",
        "__cf_bm",
        "cdn-cgi",
        "challenge-platform",
        "just a moment",
    ],
    "PerimeterX": [
        "perimeterx",
        "_pxAppId",
        "px-captcha",
        "PerimeterX",
        "pxScript",
    ],
    "DataDome": [
        "datadome",
        "dd_cookie",
        "DataDome",
    ],
    "Incapsula/Imperva": [
        "incapsula",
        "visid_incap",
        "_incap_ses",
        "imperva",
    ],
    "reCAPTCHA": [
        "recaptcha",
        "grecaptcha",
    ],
    "hCaptcha": [
        "hcaptcha",
    ],
    "Akamai": [
        "_abck",
        "bm_sz",
        "akamai",
    ],
}

# Embedded JSON state keys commonly used by Next.js / React SPAs
EMBEDDED_JSON_KEYS = [
    "__NEXT_DATA__",
    "window.__INITIAL_STATE__",
    "window.__DATA__",
    "window.__PRELOADED_STATE__",
    "window.__APP_STATE__",
    "window.__STATE__",
    "window.initialState",
    "window.pageData",
    "window.__REDUX_STATE__",
    "__nuxt__",
    "window.__APOLLO_STATE__",
]


def truncate(text, max_chars=600):
    text = " ".join(text.split())  # collapse whitespace
    if len(text) > max_chars:
        return text[:max_chars] + " ... [truncated]"
    return text


def detect_bot_protection(text_lower, headers_dict):
    detected = []
    combined = text_lower + " " + " ".join(
        str(v).lower() for v in headers_dict.values()
    )
    for product, signals in BOT_PROTECTION_SIGNALS.items():
        if any(sig.lower() in combined for sig in signals):
            detected.append(product)
    return detected


def find_embedded_json(html_text):
    found = []
    for key in EMBEDDED_JSON_KEYS:
        # Simple presence check in raw HTML
        if key in html_text:
            found.append(key)
    return found


def find_listing_card(soup):
    """
    Heuristically locate the first element that looks like a listing card.
    Returns (css_selector_description, outer_html_snippet) or None.
    """
    # Patterns: common class name fragments used by real-estate sites
    card_hints = [
        # attribute contains
        ("class", re.compile(r"listing|property|card|result|home-item|prop-card", re.I)),
    ]

    candidates = []
    for attr, pattern in card_hints:
        tags = soup.find_all(True, attrs={attr: pattern})
        # Prefer deeper / leaf-like nodes
        if tags:
            candidates.extend(tags[:5])

    # Pick the one with the most address/price-like text
    def score(tag):
        text = tag.get_text(" ", strip=True)
        score_val = 0
        if re.search(r"\$[\d,]+", text):
            score_val += 3
        if re.search(r"\d+\s*(bed|bath|br|ba)", text, re.I):
            score_val += 2
        if re.search(r"\d+\s+\w+\s+(st|ave|rd|blvd|ln|dr|ct|pl|way)", text, re.I):
            score_val += 2
        score_val += min(len(text), 200) / 200  # prefer fuller cards
        return score_val

    if candidates:
        best = max(candidates, key=score)
        tag_id = f"<{best.name} class='{' '.join(best.get('class', [])[:4])}'>"
        snippet = truncate(str(best), 800)
        return tag_id, snippet

    return None


def analyze_site(site):
    name = site["name"]
    url = site["url"]
    print(f"\n{'='*70}")
    print(f"SITE: {name}")
    print(f"URL : {url}")
    print("="*70)

    result = {
        "name": name,
        "url": url,
        "status_code": None,
        "error": None,
        "bot_protection": [],
        "embedded_json": [],
        "listing_card": None,
        "redirect_chain": [],
        "content_length": 0,
        "title": "",
        "body_preview": "",
    }

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True,
        )
        result["status_code"] = resp.status_code
        result["redirect_chain"] = [r.url for r in resp.history]
        result["content_length"] = len(resp.content)

        html = resp.text
        html_lower = html.lower()

        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else "(no title)"

        # First 300 chars of visible body text
        body = soup.find("body")
        if body:
            visible = body.get_text(" ", strip=True)
            result["body_preview"] = truncate(visible, 300)

        # Bot protection
        result["bot_protection"] = detect_bot_protection(html_lower, dict(resp.headers))

        # Embedded JSON
        result["embedded_json"] = find_embedded_json(html)

        # Listing card
        card = find_listing_card(soup)
        result["listing_card"] = card

    except requests.exceptions.Timeout:
        result["error"] = "TIMEOUT after 30s"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"CONNECTION ERROR: {e}"
    except Exception as e:
        result["error"] = f"UNEXPECTED ERROR: {e}"

    return result


def print_report(result):
    print(f"\n--- {result['name']} ---")
    if result["error"]:
        print(f"  ERROR: {result['error']}")
        return

    print(f"  HTTP Status      : {result['status_code']}")
    print(f"  Page title       : {result['title']}")
    print(f"  Content length   : {result['content_length']:,} bytes")
    if result["redirect_chain"]:
        print(f"  Redirects        : {' -> '.join(result['redirect_chain'])}")

    bp = result["bot_protection"]
    print(f"  Bot protection   : {', '.join(bp) if bp else 'None detected'}")

    ej = result["embedded_json"]
    print(f"  Embedded JSON    : {', '.join(ej) if ej else 'None found'}")

    card = result["listing_card"]
    if card:
        tag_desc, snippet = card
        print(f"  First card tag   : {tag_desc}")
        print(f"  Card HTML sample :")
        for line in textwrap.wrap(snippet, 100):
            print(f"    {line}")
    else:
        print("  First card tag   : NOT FOUND")

    print(f"  Body preview     : {result['body_preview'][:300]}")


def verdict(result):
    """Return a short verdict string."""
    if result["error"]:
        return "ERROR - could not fetch"

    code = result["status_code"]
    bp = result["bot_protection"]
    ej = result["embedded_json"]
    card = result["listing_card"]

    # Hard blocks
    if code in (403, 429, 503):
        return f"BLOCKED ({code}) - not viable without Playwright + stealth"

    # Soft blocks / CAPTCHA pages (200 but bot-protected content)
    hard_bots = [b for b in bp if b in ("PerimeterX", "DataDome", "Akamai", "Incapsula/Imperva")]
    if hard_bots:
        return f"BLOCKED ({', '.join(hard_bots)}) - not viable"

    if "Cloudflare" in bp:
        if code == 200 and (ej or card):
            return "NEEDS PLAYWRIGHT (Cloudflare present but page loaded)"
        return "BLOCKED (Cloudflare) - needs Playwright + stealth"

    if code == 200:
        if ej:
            return "SCRAPEABLE WITH REQUESTS (embedded JSON found)"
        if card:
            return "SCRAPEABLE WITH REQUESTS (HTML listing cards found)"
        return "UNCLEAR - 200 OK but no listing structure found; may need Playwright"

    return f"UNKNOWN (HTTP {code})"


def main():
    all_results = []
    for site in SITES:
        r = analyze_site(site)
        print_report(r)
        all_results.append(r)
        time.sleep(2)  # polite delay between requests

    print("\n\n" + "="*70)
    print("SUMMARY TABLE")
    print("="*70)
    print(f"{'Site':<22} {'Status':>7}  {'Bot Protection':<30} {'Embedded JSON':<20} {'Verdict'}")
    print("-"*120)
    for r in all_results:
        code = str(r["status_code"]) if r["status_code"] else "ERR"
        bp_str = ", ".join(r["bot_protection"]) if r["bot_protection"] else "-"
        ej_str = ", ".join(r["embedded_json"]) if r["embedded_json"] else "-"
        v = verdict(r)
        print(f"{r['name']:<22} {code:>7}  {bp_str:<30} {ej_str:<20} {v}")


if __name__ == "__main__":
    main()
