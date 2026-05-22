# Housing Scraper

A web scraper that collects apartment listings from **Craigslist** and
presents them in a clean, filterable frontend interface.  Scrapes can be
triggered manually at any time; new listings are merged into a local SQLite
database so re-runs only store genuinely new records.

---

## Features

| Feature | Details |
|---|---|
| Multi-city scraping | SF Bay Area, New York, LA, Chicago, Seattle, Austin, Denver, Boston |
| Incremental updates | Re-scraping only adds listings not already in the database (deduped by URL) |
| Scrape history | Every run is logged with timing, count of new listings, and status |
| REST API | JSON endpoints for listings, scrape trigger, status, and history |
| Responsive UI | Card-based grid, city + bedroom filters, pagination |

---

## Project Layout

```
backend/
  app.py           Flask application (API + static file serving)
  scraper.py       Craigslist apartment scraper
  database.py      SQLite CRUD layer
  requirements.txt Python dependencies
  tests/
    test_database.py
    test_scraper.py
frontend/
  index.html       Single-page interface
  styles.css       Responsive stylesheet
  app.js           Frontend logic (fetch, render, poll)
.gitignore
README.md
```

---

## Quick Start

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 3. Run the server

```bash
cd backend
python app.py
```

The server starts on **http://localhost:5000**.  
Open that URL in your browser – the frontend is served automatically.

### 4. Scrape listings

Click **Scrape Now** in the top-right corner, choose a city and the number
of pages (1 page ≈ 120 listings), then click **Start Scrape**.  
The badge in the header shows live status; the grid refreshes automatically
when the scrape completes.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/listings` | Paginated listing results. Query params: `city`, `bedrooms`, `limit`, `offset` |
| `POST` | `/api/scrape` | Start a scrape. Body: `{ "city": "sfbay", "max_pages": 2 }` |
| `GET` | `/api/status` | Current scrape status (`running`, `message`, `last_run`) |
| `GET` | `/api/history` | Last 10 scrape-run records |
| `GET` | `/api/cities` | Supported cities list |

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Notes

- Data is sourced from Craigslist.  For personal, non-commercial use only.
- Craigslist may rate-limit repeated requests; the scraper pauses 1.5 s
  between pages to be respectful.
- The scraper detects whether the page uses the old (pre-2022) or new
  (post-2022) Craigslist HTML layout and parses either automatically.