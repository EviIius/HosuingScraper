"""
House listing scraper for Charlotte, NC area.

Source: Redfin GIS CSV endpoint.
One visit to the Charlotte search page sets the session cookies that
allow the GIS CSV endpoint to return results for individual ZIP codes.
"""

import csv
import io
import json
import logging
import random
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Charlotte, NC area ZIP codes → Redfin region_ids (region_type=2)
# Discovered by fetching https://www.redfin.com/zipcode/{ZIP} and extracting
# the embedded "region_id=" parameter from the page HTML.
# ---------------------------------------------------------------------------
CHARLOTTE_ZIP_REGIONS: dict[int, int] = {
    28202: 11345,   # Uptown / Center City
    28203: 11346,   # South End / Dilworth
    28204: 11347,   # Elizabeth / Myers Park
    28205: 11348,   # Plaza Midwood / NoDa
    28206: 11349,   # North Charlotte
    28207: 11350,   # Myers Park
    28208: 11351,   # West Charlotte
    28209: 11352,   # Sedgefield / Madison Park
    28210: 11353,   # South Charlotte / Carmel
    28211: 11354,   # Cotswold / Eastover
    28212: 11355,   # East Charlotte / Mint Hill
    28213: 11356,   # University City
    28214: 11357,   # Steele Creek / West Charlotte
    28215: 11358,   # Hickory Ridge / East Charlotte
    28216: 11359,   # Coulwood / NW Charlotte
    28217: 11360,   # Westerly Hills / Airport area
    28226: 11368,   # Ballantyne / Pineville
    28227: 11369,   # Matthews / East Charlotte
    28262: 11393,   # University City / NE Charlotte
    28269: 11397,   # Huntersville / N Charlotte
    28270: 11398,   # Matthews
    28273: 11401,   # Steele Creek / SW Charlotte
    28277: 11404,   # Ballantyne
    28278: 11405,   # Lake Wylie / SW Charlotte
    28134: 11320,   # Pineville
    28105: 11298,   # Matthews
    28104: 11297,   # Matthews / Stallings
}

# Friendly area labels for the filter dropdown
CHARLOTTE_AREAS: dict[str, str] = {
    "charlotte":    "Charlotte",
    "matthews":     "Matthews",
    "weddington":   "Weddington",
    "indian trail": "Indian Trail",
    "pineville":    "Pineville",
    "huntersville": "Huntersville",
    "mint hill":    "Mint Hill",
    "cornelius":    "Cornelius",
    "davidson":     "Davidson",
    "concord":      "Concord",
    "harrisburg":   "Harrisburg",
    "stallings":    "Stallings",
}

