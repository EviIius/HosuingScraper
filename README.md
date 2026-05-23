# Charlotte House Finder

A Charlotte, NC housing scraper that pulls listings from six sources —
houses, townhomes, condos, and apartments — into a single filterable
frontend backed by SQLite.

Three of the sources (Zillow, Realtor.com, Apartments.com) use anti-bot
protection. We bypass them with **SeleniumBase UC Mode**, which drives a
real headless Chrome and defeats Cloudflare/PerimeterX out of the box. No
paid APIs, no proxies.

---

## Sources

| Source             | Method                                       | Covers                        |
|--------------------|----------------------------------------------|-------------------------------|
| **Redfin**         | GIS CSV endpoint (cookie-warmed `requests`)  | Houses / condos / townhomes   |
| **Estately**       | Plain `requests` + BS4 (no bot protection)   | Houses                        |
| **Craigslist**     | Plain `requests` + BS4                       | Rentals + FSBO                |
| **Zillow**         | SeleniumBase UC → `__NEXT_DATA__` JSON       | Everything (sale + rent)      |
| **Realtor.com**    | SeleniumBase UC → JSON-LD `ItemList`         | Houses / townhomes (sale)     |
| **Apartments.com** | SeleniumBase UC → `article.placard` DOM      | Apartments / townhomes (rent) |

Three sources are "fast" (plain HTTP, run in a few seconds) and three are
"browser" (10–30 s each, headless Chrome).

---

## Quick Start

```bash
# 1. Create + activate a virtual environment
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate          # macOS/Linux

# 2. Install dependencies (downloads chromedriver on first browser-source run)
pip install -r backend/requirements.txt

# 3. Run the server
cd backend
python app.py
```

The server starts on <http://localhost:5000> and serves the frontend on
the same origin.

### Scraping

Click **Scrape Now**. You'll see two "all" options plus six individual
sources:

- **Fast Sources** — Redfin + Estately + Craigslist. Finishes in seconds.
- **All Sources (incl. browser)** — adds Zillow + Realtor + Apartments.
  Slower (~1–2 min), but full coverage of houses, townhomes, apartments.

Pick one, choose For Sale or For Rent, set max pages, and start. The
header badge polls progress and the grid refreshes when the run finishes.

---

## API Reference

| Method | Path                  | Description |
|--------|-----------------------|-------------|
| `GET`  | `/api/listings`       | Paginated results. Query params: `city`, `bedrooms`, `bathrooms`, `min_price`, `max_price`, `listing_type`, `source`, `limit`, `offset` |
| `POST` | `/api/scrape`         | Start a scrape. Body: `{ "source": "all"\|"all_full"\|"redfin"\|"zillow"\|..., "listing_type": "for_sale"\|"for_rent", "max_pages": 1-5 }` |
| `GET`  | `/api/status`         | Current scrape job status |
| `GET`  | `/api/history`        | Last 10 scrape runs |
| `GET`  | `/api/cities`         | Charlotte-area filter options |
| `GET`  | `/api/export.csv`     | Download current filter set as CSV |

---

## Project Layout

```text
backend/
  app.py            Flask API + static file serving
  scraper.py        All six source scrapers + dispatcher
  database.py       SQLite CRUD layer
  requirements.txt
  tests/
    test_database.py
frontend/
  index.html
  styles.css
  app.js
scrape_diagnostic.py  Standalone tool to check anti-bot status of any site
```

---

## Notes

- For personal, non-commercial use only.
- SeleniumBase downloads the matching Chromedriver automatically on first
  run; you don't need to install it manually.
- If your Windows machine has strict Application Control / Smart App
  Control, install the venv outside protected directories — Selenium's
  `.pyd` files need to load freely.
- Apartments.com only carries rentals; selecting "For Sale" with that
  source returns an empty list cleanly.

---

## Running Tests

```bash
cd backend
pytest tests/test_database.py -v
```
