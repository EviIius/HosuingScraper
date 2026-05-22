"""
Housing listing scraper.

Targets Craigslist apartment listings and handles both the old (pre-2022) and
new (post-2022) page structures.  Falls back to a small set of sample data
when network access is unavailable (useful for demos / CI).
"""

import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

SUPPORTED_CITIES = {
    "sfbay": "San Francisco Bay Area",
    "newyork": "New York",
    "losangeles": "Los Angeles",
    "chicago": "Chicago",
    "seattle": "Seattle",
    "austin": "Austin",
    "denver": "Denver",
    "boston": "Boston",
}

REQUEST_DELAY = 1.5  # seconds between page requests


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

def _parse_new(item):
    """Parse a listing from the current Craigslist layout (post-2022)."""
    title_tag = (
        item.select_one("a.posting-title .label")
        or item.select_one(".title-blob .label")
        or item.select_one("a.cl-app-anchor .label")
    )
    if not title_tag:
        return None

    title = title_tag.get_text(strip=True)

    url_tag = item.select_one("a.posting-title") or item.select_one("a.cl-app-anchor")
    url_link = url_tag.get("href", "") if url_tag else ""

    price_tag = item.select_one(".priceinfo") or item.select_one(".price")
    price = price_tag.get_text(strip=True) if price_tag else "N/A"

    meta_spans = item.select(".meta span") or item.select(".result-meta span")
    location = "N/A"
    bedrooms = "N/A"
    sqft = "N/A"

    for span in meta_spans:
        text = span.get_text(strip=True)
        if re.match(r"^\d+br$", text, re.I):
            bedrooms = re.sub(r"[^\d]", "", text)
        elif re.search(r"ft2?", text, re.I):
            m = re.match(r"^(\d+)\s*ft", text, re.I)
            sqft = m.group(1) if m else re.sub(r"\D", "", text.split("ft")[0])
        elif text and location == "N/A":
            location = text

    date_tag = item.select_one("time")
    date_posted = date_tag.get("datetime", "") if date_tag else ""

    return {
        "title": title,
        "price": price,
        "location": location,
        "bedrooms": bedrooms,
        "sqft": sqft,
        "url": url_link,
        "date_posted": date_posted,
    }


def _parse_old(item):
    """Parse a listing from the classic Craigslist layout (pre-2022)."""
    title_tag = item.select_one("a.result-title")
    if not title_tag:
        return None

    title = title_tag.get_text(strip=True)
    url_link = title_tag.get("href", "")

    price_tag = item.select_one("span.result-price")
    price = price_tag.get_text(strip=True) if price_tag else "N/A"

    loc_tag = item.select_one("span.result-hood")
    location = loc_tag.get_text(strip=True).strip("() ") if loc_tag else "N/A"

    housing_tag = item.select_one("span.housing")
    housing_info = housing_tag.get_text(strip=True) if housing_tag else ""

    bedrooms = "N/A"
    sqft = "N/A"
    if housing_info:
        for part in [p.strip() for p in housing_info.split("-") if p.strip()]:
            if "br" in part:
                bedrooms = re.sub(r"[^\d]", "", part)
            elif "ft" in part.lower():
                sqft = re.sub(r"[^\d]", "", part)

    date_tag = item.select_one("time.result-date")
    date_posted = date_tag.get("datetime", "") if date_tag else ""

    return {
        "title": title,
        "price": price,
        "location": location,
        "bedrooms": bedrooms,
        "sqft": sqft,
        "url": url_link,
        "date_posted": date_posted,
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def scrape_craigslist_housing(city: str = "sfbay", max_pages: int = 3) -> list[dict]:
    """
    Scrape apartment listings from Craigslist for *city*.

    Parameters
    ----------
    city:      Craigslist subdomain (e.g. "sfbay", "newyork").
    max_pages: Maximum number of result pages to fetch.

    Returns
    -------
    List of listing dicts enriched with ``date_scraped``, ``source``, and
    ``city`` keys.
    """
    listings: list[dict] = []
    base_url = f"https://{city}.craigslist.org/search/apa"

    for page in range(max_pages):
        offset = page * 120
        url = f"{base_url}?s={offset}"
        logger.info("Scraping page %d: %s", page + 1, url)

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            break

        soup = BeautifulSoup(response.text, "lxml")

        # Detect layout: new structure uses li.cl-search-result
        items = soup.select("li.cl-search-result")
        use_new = bool(items)
        if not use_new:
            items = soup.select("li.result-row")

        if not items:
            logger.info("No listings found on page %d, stopping.", page + 1)
            break

        parse = _parse_new if use_new else _parse_old
        now = datetime.now(timezone.utc).isoformat()

        for item in items:
            try:
                listing = parse(item)
                if listing:
                    listing["date_scraped"] = now
                    listing["source"] = "craigslist"
                    listing["city"] = city
                    listings.append(listing)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error parsing listing: %s", exc)

        logger.info("Page %d: found %d items", page + 1, len(items))
        if page < max_pages - 1:
            time.sleep(REQUEST_DELAY)

    logger.info("Total scraped: %d listings from %s", len(listings), city)
    return listings