SCRAPE_SOURCES: dict[str, str] = {
    "redfin":      "Redfin",
    "zillow":      "Zillow",
    "realtor":     "Realtor.com",
    "craigslist":  "Craigslist",
    "estately":    "Estately",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


def scrape_redfin_charlotte(
    listing_type: str = "for_sale",
    max_pages: int = 1,
    zip_codes: list[int] | None = None,
) -> list[dict]:
    """
    Scrape Redfin house listings for Charlotte, NC.

    Strategy
    --------
    1. Visit https://www.redfin.com/NC/Charlotte to acquire session cookies —
       this is required for the GIS CSV endpoint to return results.
    2. For each Charlotte ZIP code, call the GIS CSV endpoint with the
       verified region_id.

    Parameters
    ----------
    listing_type : 'for_sale' | 'for_rent'
    max_pages    : pages per ZIP (1 page ≈ 200 listings; usually enough per ZIP)
    zip_codes    : specific ZIPs to query; defaults to all Charlotte ZIPs
    """
    status = "9" if listing_type == "for_sale" else "130"
    zips   = zip_codes if zip_codes is not None else list(CHARLOTTE_ZIP_REGIONS.keys())
    now    = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    # ── Step 1: warm-up visit to set session cookies ────────────────────────
    # Use Mecklenburg County page — stable URL that reliably returns 200.
    try:
        warm = session.get(
            "https://www.redfin.com/county/2066/NC/Mecklenburg-County", timeout=20
        )
        logger.info("[redfin] warm-up status %d", warm.status_code)
        time.sleep(random.uniform(2.0, 3.5))
    except Exception as exc:
        logger.warning("[redfin] warm-up failed: %s", exc)

    # ── Step 2: fetch CSV for each ZIP ──────────────────────────────────────
    all_listings: list[dict] = []
    seen_urls:    set[str]   = set()

    for zipcode in zips:
        region_id = CHARLOTTE_ZIP_REGIONS.get(zipcode)
        if not region_id:
            continue

        for page in range(1, max_pages + 1):
            params = {
                "al":          1,
                "market":      "charlotte",
                "num_homes":   200,
                "ord":         "redfin-recommended-asc",
                "page_number": page,
                "region_id":   region_id,
                "region_type": 2,
                "status":      status,
                "uipt":        "1,2,3,4,5,6,7,8",
                "v":           8,
            }

            try:
                resp = session.get(
                    "https://www.redfin.com/stingray/api/gis-csv",
                    params=params,
                    timeout=20,
                    headers={
                        **_HEADERS,
                        "Referer": f"https://www.redfin.com/zipcode/{zipcode}",
                        "Accept":  "text/csv,*/*",
                    },
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.error("[redfin] ZIP %s page %d failed: %s", zipcode, page, exc)
                break

            rows = _parse_redfin_csv(resp.text, listing_type, now, seen_urls)
            if not rows:
                break
            all_listings.extend(rows)
            logger.info("[redfin] ZIP %s page %d: %d listings", zipcode, page, len(rows))

            # Polite delay between ZIP requests
            time.sleep(random.uniform(1.5, 3.0))

    logger.info("[redfin] total scraped: %d listings", len(all_listings))
    return all_listings


def _parse_redfin_csv(
    raw: str,
    listing_type: str,
    scraped_at: str,
    seen_urls: set[str],
) -> list[dict]:
    """
    Parse Redfin GIS CSV.

    The first line is the header (starts with 'SALE TYPE').
    Any line starting with a double-quote is a Redfin disclaimer and is skipped.
    """
    lines = raw.splitlines()

    # Locate header row
    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.upper().startswith("SALE TYPE")),
        None,
    )
    if header_idx is None:
        return []

    # Drop disclaimer lines (wrapped in double quotes)
    data_lines = [
        ln for ln in lines[header_idx + 1:]
        if ln.strip() and not ln.startswith('"')
    ]
    if not data_lines:
        return []

    csv_text = lines[header_idx] + "\n" + "\n".join(data_lines)
    reader   = csv.DictReader(io.StringIO(csv_text))

    # The URL column has a very long name — find it once
    url_key: str | None = None
    out: list[dict] = []

    for row in reader:
        if url_key is None:
            url_key = next(
                (k for k in row if k.strip().upper().startswith("URL")), ""
            )

        address  = (row.get("ADDRESS")              or "").strip()
        city_raw = (row.get("CITY")                 or "").strip()
        state    = (row.get("STATE OR PROVINCE")    or "").strip()
        price    = (row.get("PRICE")                or "").strip()
        beds     = (row.get("BEDS")                 or "").strip()
        baths    = (row.get("BATHS")                or "").strip()
        sqft_raw = (row.get("SQUARE FEET")          or "").strip()
        url      = (row.get(url_key, "") or "").strip() if url_key else ""
        listed   = (row.get("ORIGINAL DATE LISTED") or "").strip()
        prop_raw = (row.get("PROPERTY TYPE")        or "").strip().lower()
        status   = (row.get("STATUS")               or "").strip().lower()

        # Skip non-active or duplicate listings
        if not address or not url:
            continue
        if url in seen_urls:
            continue
        if status and status not in ("active", "active contingent", "coming soon"):
            continue

        seen_urls.add(url)

        out.append({
            "title":         f"{address} – {city_raw}, {state}",
            "price":         price,
            "location":      f"{address}, {city_raw}, {state}",
            "bedrooms":      _norm_beds(beds),
            "bathrooms":     _norm_baths(baths),
            "sqft":          _norm_sqft(sqft_raw),
            "url":           url,
            "date_posted":   listed,
            "date_scraped":  scraped_at,
            "source":        "redfin",
            "city":          _norm_city(city_raw),
            "listing_type":  listing_type,
            "property_type": prop_raw,
        })

    return out


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Known Charlotte-metro city names used to strip builder code prefixes
# (new-construction listings sometimes have a code like "p16mo9 weddington")
_KNOWN_CITIES: set[str] = {
    "charlotte", "matthews", "pineville", "huntersville", "mint hill",
    "cornelius", "davidson", "concord", "harrisburg", "stallings",
    "weddington", "waxhaw", "fort mill", "rock hill", "lake wylie",
    "ballantyne", "belmont", "mooresville", "denver", "iron station",
    "mount holly", "gastonia", "kannapolis", "indian trail", "marvin",
    "monroe", "wesley chapel", "cramerton", "lowell", "bessemer city",
    "uninc",
}


