"""
SQLite persistence layer for housing listings.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "listings.db")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_connection(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str = DB_PATH) -> None:
    """Create tables if they do not exist yet."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    NOT NULL,
                price        TEXT,
                location     TEXT,
                bedrooms     TEXT,
                sqft         TEXT,
                url          TEXT    UNIQUE,
                date_posted  TEXT,
                date_scraped TEXT,
                source       TEXT,
                city         TEXT,
                created_at   TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scrape_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                city           TEXT,
                listings_found INTEGER,
                listings_new   INTEGER,
                started_at     TEXT,
                completed_at   TEXT,
                status         TEXT,
                error          TEXT
            );
            """
        )
    logger.info("Database initialised at %s", db_path)


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def upsert_listings(listings: list[dict], db_path: str = DB_PATH) -> int:
    """
    Insert listings that are not yet in the database (keyed on URL).

    Returns the number of *new* rows inserted.
    """
    new_count = 0
    with get_connection(db_path) as conn:
        for listing in listings:
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO listings
                        (title, price, location, bedrooms, sqft, url,
                         date_posted, date_scraped, source, city)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.get("title"),
                        listing.get("price"),
                        listing.get("location"),
                        listing.get("bedrooms"),
                        listing.get("sqft"),
                        listing.get("url"),
                        listing.get("date_posted"),
                        listing.get("date_scraped"),
                        listing.get("source"),
                        listing.get("city"),
                    ),
                )
                if cursor.rowcount > 0:
                    new_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Error inserting listing: %s", exc)
        conn.commit()
    return new_count


def get_listings(
    city: str | None = None,
    bedrooms: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str = DB_PATH,
) -> list[dict]:
    """Return listings with optional filters."""
    query = "SELECT * FROM listings WHERE 1=1"
    params: list = []

    if city:
        query += " AND city = ?"
        params.append(city)
    if bedrooms:
        query += " AND bedrooms = ?"
        params.append(bedrooms)

    query += " ORDER BY date_scraped DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_listing_count(
    city: str | None = None,
    db_path: str = DB_PATH,
) -> int:
    """Return total number of listings (optionally filtered by city)."""
    query = "SELECT COUNT(*) AS count FROM listings WHERE 1=1"
    params: list = []
    if city:
        query += " AND city = ?"
        params.append(city)

    with get_connection(db_path) as conn:
        row = conn.execute(query, params).fetchone()
        return row["count"]


# ---------------------------------------------------------------------------
# Scrape log
# ---------------------------------------------------------------------------

def log_scrape(
    city: str,
    listings_found: int,
    listings_new: int,
    started_at: str,
    completed_at: str,
    status: str,
    error: str | None = None,
    db_path: str = DB_PATH,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scrape_log
                (city, listings_found, listings_new,
                 started_at, completed_at, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (city, listings_found, listings_new, started_at, completed_at, status, error),
        )
        conn.commit()


def get_scrape_history(limit: int = 10, db_path: str = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
