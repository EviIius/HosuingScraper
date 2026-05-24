"""
Geocode listing addresses using Nominatim (OpenStreetMap).
Rate-limited to 1 req/sec per OSM policy.
"""
import logging
import re
import time

import requests

from database import get_ungeocoded_listings, update_listing_coords

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "CharlotteHouseFinder/1.0"})


def _clean_address(title: str, location: str, zip_code: str) -> str:
    """Build a clean address string for geocoding."""
    addr = (title or location or "").strip()
    # Remove non-breaking spaces and encoding artifacts
    addr = addr.replace("\xa0", " ").replace("\ufffd", "")
    # Strip source suffixes like "– Charlotte, NC"
    addr = re.sub(r"\s*[–-]\s*Charlotte.*$", "", addr, flags=re.IGNORECASE)
    # Normalise unit separators
    addr = re.sub(r"\s*(apt\.?|unit|ste\.?|#)\s*", " ", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\s+", " ", addr).strip()
    if zip_code:
        return f"{addr}, Charlotte, NC {zip_code}"
    return f"{addr}, Charlotte, NC"


def geocode_address(address: str) -> tuple[float, float] | None:
    """Call Nominatim for a single address. Returns (lat, lng) or None."""
    try:
        resp = _SESSION.get(
            _NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        logger.warning("Geocode failed for %r: %s", address, exc)
    return None


def geocode_pending_listings(batch_size: int = 500) -> int:
    """
    Geocode up to batch_size listings that have no coordinates.
    Respects Nominatim's 1 req/sec rate limit.
    Returns number of listings successfully geocoded.
    """
    rows = get_ungeocoded_listings(limit=batch_size)
    if not rows:
        return 0

    logger.info("Geocoding %d listings…", len(rows))
    geocoded = 0
    for row in rows:
        address = _clean_address(row["title"], row["location"], row["zip"])
        coords = geocode_address(address)
        if coords:
            update_listing_coords(row["id"], coords[0], coords[1])
            geocoded += 1
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

    logger.info("Geocoded %d/%d listings", geocoded, len(rows))
    return geocoded