def _norm_city(val: str) -> str:
    """Return a clean lower-case city name, stripping any builder code prefix."""
    city = val.strip().lower()
    if not city:
        return "charlotte"
    if city in _KNOWN_CITIES:
        return city
    # Strip leading code word (e.g. "p16mo9 weddington" → "weddington")
    parts = city.split(" ", 1)
    if len(parts) == 2 and parts[1] in _KNOWN_CITIES:
        return parts[1]
    return city


def _norm_beds(val: str) -> str:
    v = val.strip()
    if v and v not in ("—", "N/A"):
        try:
            return str(int(float(v)))
        except ValueError:
            return v
    return ""


def _norm_baths(val: str) -> str:
    v = val.strip()
    if v and v not in ("—", "N/A"):
        try:
            n = float(v)
            return str(int(n)) if n == int(n) else str(n)
        except ValueError:
            return v
    return ""


def _norm_sqft(val: str) -> str:
    v = val.strip().replace(",", "")
    if v and v not in ("—", "N/A"):
        try:
            return str(int(float(v)))
        except ValueError:
            return v
    return ""


# ---------------------------------------------------------------------------
# Realtor.com scraper
# ---------------------------------------------------------------------------

_REALTOR_HEADERS = {
    **_HEADERS,
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Upgrade-Insecure-Requests": "1",
}

_REALTOR_BASE = "https://www.realtor.com"


