"""
Flask REST API – serves both the JSON API and the static frontend files.

Endpoints
---------
GET  /                      → frontend index.html
GET  /api/listings          → paginated listing results
POST /api/scrape            → start a background scrape job
GET  /api/status            → scrape-job status
GET  /api/history           → scrape log (last N runs)
GET  /api/cities            → available cities
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from database import (
    get_listing_count,
    get_listings,
    get_scrape_history,
    init_db,
    log_scrape,
    upsert_listings,
)
from scraper import SUPPORTED_CITIES, scrape_craigslist_housing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="/")
CORS(app)

# ---------------------------------------------------------------------------
# Scrape state (simple in-process tracker – sufficient for a single worker)
# ---------------------------------------------------------------------------

_scrape_lock = threading.Lock()
scrape_status: dict = {
    "running": False,
    "last_run": None,
    "message": "No scrape run yet.",
}


def _run_scrape(city: str, max_pages: int) -> None:
    global scrape_status
    started_at = datetime.now(timezone.utc).isoformat()

    with _scrape_lock:
        scrape_status["running"] = True
        scrape_status["message"] = f"Scraping {SUPPORTED_CITIES.get(city, city)}…"

    try:
        listings = scrape_craigslist_housing(city=city, max_pages=max_pages)
        new_count = upsert_listings(listings)
        completed_at = datetime.now(timezone.utc).isoformat()
        log_scrape(city, len(listings), new_count, started_at, completed_at, "success")
        msg = f"Done. Found {len(listings)} listings, {new_count} new."
        logger.info(msg)
        with _scrape_lock:
            scrape_status["message"] = msg
            scrape_status["last_run"] = completed_at
    except Exception as exc:  # noqa: BLE001
        completed_at = datetime.now(timezone.utc).isoformat()
        log_scrape(city, 0, 0, started_at, completed_at, "error", str(exc))
        msg = f"Scrape failed: {exc}"
        logger.error(msg)
        with _scrape_lock:
            scrape_status["message"] = msg
    finally:
        with _scrape_lock:
            scrape_status["running"] = False


# ---------------------------------------------------------------------------
# Routes – static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Routes – API
# ---------------------------------------------------------------------------

@app.route("/api/listings", methods=["GET"])
def api_listings():
    city = request.args.get("city") or None
    bedrooms = request.args.get("bedrooms") or None
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = max(int(request.args.get("offset", 0)), 0)

    data = get_listings(city=city, bedrooms=bedrooms, limit=limit, offset=offset)
    total = get_listing_count(city=city)

    return jsonify({"listings": data, "total": total, "limit": limit, "offset": offset})


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    with _scrape_lock:
        if scrape_status["running"]:
            return jsonify({"error": "A scrape is already in progress."}), 409

    body = request.get_json(silent=True) or {}
    city = body.get("city", "sfbay")
    if city not in SUPPORTED_CITIES:
        return jsonify({"error": f"Unknown city '{city}'."}), 400

    max_pages = min(int(body.get("max_pages", 2)), 5)

    thread = threading.Thread(target=_run_scrape, args=(city, max_pages), daemon=True)
    thread.start()

    return jsonify({"message": f"Scrape started for {SUPPORTED_CITIES[city]}.", "city": city})


@app.route("/api/status", methods=["GET"])
def api_status():
    with _scrape_lock:
        return jsonify(dict(scrape_status))


@app.route("/api/history", methods=["GET"])
def api_history():
    return jsonify(get_scrape_history())


@app.route("/api/cities", methods=["GET"])
def api_cities():
    cities = [{"value": k, "label": v} for k, v in SUPPORTED_CITIES.items()]
    return jsonify(cities)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=False, host="0.0.0.0", port=5000)
