"""
Flask REST API – serves both the JSON API and the static frontend files.

Endpoints
---------
GET  /                      → frontend index.html
GET  /api/listings          → paginated listing results
POST /api/scrape            → start a background scrape job
GET  /api/status            → scrape-job status
GET  /api/history           → scrape log (last N runs)
GET  /api/cities            → available Charlotte area filters
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, make_response, request, send_from_directory
from flask_cors import CORS

from database import (
    get_listing_count,
    get_listings,
    get_scrape_history,
    init_db,
    log_scrape,
    upsert_listings,
)
from scraper import CHARLOTTE_AREAS, SCRAPE_SOURCES, CHARLOTTE_ZIP_REGIONS, scrape_charlotte_houses

# Sources that are reliable / don't require a browser install
_ALL_RELIABLE_SOURCES = ["redfin", "estately", "craigslist"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="/")
CORS(app)

# ---------------------------------------------------------------------------
# Scrape state
# ---------------------------------------------------------------------------

_scrape_lock = threading.Lock()
scrape_status: dict = {
    "running":  False,
    "last_run": None,
    "message":  "No scrape run yet.",
}


def _run_scrape(source: str, listing_type: str, max_pages: int) -> None:
    global scrape_status
    started_at = datetime.now(timezone.utc).isoformat()
    type_label = "for sale" if listing_type == "for_sale" else "for rent"

    # "all" — run every reliable source sequentially
    if source == "all":
        sources_to_run = _ALL_RELIABLE_SOURCES
        label = "All Sources"
    else:
        sources_to_run = [source]
        label = SCRAPE_SOURCES.get(source, source)

    with _scrape_lock:
        scrape_status["running"] = True
        scrape_status["message"] = f"Scraping {label} — {type_label} listings in Charlotte…"

    total_found = 0
    total_new   = 0
    errors      = []

    for src in sources_to_run:
        src_label = SCRAPE_SOURCES.get(src, src)
        with _scrape_lock:
            scrape_status["message"] = (
                f"Scraping {src_label} ({sources_to_run.index(src) + 1}/{len(sources_to_run)}) "
                f"— {type_label}…"
            )
        try:
            listings  = scrape_charlotte_houses(src, listing_type, max_pages)
            new_count = upsert_listings(listings)
            completed = datetime.now(timezone.utc).isoformat()
            log_scrape(src, len(listings), new_count, started_at, completed, "success")
            total_found += len(listings)
            total_new   += new_count
            logger.info("[%s] %d listings, %d new", src, len(listings), new_count)
        except Exception as exc:  # noqa: BLE001
            completed = datetime.now(timezone.utc).isoformat()
            log_scrape(src, 0, 0, started_at, completed, "error", str(exc))
            errors.append(f"{src_label}: {exc}")
            logger.error("[%s] scrape failed: %s", src, exc)

    final_completed = datetime.now(timezone.utc).isoformat()
    if errors:
        msg = f"Done with errors. Found {total_found} listings, {total_new} new. Errors: {'; '.join(errors)}"
    else:
        msg = f"Done. Found {total_found} listings, {total_new} new."
    logger.info(msg)
    with _scrape_lock:
        scrape_status["message"]  = msg
        scrape_status["last_run"] = final_completed
        scrape_status["running"]  = False


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
    city         = request.args.get("city")         or None
    bedrooms     = request.args.get("bedrooms")     or None
    bathrooms    = request.args.get("bathrooms")    or None
    min_price    = request.args.get("min_price")    or None
    max_price    = request.args.get("max_price")    or None
    listing_type = request.args.get("listing_type") or None
    source       = request.args.get("source")       or None
    limit        = min(int(request.args.get("limit",  50)), 200)
    offset       = max(int(request.args.get("offset",  0)),   0)

    data  = get_listings(
        city=city, bedrooms=bedrooms, bathrooms=bathrooms,
        min_price=min_price, max_price=max_price,
        limit=limit, offset=offset, listing_type=listing_type, source=source,
    )
    total = get_listing_count(
        city=city, bedrooms=bedrooms, bathrooms=bathrooms,
        min_price=min_price, max_price=max_price,
        listing_type=listing_type, source=source,
    )

    return jsonify({"listings": data, "total": total, "limit": limit, "offset": offset})


@app.route("/api/export.csv", methods=["GET"])
def api_export_csv():
    """Export all matching listings (respecting current filters) as a CSV download."""
    import csv as csv_mod
    import io

    city         = request.args.get("city")         or None
    bedrooms     = request.args.get("bedrooms")     or None
    bathrooms    = request.args.get("bathrooms")    or None
    min_price    = request.args.get("min_price")    or None
    max_price    = request.args.get("max_price")    or None
    listing_type = request.args.get("listing_type") or None
    source       = request.args.get("source")       or None

    rows = get_listings(
        city=city, bedrooms=bedrooms, bathrooms=bathrooms,
        min_price=min_price, max_price=max_price,
        limit=5000, offset=0, listing_type=listing_type, source=source,
    )

    COLS = [
        "title", "price", "location", "bedrooms", "bathrooms", "sqft",
        "property_type", "listing_type", "source", "date_posted", "url",
    ]

    output = io.StringIO()
    writer = csv_mod.DictWriter(output, fieldnames=COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = 'attachment; filename="charlotte_listings.csv"'
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    with _scrape_lock:
        if scrape_status["running"]:
            return jsonify({"error": "A scrape is already in progress."}), 409

    body         = request.get_json(silent=True) or {}
    source       = body.get("source", "redfin")
    listing_type = body.get("listing_type", "for_sale")
    max_pages    = min(int(body.get("max_pages", 2)), 5)

    if source != "all" and source not in SCRAPE_SOURCES:
        return jsonify({"error": f"Unknown source '{source}'."}), 400
    if listing_type not in ("for_sale", "for_rent"):
        return jsonify({"error": f"Unknown listing_type '{listing_type}'."}), 400

    source_label = "All Sources" if source == "all" else SCRAPE_SOURCES[source]

    thread = threading.Thread(
        target=_run_scrape,
        args=(source, listing_type, max_pages),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "message":      f"Scrape started — {source_label}, {listing_type}.",
        "source":       source,
        "listing_type": listing_type,
    })


@app.route("/api/status", methods=["GET"])
def api_status():
    with _scrape_lock:
        return jsonify(dict(scrape_status))


@app.route("/api/history", methods=["GET"])
def api_history():
    return jsonify(get_scrape_history())


@app.route("/api/cities", methods=["GET"])
def api_cities():
    """Return Charlotte-area filter options."""
    cities = [{"value": k, "label": v} for k, v in CHARLOTTE_AREAS.items()]
    return jsonify(cities)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=False, host="0.0.0.0", port=5000)