def scrape_realtor_charlotte(
    listing_type: str = "for_sale",
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape Realtor.com for Charlotte, NC listings using __NEXT_DATA__ JSON.

    Realtor.com embeds full listing data in a <script id="__NEXT_DATA__"> tag.
    If the site returns 429 (rate limited) the function returns an empty list
    and logs a warning rather than raising.
    """
    search_slug = "Charlotte_NC" if listing_type == "for_sale" else "Charlotte_NC"
    path_prefix = "realestateandhomes-search" if listing_type == "for_sale" else "apartments"
    now = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers.update(_REALTOR_HEADERS)

    all_listings: list[dict] = []
    seen_urls:    set[str]   = set()

    for page in range(1, max_pages + 1):
        url = f"{_REALTOR_BASE}/{path_prefix}/{search_slug}/pg-{page}"
        try:
            resp = session.get(url, timeout=25)
        except Exception as exc:
            logger.warning("[realtor] request failed page %d: %s", page, exc)
            break

        if resp.status_code == 429:
            logger.warning(
                "[realtor] rate-limited (429) on page %d — "
                "Realtor.com is blocking automated requests. "
                "Try again later or use a different source.",
                page,
            )
            break
        if resp.status_code != 200:
            logger.warning("[realtor] unexpected status %d on page %d", resp.status_code, page)
            break

        # Extract __NEXT_DATA__ JSON
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not m:
            logger.warning("[realtor] no __NEXT_DATA__ found on page %d", page)
            break

        try:
            data = json.loads(m.group(1))
        except Exception:
            logger.warning("[realtor] failed to parse __NEXT_DATA__ on page %d", page)
            break

        rows = _parse_realtor_next_data(data, listing_type, now, seen_urls)
        if not rows:
            logger.info("[realtor] no listings on page %d — stopping", page)
            break

        all_listings.extend(rows)
        logger.info("[realtor] page %d: %d listings", page, len(rows))
        time.sleep(random.uniform(3.0, 5.0))

    logger.info("[realtor] total scraped: %d listings", len(all_listings))
    return all_listings


def _parse_realtor_next_data(
    data: dict,
    listing_type: str,
    scraped_at: str,
    seen_urls: set[str],
) -> list[dict]:
    """Extract listings from Realtor.com __NEXT_DATA__ JSON."""
    # Common paths for listing results
    page_props = data.get("props", {}).get("pageProps", {})

    # Try several known JSON paths used by Realtor.com
    results: list = []
    for path in [
        ["searchResults", "home_search", "results"],
        ["searchResults", "results"],
        ["properties"],
        ["homes"],
    ]:
        node = page_props
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, list) and node:
            results = node
            break

    out: list[dict] = []
    for item in results:
        loc    = item.get("location", {}) or {}
        addr   = loc.get("address", {}) or {}
        desc   = item.get("description", {}) or {}

        address  = addr.get("line", "")
        city_raw = addr.get("city", "")
        state    = addr.get("state_code", "NC")
        price    = str(item.get("list_price", item.get("price", "")) or "")
        beds     = str(desc.get("beds", "") or "")
        baths    = str(desc.get("baths_consolidated", desc.get("baths", "")) or "")
        sqft     = str(desc.get("sqft", "") or "")
        prop_raw = (desc.get("type", "") or "").lower()
        listed   = item.get("list_date", "")
        status   = (item.get("status", "") or "").lower()
        permalink = item.get("permalink", "")
        url      = f"{_REALTOR_BASE}{permalink}" if permalink else ""

        if not address or not url:
            continue
        if url in seen_urls:
            continue
        if status and status not in ("for_sale", "active", "for_rent", ""):
            continue

        seen_urls.add(url)
        out.append({
            "title":         f"{address} \u2013 {city_raw}, {state}",
            "price":         price,
            "location":      f"{address}, {city_raw}, {state}",
            "bedrooms":      _norm_beds(beds),
            "bathrooms":     _norm_baths(baths),
            "sqft":          _norm_sqft(sqft),
            "url":           url,
            "date_posted":   listed,
            "date_scraped":  scraped_at,
            "source":        "realtor",
            "city":          _norm_city(city_raw),
            "listing_type":  listing_type,
            "property_type": prop_raw,
        })

    return out


# ---------------------------------------------------------------------------
# Zillow scraper (Playwright headless browser)
# ---------------------------------------------------------------------------

_ZILLOW_BASE = "https://www.zillow.com"
_ZILLOW_UA   = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def scrape_zillow_charlotte(
    listing_type: str = "for_sale",
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape Zillow for Charlotte, NC listings using a headless Chromium browser.

    Playwright intercepts Zillow's internal GetSearchPageState API responses
    which contain full JSON listing data, bypassing PerimeterX bot detection.

    Requires: `python -m playwright install chromium` (one-time setup).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright"
        )

    # playwright-stealth applies comprehensive fingerprint spoofing
    try:
        from playwright_stealth import stealth_sync as _stealth_fn
        logger.info("[zillow] playwright-stealth loaded")
    except ImportError:
        _stealth_fn = None
        logger.warning("[zillow] playwright-stealth not installed; bot detection may block scraping")

    now = datetime.now(timezone.utc).isoformat()

    if listing_type == "for_rent":
        base_path = "charlotte-nc/rentals"
    else:
        base_path = "charlotte-nc"

    all_listings: list[dict] = []
    seen_urls:    set[str]   = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=_ZILLOW_UA,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                java_script_enabled=True,
                accept_downloads=False,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest":  "document",
                    "Sec-Fetch-Mode":  "navigate",
                    "Sec-Fetch-Site":  "none",
                },
            )
            # Remove navigator.webdriver fingerprint at context level
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            for pg in range(1, max_pages + 1):
                path    = f"{base_path}/{pg}_p/" if pg > 1 else f"{base_path}/"
                url     = f"{_ZILLOW_BASE}/{path}"
                captured: list[dict] = []

                def _on_response(response, _captured=captured):
                    if "GetSearchPageState" in response.url and response.status == 200:
                        try:
                            _captured.append(response.json())
                        except Exception:
                            pass

                page = context.new_page()
                # Apply comprehensive stealth patches before navigation
                if _stealth_fn:
                    try:
                        _stealth_fn(page)
                    except Exception as se:
                        logger.debug("[zillow] stealth patch error: %s", se)
                page.on("response", _on_response)

                try:
                    # Use "load" instead of "networkidle" — PerimeterX challenges
                    # keep connections open, preventing networkidle from settling.
                    page.goto(url, wait_until="load", timeout=40000)
                    # Wait for async GetSearchPageState API call to complete
                    page.wait_for_timeout(7000)
                except PWTimeout:
                    logger.warning("[zillow] page %d timed out, using what was captured", pg)
                except Exception as exc:
                    logger.warning("[zillow] navigation error page %d: %s", pg, exc)

                page.close()

                if not captured:
                    logger.warning("[zillow] no API response captured on page %d", pg)
                    break

                rows = _parse_zillow_response(captured[-1], listing_type, now, seen_urls)
                if not rows:
                    logger.info("[zillow] page %d returned 0 listings — stopping", pg)
                    break

                all_listings.extend(rows)
                logger.info("[zillow] page %d: %d listings", pg, len(rows))

                if pg < max_pages:
                    page_wait = context.new_page()
                    page_wait.wait_for_timeout(random.randint(3000, 5500))
                    page_wait.close()

            browser.close()

    except Exception as exc:
        # Surface the error cleanly — don't silently return empty
        msg = str(exc)
        if "Executable doesn't exist" in msg or "chromium" in msg.lower():
            raise RuntimeError(
                "Zillow scraper requires Playwright browsers. "
                "Run: python -m playwright install chromium"
            ) from exc
        raise

    logger.info("[zillow] total scraped: %d listings", len(all_listings))
    return all_listings


def _parse_zillow_response(
    data: dict,
    listing_type: str,
    scraped_at: str,
    seen_urls: set[str],
) -> list[dict]:
    """Extract listings from a Zillow GetSearchPageState JSON response."""
    # Try common paths for listing results
    results: list = []
    for path in [
        ["cat1", "searchResults", "listResults"],
        ["cat2", "searchResults", "listResults"],
        ["mapResults"],
    ]:
        node = data
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list) and node:
            results = node
            break

    out: list[dict] = []
    for item in results:
        address  = (item.get("addressStreet") or "").strip()
        city_raw = (item.get("addressCity")   or "").strip()
        state    = (item.get("addressState")  or "NC").strip()
        price    = str(item.get("unformattedPrice") or item.get("price") or "")
        beds     = str(item.get("beds")  or "")
        baths    = str(item.get("baths") or "")
        sqft     = str(item.get("area")  or "")
        detail   = (item.get("detailUrl") or "").strip()
        prop_raw = (item.get("propertyType") or "").lower().replace("_", " ")
        listed   = ""  # Zillow doesn't expose raw date in this endpoint

        # Skip non-residential / non-Charlotte results
        if not address or not detail:
            continue
        url = detail if detail.startswith("http") else f"{_ZILLOW_BASE}{detail}"
        if url in seen_urls:
            continue

        # Skip sold/off-market
        status = (item.get("statusType") or "").upper()
        if status in ("RECENTLY_SOLD", "OTHER"):
            continue

        seen_urls.add(url)
        out.append({
            "title":         f"{address} \u2013 {city_raw}, {state}",
            "price":         price,
            "location":      f"{address}, {city_raw}, {state}",
            "bedrooms":      _norm_beds(beds),
            "bathrooms":     _norm_baths(baths),
            "sqft":          _norm_sqft(sqft),
            "url":           url,
            "date_posted":   listed,
            "date_scraped":  scraped_at,
            "source":        "zillow",
            "city":          _norm_city(city_raw),
            "listing_type":  listing_type,
            "property_type": prop_raw,
        })

    return out


# ---------------------------------------------------------------------------
# Estately scraper
# ---------------------------------------------------------------------------

_ESTATELY_BASE = "https://www.estately.com"


def scrape_estately_charlotte(
    listing_type: str = "for_sale",
    max_pages: int = 5,
) -> list[dict]:
    """
    Scrape Estately for Charlotte, NC listings.

    Estately serves fully server-rendered HTML (Ruby on Rails app) with no
    significant bot protection — standard requests + BeautifulSoup works fine.

    Structure:
      Container : div.full-height-padded-wrapper  (15 listings per page)
      Address   : h2.result-address a             (href = listing URL)
      Prop type : h2.result-address small
      Price     : p.result-price strong
      Details   : div.result-basics li            (<b>N</b> beds/baths/sqft)
      Pagination: ?page=N  (up to page 18 visible; ~270 listings for sale)
    """
    base_url = f"{_ESTATELY_BASE}/NC/Charlotte"
    if listing_type == "for_rent":
        base_url += "?only_rent=true"
        page_sep = "&"
    else:
        page_sep = "?"

    now = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": _ESTATELY_BASE,
    })

    all_listings: list[dict] = []
    seen_urls:    set[str]   = set()

    for pg in range(1, max_pages + 1):
        url = base_url if pg == 1 else f"{base_url}{page_sep}page={pg}"
        try:
            resp = session.get(url, timeout=25)
        except Exception as exc:
            logger.error("[estately] request failed page %d: %s", pg, exc)
            break

        if resp.status_code != 200:
            logger.warning("[estately] status %d on page %d", resp.status_code, pg)
            break

        soup = BeautifulSoup(resp.text, "lxml")
        wrappers = soup.find_all(class_="full-height-padded-wrapper")
        if not wrappers:
            logger.info("[estately] no listing wrappers on page %d — stopping", pg)
            break

        page_count = 0
        for item in wrappers:
            # Address + URL
            addr_link = item.select_one("h2.result-address a")
            if not addr_link:
                continue
            address_text = addr_link.get_text(strip=True)
            href = addr_link.get("href", "").strip()
            if not href:
                continue
            if not href.startswith("http"):
                href = _ESTATELY_BASE + href
            if href in seen_urls:
                continue

            # Property type  ("House For Sale", "Condo For Sale", etc.)
            small_el = item.select_one("h2.result-address small")
            prop_raw = small_el.get_text(strip=True).lower() if small_el else ""
            # Strip listing-type suffix ("for sale" / "for rent")
            prop_type = re.sub(r"\s*for\s+(sale|rent)$", "", prop_raw).strip()

            # Price
            price_el = item.select_one("p.result-price strong")
            price_raw = (
                price_el.get_text(strip=True).replace("$", "").replace(",", "")
                if price_el else ""
            )

            # Beds / baths / sqft from result-basics list items
            beds = baths = sqft = ""
            for li in item.select("div.result-basics li"):
                bold = li.find("b")
                if not bold:
                    continue
                num  = bold.get_text(strip=True)
                rest = li.get_text(strip=True).replace(num, "", 1).strip().lower()
                if "bed" in rest:
                    beds = num
                elif "bath" in rest:
                    baths = num
                elif "sqft" in rest and "lot" not in rest and not sqft:
                    sqft = num.replace(",", "")

            # Parse city from address "Street, City, State"
            parts    = [p.strip() for p in address_text.split(",")]
            city_raw = parts[-2] if len(parts) >= 3 else "Charlotte"

            seen_urls.add(href)
            all_listings.append({
                "title":         address_text,
                "price":         price_raw,
                "location":      address_text,
                "bedrooms":      _norm_beds(beds),
                "bathrooms":     _norm_baths(baths),
                "sqft":          _norm_sqft(sqft),
                "url":           href,
                "date_posted":   "",
                "date_scraped":  now,
                "source":        "estately",
                "city":          _norm_city(city_raw),
                "listing_type":  listing_type,
                "property_type": prop_type,
            })
            page_count += 1

        logger.info("[estately] page %d: %d listings", pg, page_count)
        time.sleep(random.uniform(2.0, 3.5))

    logger.info("[estately] total scraped: %d listings", len(all_listings))
    return all_listings


# ---------------------------------------------------------------------------
# Craigslist scraper
# ---------------------------------------------------------------------------

_CL_BASE = "https://charlotte.craigslist.org"


def scrape_craigslist_charlotte(
    listing_type: str = "for_sale",
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape Craigslist Charlotte for housing listings.

    For sale : /search/rea  (real estate — for sale by owner & broker)
    For rent : /search/apa  (apartments / housing for rent)

    Craigslist serves plain server-side HTML with no meaningful bot protection,
    so standard requests + BeautifulSoup works reliably.
    Each page returns up to 120 results; paginate with ?s=0, ?s=120, …
    """
    search_path = "/search/apa" if listing_type == "for_rent" else "/search/rea"
    now = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    all_listings: list[dict] = []
    seen_urls:    set[str]   = set()

    for pg in range(max_pages):
        url = f"{_CL_BASE}{search_path}?s={pg * 120}"
        try:
            resp = session.get(url, timeout=20)
        except Exception as exc:
            logger.error("[craigslist] request failed page %d: %s", pg + 1, exc)
            break

        if resp.status_code != 200:
            logger.warning("[craigslist] status %d on page %d", resp.status_code, pg + 1)
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # ── Parse JSON-LD for structured address / bed / bath data ──────────
        ld_by_title: dict[str, dict] = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "ItemList":
                    for element in data.get("itemListElement", []):
                        item = element.get("item", element)
                        name = (item.get("name") or "").strip()
                        if name:
                            ld_by_title[name.lower()[:80]] = item
                    break
            except Exception:
                pass

        # ── Parse HTML listing rows ─────────────────────────────────────────
        # Craigslist has used multiple layouts over time; support all known variants.
        results = (
            soup.select("li.cl-static-search-result")  # current (2025+)
            or soup.select("li.cl-search-result")       # previous layout
            or soup.select("li.result-row")             # old layout
        )

        if not results:
            logger.info("[craigslist] no results found on page %d — stopping", pg + 1)
            break

        page_count = 0
        for row in results:
            # ── Current layout: <li title="..."><a href="..."><div class="title">...</div>
            # ── Older layouts:  <li><a class="posting-title ...">
            link = row.find("a")
            if not link:
                continue

            # Title: prefer .title div text, fall back to li title attr, then link text
            title_div = row.select_one(".title")
            title = (
                title_div.get_text(strip=True)
                or row.get("title", "")
                or link.get_text(strip=True)
            ).strip()

            href = link.get("href", "").strip()
            if not href:
                continue
            if not href.startswith("http"):
                href = _CL_BASE + href
            if href in seen_urls:
                continue

            # Price
            price_el = row.select_one(".price") or row.select_one(".result-price")
            price_raw = price_el.get_text(strip=True).replace("$", "").replace(",", "") if price_el else ""

            # Beds / baths from housing blurb ("3br 2ba") — older layouts only
            housing_el = row.select_one(".housing") or row.select_one(".result-housing")
            beds, baths = _parse_cl_housing(housing_el.get_text() if housing_el else "")

            # Neighborhood — new layout uses .location, old used .result-hood / .hood
            hood_el = (
                row.select_one(".location")
                or row.select_one(".result-hood")
                or row.select_one(".hood")
            )
            hood = hood_el.get_text(strip=True).strip("() ") if hood_el else ""

            # Date
            date_el = row.select_one("time")
            date_posted = (date_el.get("datetime") or "")[:10] if date_el else ""

            # Supplement with JSON-LD address if available
            ld = ld_by_title.get(title.lower()[:80], {})
            addr_obj  = ld.get("address") or {}
            locality  = addr_obj.get("addressLocality", "") if isinstance(addr_obj, dict) else ""
            region    = addr_obj.get("addressRegion", "NC")  if isinstance(addr_obj, dict) else "NC"
            if not beds:
                beds  = str(ld.get("numberOfBedrooms",  "")) if ld.get("numberOfBedrooms")  else beds
            if not baths:
                baths = str(ld.get("numberOfBathroomsTotal", "")) if ld.get("numberOfBathroomsTotal") else baths

            city_raw = locality or hood or "Charlotte"
            # Skip listings clearly outside the Charlotte metro
            city_norm = _norm_city(city_raw)

            seen_urls.add(href)
            all_listings.append({
                "title":         title,
                "price":         price_raw,
                "location":      f"{city_raw}, {region}",
                "bedrooms":      _norm_beds(str(beds)),
                "bathrooms":     _norm_baths(str(baths)),
                "sqft":          "",
                "url":           href,
                "date_posted":   date_posted,
                "date_scraped":  now,
                "source":        "craigslist",
                "city":          city_norm,
                "listing_type":  listing_type,
                "property_type": (ld.get("@type") or "").lower(),
            })
            page_count += 1

        logger.info("[craigslist] page %d: %d listings", pg + 1, page_count)
        time.sleep(random.uniform(2.0, 3.5))

    logger.info("[craigslist] total scraped: %d listings", len(all_listings))
    return all_listings


def _parse_cl_housing(text: str) -> tuple[str, str]:
    """Parse Craigslist housing blurb '3br 2ba' → ('3', '2')."""
    beds  = ""
    baths = ""
    bed_m  = re.search(r"(\d+)\s*[Bb][Rr]", text)
    bath_m = re.search(r"(\d+(?:\.\d)?)\s*[Bb][Aa]", text)
    if bed_m:
        beds  = bed_m.group(1)
    if bath_m:
        baths = bath_m.group(1)
    return beds, baths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_charlotte_houses(
    source: str = "redfin",
    listing_type: str = "for_sale",
    max_pages: int = 1,
) -> list[dict]:
    """
    Main entry point for scraping Charlotte, NC house listings.

    Parameters
    ----------
    source       : 'redfin' | 'zillow' | 'realtor'
    listing_type : 'for_sale' | 'for_rent'
    max_pages    : pages to fetch
    """
    if source == "zillow":
        return scrape_zillow_charlotte(listing_type, max_pages)
    if source == "realtor":
        return scrape_realtor_charlotte(listing_type, max_pages)
    if source == "craigslist":
        return scrape_craigslist_charlotte(listing_type, max_pages)
    if source == "estately":
        return scrape_estately_charlotte(listing_type, max_pages)
    return scrape_redfin_charlotte(listing_type, max_pages)
